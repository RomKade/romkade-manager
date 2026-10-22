"""Informations de jeu, sans réseau : année, date de sortie, développeur, éditeur, franchise, résumé, référence.

La table `app/data/gameinfo.json.gz` est construite par `scripts/build_gameinfo.py` (libretro-database,
OpenVGDB, listes arcade MAME / FBNeo / HBMAME). Rapprochement par nom de fichier, comme les genres (genres.py) :
nom No-Intro exact, puis titre sans étiquettes (région, version), puis titre compact ; l'arcade par nom court du
zip. Le résumé vient d'OpenVGDB, en anglais.
"""

import gzip
import json
import re
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Platform, RemoteFile
from app.platforms import canonical
from app.services.classify import stem_of
from app.services.genres import ARCADE_DIRS, compact_title, loose_title

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "gameinfo.json.gz"
FIELDS = ("year", "date", "developer", "publisher", "franchise", "text", "url", "players")
COLUMNS = ("release_year", "release_date", "developer", "publisher", "franchise", "description", "info_url", "players")
# Consoles portables : leur « 2 joueurs » demande deux consoles reliées (câble link), pas deux manettes.
LINK_DIRS = {"GB", "GBC", "GBA", "GG", "WS", "NGP", "LYNX", "VB", "NDS", "PSP", "POKEMINI", "GW"}


def dump(data: dict, path: Path = DATA_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _richness(name: str, row: list) -> tuple:
    """Pour choisir une édition parmi d'autres du même titre : la plus renseignée, puis USA, Europe, Monde."""
    tags = name.lower()
    region = 0 if "(usa" in tags else 1 if "europe" in tags else 2 if "world" in tags else 3
    demo = any(w in tags for w in ("(demo", "(beta", "(proto", "(kiosk", "(sample"))
    return (-sum(v is not None for v in row), demo, region, name)


def _fill(table: dict[str, list], key: str, row: list) -> None:
    """Édition la plus renseignée d'abord ; ses champs vides sont complétés par les autres éditions du même titre
    (le nombre de joueurs n'est souvent connu que pour l'une d'elles)."""
    have = table.get(key)
    if have is None:
        table[key] = list(row)
        return
    if len(have) < len(row):
        have.extend([None] * (len(row) - len(have)))
    for i, v in enumerate(row):
        if have[i] is None and v is not None:
            have[i] = v


class InfoIndex:
    def __init__(self, data: dict):
        self.version: dict = data.get("version", {})
        self.texts: list[str] = data.get("texts", [])
        self.arcade: dict[str, list] = data.get("arcade", {})
        consoles: dict[str, dict[str, list]] = data.get("consoles", {})
        self.exact = {d: {k.lower(): v for k, v in t.items()} for d, t in consoles.items()}
        self.loose: dict[str, dict[str, list]] = {}
        self.compact: dict[str, dict[str, list]] = {}
        for d, table in consoles.items():
            for name in sorted(table, key=lambda n: _richness(n, table[n])):
                row = table[name]
                if t := loose_title(name):
                    _fill(self.loose.setdefault(d, {}), t, row)
                if c := compact_title(name):
                    _fill(self.compact.setdefault(d, {}), c, row)

    def lookup(self, platform_dir: str, filename: str) -> dict | None:
        """Champs de COLUMNS pour ce fichier, ou None sans correspondance."""
        stem = stem_of(filename)
        d = canonical(platform_dir)
        if d in ARCADE_DIRS:
            row = self.arcade.get(stem.lower())
        else:
            exact = self.exact.get(d, {}).get(stem.lower())
            loose = self.loose.get(d, {}).get(loose_title(stem))
            row = exact or loose or self._compact(d, stem)
            if exact and loose and None in exact:  # nom exact sans un champ (joueurs…) : complété par le titre
                row = [v if v is not None else (loose[i] if i < len(loose) else None) for i, v in enumerate(exact)]
                row += loose[len(exact):]
        if not row:
            return None
        values = dict(zip(COLUMNS, row))
        text = values["description"]
        values["description"] = self.texts[text] if isinstance(text, int) and 0 <= text < len(self.texts) else None
        return values

    def _compact(self, d: str, stem: str) -> list | None:
        short = compact_title(re.sub(r"^[A-Z]{2,3}-", "", stem))  # « SS-Clockwork Knight »
        return self.compact.get(d, {}).get(short) if len(short) >= 4 else None


@lru_cache(maxsize=1)
def load_index(path: Path = DATA_FILE) -> InfoIndex:
    if not path.exists():
        return InfoIndex({})
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return InfoIndex(json.load(fh))


def apply_info(s: Session, platform_ids: set[int] | None = None, index: InfoIndex | None = None) -> int:
    """Recalcule les informations des fichiers candidats, tous ou ceux de quelques plateformes.
    Renvoie le nombre de fichiers renseignés."""
    index = index or load_index()
    cols = [getattr(RemoteFile, c) for c in COLUMNS]
    q = select(RemoteFile.id, RemoteFile.filename, Platform.directory, *cols).join(Platform) \
        .where(RemoteFile.role == "candidate")
    if platform_ids is not None:
        q = q.where(RemoteFile.platform_id.in_(platform_ids))
    changes: list[dict] = []
    found = 0
    for fid, filename, directory, *current in s.execute(q):
        values = index.lookup(directory, filename) or {}
        found += bool(values)
        new = [values.get(c) for c in COLUMNS]
        if new != list(current):
            changes.append({"id": fid, **dict(zip(COLUMNS, new))})
    if changes:
        s.execute(update(RemoteFile), changes)
    return found


def apply_all(sessions: sessionmaker[Session]) -> int:
    with sessions.begin() as s:
        return apply_info(s)
