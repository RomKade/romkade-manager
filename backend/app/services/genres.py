"""Genres des jeux, sans réseau : rapprochement par nom de fichier avec une table embarquée.

La table `app/data/genres.json.gz` est construite par `scripts/build_genres.py` à partir de deux
sources publiques :
- libretro-database (`metadat/genre`) pour les consoles, indexée par nom No-Intro complet ;
- catver.ini (progettoSNAPS) pour l'arcade, indexé par nom court MAME (`sf2.zip` -> `sf2`) ;
- OpenVGDB (base d'OpenEmu) en seconde source, notamment pour les consoles à CD (PlayStation, Saturn…).
Les noms de fichiers approximatifs sont rapprochés par titre compact, début de titre, puis autre console.

Chaque fichier reçoit un genre unifié (`genre`, clé stable de GENRES) et la catégorie d'origine
(`genre_detail`). Un fichier sans correspondance garde `genre = NULL` (« Non classé »).
Les jeux d'arcade reçoivent aussi leur titre complet (`full_title`), tiré des listes MAME, FBNeo et HBMAME.
"""

import bisect
import gzip
import json
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Platform, RemoteFile
from app.services import subgenres
from app.services.classify import normalize_title, search_key, stem_of
from app.platforms import canonical

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "genres.json.gz"

# Ordre d'affichage du filtre.
GENRES: dict[str, str] = {
    "action": "Action",
    "aventure": "Aventure",
    "beat": "Beat'em up",
    "combat": "Combat",
    "course": "Course",
    "plateforme": "Plateforme",
    "rpg": "Jeu de rôle",
    "shmup": "Shoot'em up",
    "tir": "Tir",
    "sport": "Sport",
    "reflexion": "Réflexion",
    "labyrinthe": "Labyrinthe",
    "strategie": "Stratégie",
    "simulation": "Simulation",
    "flipper": "Flipper",
    "societe": "Société et casino",
    "quiz": "Quiz",
    "musique": "Musique et rythme",
    "educatif": "Éducatif",
    "compilation": "Compilation",
    "autre": "Autre",
}
UNCLASSIFIED = "none"  # valeur du filtre pour les jeux sans genre

# Dossier de la carte -> fichiers libretro-database à consulter (dans l'ordre).
CONSOLE_SOURCES: dict[str, list[str]] = {
    "A2600": ["Atari - 2600"],
    "A5200": ["Atari - 5200"],
    "A7800": ["Atari - 7800"],
    "LYNX": ["Atari - Lynx"],
    "WS": ["Bandai - WonderSwan", "Bandai - WonderSwan Color"],
    "MSX": ["Microsoft - MSX", "Microsoft - MSX2", "Microsoft - MSX 2"],
    "PCE": ["NEC - PC Engine - TurboGrafx 16", "NEC - PC Engine SuperGrafx"],
    "FC": ["Nintendo - Nintendo Entertainment System", "Nintendo - Family Computer Disk System"],
    "FDS": ["Nintendo - Family Computer Disk System"],
    "SFC": ["Nintendo - Super Nintendo Entertainment System", "Nintendo - Satellaview", "Nintendo - Sufami Turbo"],
    "GB": ["Nintendo - Game Boy", "Nintendo - Game Boy Color"],
    "GBC": ["Nintendo - Game Boy Color", "Nintendo - Game Boy"],
    "GBA": ["Nintendo - Game Boy Advance"],
    "N64": ["Nintendo - Nintendo 64"],
    "NDS": ["Nintendo - Nintendo DS"],
    "VB": ["Nintendo - Virtual Boy"],
    "NGP": ["SNK - Neo Geo Pocket", "SNK - Neo Geo Pocket Color"],
    "SEGA32X": ["Sega - 32X"],
    "GG": ["Sega - Game Gear"],
    "SMS": ["Sega - Master System - Mark III", "Sega - SG-1000"],
    "MD": ["Sega - Mega Drive - Genesis"],
    "PSP": ["Sony - PlayStation Portable"],
}
# Dossiers dont les jeux portent un nom court MAME (catver.ini).
ARCADE_DIRS = {"MAME", "FBNEO", "CPS1", "CPS2", "CPS3", "HBMAME", "NAOMI", "ATOMISWAVE", "NEOGEO", "PGM2", "VARCADE"}

