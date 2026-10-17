"""Construit la table embarquée des informations de jeu (app/data/gameinfo.json.gz).

Usage (depuis backend/) :
    .venv/bin/python scripts/build_gameinfo.py

À lancer seulement pour rafraîchir les sources : l'application lit le fichier produit, sans réseau.
Sources publiques :
- libretro-database (metadat/developer, publisher, releaseyear, releasemonth, franchise) : consoles, par nom
  No-Intro ;
- OpenVGDB (base d'OpenEmu) : résumé (en anglais), date de sortie, développeur, éditeur, fiche GameFAQs ;
- listes arcade libretro (MAME, FBNeo, HBMAME) : année et fabricant, par nom court du zip.
Chaque enregistrement : [année, date « AAAA-MM-JJ » ou « AAAA-MM », développeur, éditeur, franchise,
index du résumé dans « texts », lien de référence]. Les résumés identiques (éditions d'un même jeu) sont partagés.
"""

import gzip
import io
import re
import sqlite3
import sys
import tempfile
import urllib.parse
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx  # dépendance de dev : fournit les certificats (certifi), absents du Python python.org

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.gameinfo import DATA_FILE, FIELDS, dump  # noqa: E402
from app.services.genres import ARCADE_DIRS, CONSOLE_SOURCES, OVGDB_SYSTEMS  # noqa: E402

METADAT = "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/{}/{}.dat"
LIBRETRO_FIELDS = ("developer", "publisher", "releaseyear", "releasemonth", "franchise")
ARCADE = [  # (url, champ année, champ fabricant)
    ("https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/mame/MAME.dat", "year", "developer"),
    ("https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/fbneo-split/FBNeo%20-%20Arcade%20Games.dat",
     "releaseyear", "publisher"),
    ("https://raw.githubusercontent.com/libretro/libretro-database/master/dat/HBMAME.dat", "year", "developer"),
]
OPENVGDB = "https://github.com/OpenVGDB/OpenVGDB/releases/download/v29.0/openvgdb.zip"

BLOCK_RE = re.compile(r"^game \((.*?)^\)", re.S | re.M)
TITLE_RE = re.compile(r'^\s*(?:comment|name) "((?:[^"\\]|\\.)*)"', re.M)
ZIP_RE = re.compile(r"rom \( name (\S+?)\.zip ")
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def field(block: str, name: str) -> str | None:
    m = re.search(rf'^\s*{name} "((?:[^"\\]|\\.)*)"', block, re.M)
    value = m.group(1).strip() if m else ""
    return value or None


def fetch(url: str) -> str:
    r = httpx.get(url, timeout=60, follow_redirects=True)
    if r.status_code == 404:
        return ""
    r.raise_for_status()
    return r.content.decode("utf-8", errors="replace")


def year_of(value: str | None) -> int | None:
    m = re.search(r"(19[5-9]\d|20[0-4]\d)", value or "")
    return int(m.group(1)) if m else None


def ovgdb_date(raw: str | None) -> tuple[int | None, str | None]:
    """« Jan 10, 2005 » -> (2005, « 2005-01-10 ») ; « 1994 » -> (1994, None)."""
    if not raw:
        return None, None
    m = re.match(r"([A-Za-z]{3})[a-z]* (\d{1,2}), (\d{4})", raw.strip())
    if m and m.group(1).lower() in MONTHS:
        return int(m.group(3)), f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    return year_of(raw), None


