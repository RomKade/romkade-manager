"""Construit la table de genres embarquée (app/data/genres.json.gz).

Usage (depuis backend/) :
    .venv/bin/python scripts/build_genres.py

À lancer seulement pour rafraîchir les sources : l'application lit le fichier produit, sans réseau.
Sources :
- https://github.com/libretro/libretro-database (metadat/genre/*.dat) : consoles, par nom No-Intro ;
- https://github.com/AntoPISA/MAME_SupportFiles (catver.ini, progettoSNAPS) : arcade, par nom court MAME ;
- libretro-database (MAME, FBNeo, HBMAME) : titre complet des jeux d'arcade (« sf2 » -> « Street Fighter II… »).
Les genres d'origine absents des tables de correspondance sont listés à la fin pour les ajouter.
"""

import gzip
import io
import json
import re
import sqlite3
import sys
import tempfile
import urllib.parse
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx  # dépendance de dev : fournit les certificats (certifi), absents du Python python.org

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.genres import (  # noqa: E402
    CONSOLE_SOURCES, DATA_FILE, OVGDB_SYSTEMS, catver_genre, clean_detail, libretro_genre, ovgdb_genre,
)

LIBRETRO = "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/genre/{}.dat"
CATVER = "https://raw.githubusercontent.com/AntoPISA/MAME_SupportFiles/main/catver.ini/catver.ini"
# Titres complets des jeux d'arcade (nom court du zip -> titre), par ordre de priorité.
ARCADE_TITLES = [
    "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/mame/MAME.dat",
    "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/fbneo-split/FBNeo%20-%20Arcade%20Games.dat",
    "https://raw.githubusercontent.com/libretro/libretro-database/master/dat/HBMAME.dat",
]
OPENVGDB = "https://github.com/OpenVGDB/OpenVGDB/releases/download/v29.0/openvgdb.zip"
ZIP_RE = re.compile(r"rom \( name (\S+?)\.zip ")

BLOCK_RE = re.compile(r"^game \((.*?)^\)", re.S | re.M)
TITLE_RE = re.compile(r'^\s*(?:comment|name) "((?:[^"\\]|\\.)*)"', re.M)
GENRE_RE = re.compile(r'^\s*genre "([^"]*)"', re.M)


def dat_entries(text: str):
    """(titre No-Intro, genre) de chaque bloc `game ( ... )` d'un fichier clrmamepro."""
    for block in BLOCK_RE.findall(text):
        title, genre = TITLE_RE.search(block), GENRE_RE.search(block)
        if title and genre:
            yield title.group(1), genre.group(1)


def fetch(url: str) -> str:
    r = httpx.get(url, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.content.decode("utf-8", errors="replace")


def openvgdb(unmapped: Counter) -> dict[str, dict[str, str]]:
    """Genres OpenVGDB par dossier de la carte : {dossier: {nom de fichier sans extension: "clé|genre d'origine"}}."""
    r = httpx.get(OPENVGDB, timeout=120, follow_redirects=True)
    r.raise_for_status()
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            z.extract("openvgdb.sqlite", tmp)
        db = sqlite3.connect(Path(tmp) / "openvgdb.sqlite")
        rows = db.execute("select o.systemID, o.romExtensionlessFileName, r.releaseGenre from ROMs o "
                          "join RELEASES r on r.romID = o.romID where r.releaseGenre is not null and r.releaseGenre != ''").fetchall()
        db.close()
    out: dict[str, dict[str, str]] = {}
    for system, name, raw in rows:
        genre = ovgdb_genre(raw)
        if genre is None:
            unmapped[f"openvgdb: {raw}"] += 1
            continue
        for d in OVGDB_SYSTEMS.get(system, []):
            out.setdefault(d, {}).setdefault(name, f"{genre}|{raw.replace(',', ' / ')}")
    for d in sorted(out):
        print(f"{'OpenVGDB ' + d:<50} {len(out[d]):>6}")
    return out


def main() -> int:
    unmapped: Counter = Counter()
    systems: dict[str, dict[str, str]] = {}
    for name in sorted({s for srcs in CONSOLE_SOURCES.values() for s in srcs}):
        text = fetch(LIBRETRO.format(urllib.parse.quote(name)))
        entries: dict[str, str] = {}
        for title, raw in dat_entries(text):
            genre = libretro_genre(raw)
            if genre is None:
                unmapped[f"libretro: {raw}"] += 1
                continue
            entries[title] = f"{genre}|{raw}"  # casse d'origine : c'est aussi le nom des jaquettes libretro
        systems[name] = entries
        print(f"{name:<50} {len(entries):>6}")

    text = fetch(CATVER)
    header = re.search(r";;\s*(catver\.ini[^;]*);;", text)
    section = text.split("[Category]", 1)[1].split("\n[", 1)[0]
    arcade: dict[str, str] = {}
    for line in section.splitlines():
        if "=" not in line or line.startswith(";"):
            continue
        short, raw = (x.strip() for x in line.split("=", 1))
        genre = catver_genre(raw)
        if genre is None:
            unmapped[f"catver: {raw.split(' / ')[0]}"] += 1
            continue
        arcade[short.lower()] = f"{genre}|{clean_detail(raw)}"
    print(f"{'catver.ini (arcade)':<50} {len(arcade):>6}")

    arcade_titles: dict[str, str] = {}
    for url in ARCADE_TITLES:
        before = len(arcade_titles)
        for block in BLOCK_RE.findall(fetch(url)):
            title, zipname = TITLE_RE.search(block), ZIP_RE.search(block)
            if title and zipname:
                arcade_titles.setdefault(zipname.group(1).lower(), title.group(1))
        print(f"{'titres arcade ' + url.rsplit('/', 1)[1]:<50} {len(arcade_titles) - before:>6}")

    data = {
        "version": {"built_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "catver": header.group(1).strip() if header else None,
                    "libretro": "libretro-database master"},
        "systems": systems,
        "arcade": arcade,
        "arcade_titles": arcade_titles,
        "ovgdb": openvgdb(unmapped),
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(DATA_FILE, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    print(f"\nÉcrit : {DATA_FILE} ({DATA_FILE.stat().st_size / 1e6:.2f} Mo)")
    if unmapped:
        print("\nCatégories ignorées (sans genre) :")
        for k, n in unmapped.most_common():
            print(f"  {n:>6}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