# OpenVGDB (base d'OpenEmu) : identifiant de système -> dossiers de la carte. Seconde source de genres,
# indispensable pour les consoles à CD (PlayStation, Saturn, Mega-CD, PC Engine CD) absentes de libretro.
OVGDB_SYSTEMS: dict[int, list[str]] = {
    38: ["PS"], 34: ["SATURN"], 32: ["MDCD"], 15: ["PCECD"], 23: ["N64"], 24: ["NDS"], 39: ["PSP"],
    19: ["GB", "GBC"], 21: ["GBC", "GB"], 20: ["GBA"], 25: ["FC"], 18: ["FDS", "FC"], 26: ["SFC"],
    33: ["MD"], 31: ["SMS"], 30: ["GG"], 29: ["SEGA32X"], 14: ["PCE"], 3: ["A2600"], 4: ["A5200"], 5: ["A7800"],
    6: ["LYNX"], 9: ["WS"], 10: ["WS"], 36: ["NGP"], 37: ["NGP"], 27: ["VB"], 42: ["MSX"], 43: ["MSX"],
}

# Genres OpenVGDB (« Action,Fighting,3D ») -> genre unifié : le premier motif présent gagne.
OVGDB_RULES: list[tuple[str, str]] = [
    ("fighting", "combat"), ("beat-'em-up", "beat"), ("shoot-'em-up", "shmup"), ("shooter,scrolling", "shmup"),
    ("light gun", "tir"), ("shooter", "tir"), ("platformer", "plateforme"), ("racing", "course"),
    ("driving", "course"), ("sports", "sport"), ("role-playing", "rpg"), ("puzzle", "reflexion"),
    ("pinball", "flipper"), ("trivia", "quiz"), ("rhythm", "musique"), ("music", "musique"),
    ("board game", "societe"), ("maze", "labyrinthe"), ("card", "societe"), ("gambling", "societe"), ("parlor", "societe"),
    ("compilation", "compilation"), ("educational", "educatif"), ("strategy", "strategie"),
    ("simulation", "simulation"), ("adventure", "aventure"), ("action", "action"), ("arcade", "action"),
    ("party", "autre"), ("minigame", "autre"), ("miscellaneous", "autre"),
]

# Genres libretro -> genre unifié.
LIBRETRO_MAP: dict[str, str] = {
    "action": "action", "adventure": "aventure", "platform": "plateforme",
    "role-playing (rpg)": "rpg", "role playing game": "rpg", "rpg": "rpg",
    "racing": "course", "driving": "course",
    "strategy": "strategie", "shoot'em up": "shmup", "shooter": "tir", "lightgun shooter": "tir",
    "beat'em up": "beat", "fighting": "combat", "puzzle": "reflexion", "simulation": "simulation",
    "flight simulator": "simulation", "educational": "educatif", "board": "societe", "board game": "societe",
    "gambling": "societe", "casino": "societe", "card game": "societe", "pinball": "flipper",
    "compilation": "compilation", "quiz": "quiz", "trivia": "quiz", "music / dancing": "musique",
    "music": "musique", "sports": "sport", "hunting and fishing": "sport", "fishing": "sport",
    "various": "autre", "casual game": "autre", "party": "autre", "mini-games": "autre",
    "maze": "labyrinthe", "visual novel": "aventure", "card": "societe", "sports with animals": "sport",
    "thinking": "reflexion", "miscellaneous": "autre",
}

# Catégories catver.ini (« Principal / Sous-catégorie ») -> genre unifié. Le premier préfixe qui correspond gagne.
CATVER_RULES: list[tuple[str, str | None]] = [
    ("platform / shooter", "tir"),
    ("platform / fighter", "beat"),
    ("platform", "plateforme"),
    ("climbing", "plateforme"),
    ("shooter / flying", "shmup"),
    ("shooter", "tir"),
    ("fighter", "combat"),
    ("sports", "sport"),
    ("driving", "course"),
    ("maze", "labyrinthe"),
    ("puzzle", "reflexion"),
    ("ball & paddle", "action"),
    ("pinball", "flipper"),
    ("arcade / pinball", "flipper"),
    ("quiz", "quiz"),
    ("music", "musique"),
    ("rhythm", "musique"),
    ("tabletop", "societe"),
    ("board game / chess machine", None),
    ("board game", "societe"),
    ("card games", "societe"),
    ("casino", "societe"),
    ("multigame", "compilation"),
    ("multiplay", "autre"),
    ("role playing", "rpg"),
    ("rpg", "rpg"),
    ("simulation", "simulation"),
    ("strategy", "strategie"),
    ("adventure", "aventure"),
    ("action", "action"),
    ("breakout", "action"),
    ("misc.", "autre"),
]


def libretro_genre(raw: str) -> str | None:
    return LIBRETRO_MAP.get(raw.strip().lower())


def ovgdb_genre(raw: str) -> str | None:
    low = raw.lower()
    for pattern, genre in OVGDB_RULES:
        if pattern in low:
            return genre
    return None


