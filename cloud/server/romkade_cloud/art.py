"""Jaquettes servies par le cloud : /art/<clé>.webp, pour l'interface MCP Apps (ChatGPT, Claude…).

Même source et même recherche que le Manager (app.services.boxart : libretro-thumbnails, nom exact puis titre le
plus proche). L'image est téléchargée une fois, gardée en cache sur le serveur, servie en vignette WebP.
La clé (catalog.art_key) ne dit rien du compte : la même jaquette sert à tous ceux qui ont le même jeu.
"""

from pathlib import Path
from types import SimpleNamespace

from app.config import data_dir
from app.services import boxart, genres
from app.services.classify import stem_of  # noqa: F401 — même découpage que le Manager

from .store import Store


class Art:
    def __init__(self, store: Store, root: Path | None = None):
        self.store = store
        self.boxes = boxart.BoxartStore(root or data_dir() / "boxart")

    async def path(self, key: str, size: str = "thumb") -> Path | None:
        row = self.store.game_for_art(key)
        if row is None or not boxart.has_source(row["platform_dir"]):
            return None
        filename = row["relative_path"].rsplit("/", 1)[-1]
        # Le Manager passe une ligne RemoteFile ; seuls ces champs servent à la recherche de la jaquette.
        f = SimpleNamespace(platform=SimpleNamespace(directory=row["platform_dir"]), filename=filename,
                            full_title=row["full_title"])
        original = await self.boxes.get(f, genres.load_index())
        if original is None:
            return None
        return original if size == "full" else await self.boxes.thumbnail(original)
