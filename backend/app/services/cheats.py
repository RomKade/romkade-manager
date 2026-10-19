"""Codes de triche de RetroArch (libretro-database, dossier `cht`, licence CC BY-SA 4.0), sans IA.

Le paquet officiel de RetroArch (CHEATS_URL, celui du « Online Updater », environ 37 Mo) est téléchargé à la demande
dans le dossier de données (Paramètres > Connaissances) et lu sur place : un fichier `.cht` par jeu, rangé par
système (« Nintendo - Super Nintendo Entertainment System/Batman Returns (USA).cht »), souvent en plusieurs
variantes (Game Genie, Action Replay…). Rapprochement par nom, comme les informations des jeux (gameinfo.py) : nom
No-Intro exact, puis titre sans étiquettes. Les fichiers « (Rumbles) » (vibrations, pas des codes) sont ignorés.

Un code dépend de la version du jeu : un code d'une édition USA ne marche pas forcément sur une édition européenne.
Les fichiers de la même région que le jeu passent donc en premier.

Copie sur la console : le fichier choisi est écrit dans le dossier des codes de RetroArch (`cheat_database_path` de
retroarch.cfg), sous le nom du jeu ; on le charge ensuite en jeu (Menu rapide > Codes de triche).
"""

import asyncio
import base64
import re
import shlex
import zipfile
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import httpx

from app.config import data_dir
from app.errors import AppError
from app.platforms import canonical
from app.services.classify import stem_of
from app.services.genres import ARCADE_DIRS, CONSOLE_SOURCES, loose_title

CHEATS_URL = "https://buildbot.libretro.com/assets/frontend/cheats.zip"
SOURCE_URL = "https://github.com/libretro/libretro-database/tree/master/cht"
LICENSE = "CC BY-SA 4.0"
FILE = "cheats.zip"
ARCADE_SYSTEM = "FBNeo - Arcade Games"
EXTRA_SYSTEMS = {"PCECD": ["NEC - PC Engine CD - TurboGrafx-CD"], "PS": ["Sony - PlayStation"],
                 "MDCD": ["Sega - Mega-CD - Sega CD"], "SATURN": ["Sega - Saturn"], "DC": ["Sega - Dreamcast"],
                 "COLECO": ["Coleco - ColecoVision"], "INTV": ["Mattel - Intellivision"]}
MAX_CHEATS = 300  # par fichier, à l'affichage
MAX_FILE_BYTES = 512 * 1024
DEVICES = ("game genie", "action replay", "pro action replay", "gameshark", "game shark", "code breaker",
           "codebreaker", "xploder", "gold finger", "goldfinger", "cheatcode", "raw")

_lock = asyncio.Lock()


def path() -> Path:
    return data_dir() / FILE


def systems_for(platform_dir: str) -> list[str]:
    d = canonical(platform_dir)
    if d in ARCADE_DIRS:
        return [ARCADE_SYSTEM]
    return CONSOLE_SOURCES.get(d, []) + EXTRA_SYSTEMS.get(d, [])


def _tags(name: str) -> list[str]:
    return [t.strip().lower() for t in re.findall(r"\(([^)]*)\)", name)]


def label_of(name: str) -> str:
    """« Batman Returns (World) (Game Genie) » -> « World · Game Genie » ; sans étiquette : le titre."""
    tags = re.findall(r"\(([^)]*)\)", Path(name).stem)
    return " · ".join(tags) if tags else Path(name).stem


class CheatIndex:
    def __init__(self, names: list[str]):
        self.exact: dict[str, dict[str, str]] = {}
        self.loose: dict[str, dict[str, list[str]]] = {}
        for n in names:
            if not n.endswith(".cht") or "/" not in n:
                continue
            system, base = n.split("/", 1)
            stem = base[:-4]
            if "rumble" in stem.lower():
                continue
            self.exact.setdefault(system, {})[stem.lower()] = n
            if t := loose_title(stem):
                self.loose.setdefault(system, {}).setdefault(t, []).append(n)
        self.count = sum(len(v) for v in self.exact.values())

    def files_for(self, platform_dir: str, filename: str) -> list[str]:
        """Fichiers de codes de ce jeu, les plus sûrs d'abord : même nom, même région, puis les autres."""
        stem = stem_of(filename)
        found: list[str] = []
        for system in systems_for(platform_dir):
            if system == ARCADE_SYSTEM:
                if n := self.exact.get(system, {}).get(stem.lower()):
                    found.append(n)
                continue
            if n := self.exact.get(system, {}).get(stem.lower()):
                found.append(n)
            found += [n for n in self.loose.get(system, {}).get(loose_title(stem), []) if n not in found]
        mine = {p.strip() for t in _tags(stem) if t not in DEVICES for p in t.split(",")}

        def rank(n: str) -> tuple:
            base = Path(n).stem
            tags = _tags(base)
            same = base.lower() == stem.lower()
            region = -len(mine & {p.strip() for t in tags for p in t.split(",")})
            proto = any(w in " ".join(tags) or w in base for w in ("proto", "beta", "demo", "[b]"))
            japan = any("japan" in t for t in tags) and not any(r in " ".join(tags) for r in ("usa", "europe", "world"))
            return (not same, region, proto, japan, any(t in DEVICES for t in tags), base)

        return sorted(found, key=rank)