def catver_genre(raw: str) -> str | None:
    """Les machines à sous, électromécaniques, ordinateurs, appareils… ne reçoivent pas de genre."""
    c = raw.replace("* Mature *", "").strip().lower()
    for prefix, genre in CATVER_RULES:
        if c.startswith(prefix):
            return genre
    return None


def clean_detail(raw: str) -> str:
    return re.sub(r"\s*\*\s*Mature\s*\*", "", raw).strip()


class GenreIndex:
    def __init__(self, data: dict):
        self.version: dict = data.get("version", {})
        # entrée : "clé|catégorie d'origine", indexée par nom No-Intro en minuscules
        raw: dict[str, dict[str, str]] = data.get("systems", {})
        self.systems = {src: {k.lower(): v for k, v in entries.items()} for src, entries in raw.items()}
        # nom No-Intro exact (casse d'origine) : sert aussi à retrouver la jaquette libretro
        self.names = {src: {k.lower(): k for k in entries} for src, entries in raw.items()}
        self.names_by_title = {src: _names_by_title(entries) for src, entries in raw.items()}
        self.arcade: dict[str, str] = data.get("arcade", {})
        self.arcade_titles: dict[str, str] = data.get("arcade_titles", {})
        self.by_title: dict[str, dict[str, str]] = {name: _by_title(entries) for name, entries in self.systems.items()}
        # OpenVGDB, par dossier de la carte : nom exact, titre souple, titre compact (sans espaces).
        ovgdb: dict[str, dict[str, str]] = data.get("ovgdb", {})
        self.ovgdb = {d: {k.lower(): v for k, v in entries.items()} for d, entries in ovgdb.items()}
        self.ovgdb_by_title = {d: _by_title(entries) for d, entries in ovgdb.items()}
        # Titre compact -> genre, par dossier (libretro + OpenVGDB) et toutes consoles confondues.
        self.compact: dict[str, dict[str, str]] = {}
        everywhere: dict[str, Counter] = defaultdict(Counter)
        for d, sources in CONSOLE_SOURCES.items():
            for src in sources:
                for name, entry in raw.get(src, {}).items():
                    self._add_compact(d, name, entry, everywhere)
        for d, entries in ovgdb.items():
            for name, entry in entries.items():
                self._add_compact(d, name, entry, everywhere)
        for short, title in self.arcade_titles.items():  # portages d'arcade (Dreamcast, Saturn…)
            if short in self.arcade:
                everywhere[compact_title(title)][self.arcade[short]] += 1
        self.everywhere = {k: c.most_common(1)[0][0] for k, c in everywhere.items() if k}
        self.compact_sorted = {d: sorted(m) for d, m in self.compact.items()}

    def _add_compact(self, d: str, name: str, entry: str, everywhere: dict) -> None:
        key = compact_title(name)
        if key:
            self.compact.setdefault(d, {}).setdefault(key, entry)
            everywhere[key][entry] += 1

    def lookup(self, platform_dir: str, filename: str) -> tuple[str, str] | None:
        stem = stem_of(filename)
        d = canonical(platform_dir)
        if d in ARCADE_DIRS:
            hit = self.arcade.get(stem.lower())
            return _split(hit) if hit else None
        sources = CONSOLE_SOURCES.get(d, [])
        key = stem.lower()
        for src in sources:
            hit = self.systems.get(src, {}).get(key)
            if hit:
                return _split(hit)
        if hit := self.ovgdb.get(d, {}).get(key):
            return _split(hit)
        # Repli : même titre sans les étiquettes (région, version), autre édition du même jeu.
        title = loose_title(stem)
        if title:
            for src in sources:
                hit = self.by_title.get(src, {}).get(title)
                if hit:
                    return _split(hit)
            if hit := self.ovgdb_by_title.get(d, {}).get(title):
                return _split(hit)
        # Noms approximatifs des fichiers (« Bomberman2 », « SS-Clockwork Knight », titre tronqué).
        short = compact_title(re.sub(r"^[A-Z]{2,3}-", "", stem))
        if len(short) >= 4:
            if hit := self.compact.get(d, {}).get(short):
                return _split(hit)
            if len(short) >= 10 and (hit := self._prefix(d, short)):
                return _split(hit)
            if hit := self.everywhere.get(short):  # le même jeu sur une autre console
                return _split(hit)
        return None

    def ovgdb_raw(self, platform_dir: str, filename: str) -> str | None:
        """Catégorie OpenVGDB d'origine (« Sports,Traditional,Golf,Sim »), souvent plus fine que celle de libretro :
        sert aux sous-genres (subgenres.py)."""
        d = canonical(platform_dir)
        stem = stem_of(filename)
        hit = self.ovgdb.get(d, {}).get(stem.lower()) or self.ovgdb_by_title.get(d, {}).get(loose_title(stem))
        return _split(hit)[1] if hit else None

    def _prefix(self, d: str, short: str) -> str | None:
        """Titre tronqué : le titre connu le plus court qui commence par `short`."""
        keys = self.compact_sorted.get(d, [])
        i = bisect.bisect_left(keys, short)
        best = None
        while i < len(keys) and keys[i].startswith(short):
            if best is None or len(keys[i]) < len(best):
                best = keys[i]
            i += 1
        return self.compact[d][best] if best else None

    def full_title(self, platform_dir: str, filename: str) -> str | None:
        """Titre complet d'un jeu d'arcade (« sf2.zip » -> « Street Fighter II: The World Warrior (World 910522) »)."""
        if canonical(platform_dir) not in ARCADE_DIRS:
            return None
        return self.arcade_titles.get(stem_of(filename).lower())