class Builder:
    def __init__(self):
        self.texts: list[str] = []
        self.text_ids: dict[str, int] = {}
        self.consoles: dict[str, dict[str, list]] = {}
        self.arcade: dict[str, list] = {}

    def text(self, value: str | None) -> int | None:
        value = (value or "").strip()
        if len(value) < 20:
            return None
        if value not in self.text_ids:
            self.text_ids[value] = len(self.texts)
            self.texts.append(value)
        return self.text_ids[value]

    @staticmethod
    def merge(table: dict[str, list], name: str, values: list) -> None:
        """Complète l'enregistrement `name` : une valeur déjà connue n'est pas remplacée."""
        row = table.setdefault(name, [None] * len(FIELDS))
        for i, v in enumerate(values):
            if v in (None, ""):
                continue
            # Date : la plus précise gagne (« 2005-01-10 » plutôt que « 2005-01 »), si elle est de la même année.
            if row[i] is None or (FIELDS[i] == "date" and isinstance(row[i], str) and isinstance(v, str)
                                  and len(v) > len(row[i]) and v.startswith(row[i][:4])):
                row[i] = v

    def libretro(self) -> None:
        for d, sources in CONSOLE_SOURCES.items():
            table = self.consoles.setdefault(d, {})
            for src in sources:
                found = 0
                for kind in LIBRETRO_FIELDS:
                    for block in BLOCK_RE.findall(fetch(METADAT.format(kind, urllib.parse.quote(src)))):
                        title, value = TITLE_RE.search(block), field(block, kind)
                        if not (title and value):
                            continue
                        found += 1
                        row = [None] * len(FIELDS)
                        if kind == "releaseyear":
                            row[0] = year_of(value)
                        elif kind == "releasemonth":
                            row[1] = value  # mois seul : complété avec l'année plus bas
                        else:
                            row[FIELDS.index(kind)] = value
                        self.merge(table, title.group(1), row)
                print(f"libretro {d:<10} {src:<50} {found:>6}")
            for row in table.values():  # « 6 » + 2005 -> « 2005-06 »
                if row[1] and row[1].isdigit() and row[0]:
                    row[1] = f"{row[0]}-{int(row[1]):02d}"
                elif row[1] and not re.match(r"\d{4}-", row[1]):
                    row[1] = None

    def openvgdb(self) -> None:
        r = httpx.get(OPENVGDB, timeout=120, follow_redirects=True)
        r.raise_for_status()
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                z.extract("openvgdb.sqlite", tmp)
            db = sqlite3.connect(Path(tmp) / "openvgdb.sqlite")
            rows = db.execute("select o.systemID, o.romExtensionlessFileName, r.releaseDate, r.releaseDeveloper, "
                              "r.releasePublisher, r.releaseDescription, r.releaseReferenceURL from ROMs o "
                              "join RELEASES r on r.romID = o.romID").fetchall()
            db.close()
        count = 0
        for system, name, date, dev, pub, desc, url in rows:
            dirs = OVGDB_SYSTEMS.get(system)
            if not dirs or not name:
                continue
            year, full_date = ovgdb_date(date)
            values = [year, full_date, dev, pub, None, self.text(desc), url]
            for d in dirs:
                self.merge(self.consoles.setdefault(d, {}), name, values)
            count += 1
        print(f"OpenVGDB : {count} éditions")

    def arcade_lists(self) -> None:
        for url, year_field, maker_field in ARCADE:
            before = len(self.arcade)
            for block in BLOCK_RE.findall(fetch(url)):
                z = ZIP_RE.search(block)
                if not z:
                    continue
                maker = field(block, maker_field) or field(block, "manufacturer")
                self.merge(self.arcade, z.group(1).lower(),
                           # Arcade : le fabricant est à la fois développeur et éditeur.
                           [year_of(field(block, year_field)), None, maker, maker, None, None, None])
            print(f"arcade {url.rsplit('/', 1)[1]:<40} {len(self.arcade) - before:>6} nouveaux")


def main() -> int:
    b = Builder()
    b.libretro()
    b.openvgdb()
    b.arcade_lists()
    data = {
        "version": {"built_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "sources": "libretro-database master, OpenVGDB v29.0", "arcade_dirs": sorted(ARCADE_DIRS)},
        "fields": list(FIELDS),
        "consoles": b.consoles,
        "arcade": b.arcade,
        "texts": b.texts,
    }
    dump(data, DATA_FILE)
    total = sum(len(t) for t in b.consoles.values())
    print(f"\n{total} éditions console, {len(b.arcade)} jeux d'arcade, {len(b.texts)} résumés")
    print(f"Écrit : {DATA_FILE} ({DATA_FILE.stat().st_size / 1e6:.2f} Mo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
