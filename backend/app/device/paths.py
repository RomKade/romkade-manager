"""Garde de chemins distants : tout doit rester sous la racine configurée."""

import posixpath

from app.errors import path_forbidden


def is_within(root: str, path: str) -> bool:
    root = root.rstrip("/")
    return path == root or path.startswith(root + "/")


def safe_join(root: str, *parts: str) -> str:
    """Construit un chemin sous `root` à partir de segments non fiables (ex. venant du navigateur)."""
    for part in parts:
        if not part or "\x00" in part:
            raise path_forbidden(part, "segment vide ou caractère nul")
        if part.startswith("/"):
            raise path_forbidden(part, "chemin absolu interdit")
        if any(seg in ("..", ".") for seg in part.split("/")):
            raise path_forbidden(part, "segment '.' ou '..' interdit")
    joined = posixpath.normpath(posixpath.join(root, *parts))
    if not is_within(root, joined):
        raise path_forbidden(joined, "hors de la racine")
    return joined


def platform_dir_name_ok(name: str) -> bool:
    return bool(name) and "/" not in name and name not in (".", "..") and "\x00" not in name
