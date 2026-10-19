"""Catalogue envoyé par l'agent : liste brute des fichiers du dossier des ROMs, triée ici avec les règles du Manager.

Le tri se fait dans le cloud (et non sur la console) : on corrige une règle sans mettre à jour les agents.
L'agent n'envoie que des noms de fichiers et des tailles, jamais le contenu des jeux.
"""

from collections import defaultdict

from app.platforms import IMAGE_DIR_NAMES, MEDIA_DIR_NAMES, NOT_PLATFORM_DIRS, canonical, lookup
from app.services.classify import classify_directory, display_title, normalize_title, region_of, stem_of

MAX_FILES = 50_000
EXCLUDED_KINDS = {"apps", "ports"}  # programmes, pas des jeux
SKIPPED_FOLDERS = IMAGE_DIR_NAMES | MEDIA_DIR_NAMES  # jaquettes, vidéos… rangées à côté des jeux


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
                games.append({"platform_dir": directory, "platform_code": code, "platform_label": label,
                              "relative_path": f"{folder}/{name}" if folder else name,
                              "title": display_title(stem), "normalized": normalize_title(stem),
                              "region": region_of(stem), "size": size})
    return games