@lru_cache(maxsize=2)
def _load(p: str, mtime: float) -> CheatIndex | None:
    try:
        with zipfile.ZipFile(p) as z:
            return CheatIndex(z.namelist())
    except (OSError, zipfile.BadZipFile):
        return None


def index() -> CheatIndex | None:
    p = path()
    if not p.exists():
        return None
    return _load(str(p), p.stat().st_mtime)


def status() -> dict:
    p = path()
    idx = index()
    return {"available": idx is not None, "files": idx.count if idx else 0,
            "updated_at": datetime.fromtimestamp(p.stat().st_mtime, UTC) if idx else None,
            "size": p.stat().st_size if idx else 0, "license": LICENSE, "source_url": SOURCE_URL}


async def download(url: str = CHEATS_URL, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Télécharge (ou met à jour) le paquet de RetroArch, vérifie qu'il se lit, puis remplace l'ancien."""
    if _lock.locked():
        raise AppError("cheats_downloading", "Le téléchargement des codes de triche est déjà en cours.", 409)
    async with _lock:
        tmp = path().with_suffix(".part")
        try:
            async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(30, read=60),
                                         follow_redirects=True) as http:
                async with http.stream("GET", url) as r:
                    r.raise_for_status()
                    with tmp.open("wb") as fh:
                        async for chunk in r.aiter_bytes(1 << 16):
                            fh.write(chunk)
            if await asyncio.to_thread(lambda: _load(str(tmp), tmp.stat().st_mtime)) is None:
                raise AppError("cheats_unreadable", "Le paquet des codes de triche reçu est illisible.", 502)
            tmp.replace(path())
        except httpx.HTTPError as exc:
            raise AppError("cheats_download_failed",
                           f"Les codes de triche n'ont pas pu être téléchargés : {type(exc).__name__}.", 502) from exc
        finally:
            tmp.unlink(missing_ok=True)
    return status()


LINE_RE = re.compile(r'^\s*cheat(\d+)_(desc|code|address|value|handler)\s*=\s*"?(.*?)"?\s*$')


def parse(text: str) -> list[dict]:
    """Codes d'un fichier `.cht` : [{desc, code}], dans l'ordre. Un code d'émulateur (Game Genie…) tel quel ; une
    écriture en mémoire (handler 1, fichiers d'arcade FBNeo) en « adresse=valeur »."""
    items: dict[int, dict] = {}
    for line in text.splitlines():
        if m := LINE_RE.match(line):
            items.setdefault(int(m.group(1)), {})[m.group(2)] = m.group(3).strip()
    out = []
    for i, v in sorted(items.items()):
        code = v.get("code") or (f"{v['address']}={v['value']}" if v.get("handler") == "1" and v.get("address")
                                 and v.get("value") is not None else "")
        if code:
            out.append({"desc": v.get("desc") or f"#{i + 1}", "code": code})
    return out


def read(name: str) -> str:
    """Texte d'un fichier du paquet (nom exact, tel que listé par files_for)."""
    with zipfile.ZipFile(path()) as z:
        info = z.getinfo(name)
        if info.file_size > MAX_FILE_BYTES:
            raise AppError("cheats_too_big", "Ce fichier de codes est trop gros.", 422)
        return z.read(info).decode("utf-8", "replace")


def for_game(platform_dir: str, filename: str) -> list[dict]:
    """[{name, label, system, cheats}] pour ce jeu (vide si le paquet manque ou si rien ne correspond)."""
    idx = index()
    if idx is None:
        return []
    out = []
    for name in idx.files_for(platform_dir, filename):
        cheats = parse(read(name))
        if cheats:
            out.append({"name": name, "label": label_of(name), "system": name.split("/", 1)[0],
                        "count": len(cheats), "cheats": cheats[:MAX_CHEATS]})
    return out


def install_command(ra_config: str, system: str, rom_stem: str, data: bytes) -> str:
    """Commande shell : écrit le fichier de codes dans le dossier des codes de RetroArch (cheat_database_path ;
    « : » = dossier de retroarch.cfg ; « ~ » = dossier personnel ; par défaut <dossier de la config>/cheats)."""
    name = re.sub(r"[/\x00]", "_", rom_stem)[:200] + ".cht"
    sub = re.sub(r"[/\x00]", "_", system)
    b64 = base64.b64encode(data).decode()
    return (
        f"CFG={shlex.quote(ra_config)}; BASE=$(dirname \"$CFG\"); "
        "P=$(sed -n 's/^[[:space:]]*cheat_database_path[[:space:]]*=[[:space:]]*\"\\(.*\\)\"/\\1/p' \"$CFG\" 2>/dev/null | head -1); "
        "case \"$P\" in ''|default) P=\"$BASE/cheats\";; ':'*) P=\"$BASE${P#:}\";; '~'*) P=\"$HOME${P#\\~}\";; esac; "
        f"D=\"$P\"/{shlex.quote(sub)}; mkdir -p \"$D\" && "
        f"echo {b64} | base64 -d > \"$D\"/{shlex.quote(name)} && echo \"OK:$D/\"{shlex.quote(name)}"
    )