def compact_title(name: str) -> str:
    """Titre souple sans espaces : « Bomberman2 » = « Bomberman 2 », « R4: Ridge Racer » = « R4 Ridge Racer »."""
    return loose_title(name).replace(" ", "")


def loose_title(name: str) -> str:
    """Titre sans étiquettes ni article « the » (« Ren & Stimpy Show, The - X » = « The Ren & Stimpy Show - X »)."""
    return " ".join(w for w in normalize_title(name).split() if w not in ("the", "and"))


def _names_by_title(entries: dict[str, str]) -> dict[str, str]:
    """Titre souple -> un nom No-Intro de ce titre, en préférant les éditions USA puis Europe puis Monde."""
    def rank(name: str) -> int:
        tags = name.lower()
        return 0 if "(usa" in tags else 1 if "europe" in tags else 2 if "world" in tags else 3
    out: dict[str, str] = {}
    for name in sorted(entries, key=lambda n: (rank(n), n)):
        out.setdefault(loose_title(name), name)
    return out


def _split(entry: str) -> tuple[str, str]:
    genre, _, detail = entry.partition("|")
    return genre, detail


def _by_title(entries: dict[str, str]) -> dict[str, str]:
    """Titre normalisé -> genre le plus fréquent parmi ses éditions."""
    votes: dict[str, Counter] = defaultdict(Counter)
    for name, entry in entries.items():
        t = loose_title(name)
        if t:
            votes[t][entry] += 1
    return {t: c.most_common(1)[0][0] for t, c in votes.items()}


@lru_cache(maxsize=1)
def load_index(path: Path = DATA_FILE) -> GenreIndex:
    if not path.exists():
        return GenreIndex({})
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return GenreIndex(json.load(fh))


def apply_genres(s: Session, platform_ids: set[int] | None = None, index: GenreIndex | None = None) -> int:
    """Recalcule genre et titre complet (arcade) des fichiers candidats, tous ou ceux de quelques plateformes.

    Pour l'arcade, le titre complet sert aussi à la recherche et au tri (`search_key`, `normalized_title`).
    Renvoie le nombre de fichiers classés.
    """
    index = index or load_index()
    q = select(RemoteFile.id, RemoteFile.filename, RemoteFile.genre, RemoteFile.genre_detail, RemoteFile.full_title,
               RemoteFile.normalized_title, RemoteFile.search_key, RemoteFile.subgenre, Platform.directory) \
        .join(Platform).where(RemoteFile.role == "candidate")
    if platform_ids is not None:
        q = q.where(RemoteFile.platform_id.in_(platform_ids))
    changes: list[dict] = []
    classified = 0
    for fid, filename, genre, detail, full, norm, skey, sub, directory in s.execute(q):
        directory = canonical(directory)
        hit = index.lookup(directory, filename)
        new_genre, new_detail = hit if hit else (None, None)
        classified += hit is not None
        new_full = index.full_title(directory, filename)
        stem = stem_of(filename)
        new_norm = normalize_title(new_full) if new_full else normalize_title(stem)
        new_skey = search_key(f"{filename} {new_full}") if new_full else search_key(filename)
        new_sub = subgenres.classify(new_genre, [new_detail, index.ovgdb_raw(directory, filename)], new_full or stem)
        new = (new_genre, new_detail, new_full, new_norm, new_skey, new_sub)
        if new != (genre, detail, full, norm, skey, sub):
            changes.append(dict(zip(("id", "genre", "genre_detail", "full_title", "normalized_title", "search_key",
                                     "subgenre"), (fid, *new))))
    if changes:
        s.execute(update(RemoteFile), changes)
    return classified


def apply_all(sessions: sessionmaker[Session]) -> int:
    with sessions.begin() as s:
        return apply_genres(s)
