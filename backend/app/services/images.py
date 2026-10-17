"""Cache local des images de présentation lues dans les dossiers Imgs de la console.

L'original est lu une fois par SFTP (lecture seule) ; une miniature WebP est dérivée pour la grille.
"""

import asyncio
import hashlib
import io
import os
from pathlib import Path

from app.device.paths import safe_join
from app.device.remote_fs import ReadOnlyRemoteFS

MAX_IMAGE_BYTES = 10 * 1024 * 1024
THUMB_MAX_SIDE = 360
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
               "webp": "image/webp", "bmp": "image/bmp"}


def media_type(path: str) -> str:
    return MEDIA_TYPES.get(path.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def _write_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, target)


def _make_thumb(original: Path, target: Path) -> Path | None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(original) as im:
            im.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.Resampling.LANCZOS)
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=82, method=4)
    except (UnidentifiedImageError, OSError, ValueError):
        return None  # image illisible : on servira l'original
    _write_atomic(target, buf.getvalue())
    return target


class ImageCache:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[Path, asyncio.Lock] = {}

    def path_for(self, platform_dir: str, relpath: str, size: int | None, mtime_ts: float | None) -> Path:
        # La clé inclut taille et date : une image modifiée sur la carte invalide le cache.
        key = hashlib.sha1(f"{platform_dir}/{relpath}|{size}|{mtime_ts}".encode()).hexdigest()
        ext = relpath.rsplit(".", 1)[-1].lower() if "." in relpath else "bin"
        return self.root / platform_dir / f"{key}.{ext}"

    @staticmethod
    def thumb_path(original: Path) -> Path:
        return original.with_name(original.stem + ".thumb.webp")

    def lock(self, path: Path) -> asyncio.Lock:
        # Évite de lire deux fois la même image quand la grille la demande en rafale.
        return self._locks.setdefault(path, asyncio.Lock())

    async def fetch(self, fs: ReadOnlyRemoteFS, platform_dir: str, relpath: str, target: Path) -> Path:
        data = await fs.read_file(safe_join(fs.root, platform_dir, relpath), MAX_IMAGE_BYTES)
        await asyncio.to_thread(_write_atomic, target, data)
        return target

    async def thumbnail(self, original: Path) -> Path:
        thumb = self.thumb_path(original)
        if thumb.exists():
            return thumb
        return await asyncio.to_thread(_make_thumb, original, thumb) or original
