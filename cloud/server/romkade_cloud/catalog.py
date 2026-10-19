"""Catalogue envoyé par l'agent : liste brute des fichiers du dossier des ROMs, triée et enrichie ici avec les
règles et les bases du Manager.

Le tri se fait dans le cloud (et non sur la console) : on corrige une règle ou on enrichit le catalogue sans mettre
à jour les agents. La liste brute est gardée ; quand VERSION change, les catalogues sont recalculés au démarrage.
L'agent n'envoie que des noms de fichiers et des tailles, jamais le contenu des jeux.

Enrichissement (sans réseau) : titre complet des jeux d'arcade (« sf2 » -> « Street Fighter II… »), genre,
année, développeur, éditeur, résumé (app/data/genres.json.gz et gameinfo.json.gz du Manager). La jaquette est
cherchée à la demande (art.py), d'après `art_key`.
"""

import hashlib
from collections import defaultdict

from app.platforms import IMAGE_DIR_NAMES, MEDIA_DIR_NAMES, NOT_PLATFORM_DIRS, canonical, lookup
from app.services import gameinfo, genres
from app.services.classify import (classify_directory, display_title, normalize_title, region_of, search_key,
                                   stem_of)

VERSION = 4  # change quand build() change : les catalogues gardés sont recalculés
MAX_FILES = 50_000
EXCLUDED_KINDS = {"apps", "ports"}  # programmes, pas des jeux
SKIPPED_FOLDERS = IMAGE_DIR_NAMES | MEDIA_DIR_NAMES  # jaquettes, vidéos… rangées à côté des jeux


def art_key(platform_dir: str, filename: str, full_title: str | None) -> str:
    """Clé de la jaquette : même jeu (même fichier) = même image, quel que soit le compte."""
    return hashlib.sha1(f"{canonical(platform_dir)}/{filename}|{full_title or ''}".encode()).hexdigest()[:20]


def build(files: list) -> list[dict]:
    """Jeux du catalogue à partir de [[dossier de plateforme, chemin relatif, taille], …]."""
    by_dir: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for item in files[:MAX_FILES]:
        if not (isinstance(item, list | tuple) and len(item) == 3):
            continue
        directory, rel, size = item
        if not isinstance(directory, str) or not isinstance(rel, str) or directory.lower() in NOT_PLATFORM_DIRS:
            continue
        parts = rel.split("/")
        if "/" in directory or rel.startswith("/") or ".." in parts:
            continue
        if any(p.lower() in SKIPPED_FOLDERS or p.startswith(".") for p in parts):
            continue
        by_dir[directory].append((rel, size if isinstance(size, int) else 0))

    genre_index = genres.load_index()
    info_index = gameinfo.load_index()
    games: list[dict] = []
    for directory, entries in by_dir.items():
        info = lookup(directory)
        if info is not None and info.kind in EXCLUDED_KINDS:
            continue
        code = canonical(directory)
        label = (info.label if info and info.label else directory)
        # Le Manager classe dossier par dossier (pistes d'un .cue, disques d'un .m3u…).
        folders: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for rel, size in entries:
            folder, _, name = rel.rpartition("/")
            folders[folder].append((name, size))
        for folder, items in folders.items():
            roles = classify_directory(info.kind if info else "unknown", [n for n, _ in items])
            for name, size in items:
                if roles.get(name) != "candidate":
                    continue
                stem = stem_of(name)
                full = genre_index.full_title(code, name)
                genre = genre_index.lookup(code, name)
                facts = info_index.lookup(code, name) or {}
                games.append({
                    "platform_dir": directory, "platform_code": code, "platform_label": label,
                    "relative_path": f"{folder}/{name}" if folder else name,
                    "title": display_title(full) if full else display_title(stem),
                    "full_title": full,
                    "normalized": normalize_title(full) if full else normalize_title(stem),
                    "search": search_key(f"{name} {full}") if full else search_key(name),
                    "region": region_of(full or stem), "size": size,
                    "genre": genre[0] if genre else None,
                    "year": facts.get("release_year"), "developer": facts.get("developer"),
                    "publisher": facts.get("publisher"), "description": facts.get("description"),
                    "art_key": art_key(directory, name, full),
                })
    return games
