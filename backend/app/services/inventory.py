"""Inventaire en lecture seule de la racine des ROMs.

Règles :
- un dossier de premier niveau = une plateforme ;
- les dossiers `Imgs` (casse ignorée) sont listés à part comme images, jamais comme des jeux ;
- fichiers cachés et AppleDouble (`._*`) ignorés et signalés ;
- liens symboliques signalés, jamais suivis ;
- sous-dossiers parcourus jusqu'à MAX_DEPTH (jeux multi-disques, dossiers par jeu) ;
- le rôle de chaque fichier est déterminé par services.classify.
"""

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.device.paths import safe_join
from app.device.remote_fs import Entry, ReadOnlyRemoteFS
from app.platforms import IMAGE_DIR_NAMES, IMAGE_EXTENSIONS, MEDIA_DIR_NAMES, NOT_PLATFORM_DIRS, lookup
from app.schemas import InventoryOut, PlatformInventoryOut, PlatformOut, RemoteFileOut, RemoteImageOut
from app.services.classify import classify_directory, extension_of

MAX_DEPTH = 3
CONCURRENCY = 6


def file_id(remote_path: str) -> str:
    return hashlib.sha1(remote_path.encode()).hexdigest()[:16]


def platform_out(entry: Entry) -> PlatformOut:
    info = lookup(entry.name)
    return PlatformOut(
        directory=entry.name,
        label=info.label if info else None,
        label_status=info.label_status if info else "unmapped",
        kind=info.kind if info else "unknown",
        known=info is not None,
        is_symlink=entry.kind == "symlink",
    )


def platforms_from(entries: list[Entry]) -> list[PlatformOut]:
    """Dossiers de consoles parmi les entrées du dossier des ROMs."""
    out = [platform_out(e) for e in entries if e.kind in ("dir", "symlink") and not e.name.startswith(".")
           and e.name.lower() not in NOT_PLATFORM_DIRS]
    return sorted(out, key=lambda p: p.directory.lower())


async def list_platforms(fs: ReadOnlyRemoteFS) -> list[PlatformOut]:
    return platforms_from(await fs.listdir(fs.root))


async def _list_images(fs: ReadOnlyRemoteFS, path: str, base: str) -> list[RemoteImageOut]:
    out = []
    for e in await fs.listdir(path):
        if e.kind == "file" and not e.name.startswith(".") and extension_of(e.name) in IMAGE_EXTENSIONS:
            out.append(RemoteImageOut(relative_path=e.path[len(base) + 1:], filename=e.name,
                                      size=e.size, modified_at=e.modified_at))
    return out


async def scan_platform(fs: ReadOnlyRemoteFS, platform: PlatformOut, include_files: bool = True) -> PlatformInventoryOut:
    base = safe_join(fs.root, platform.directory)
    files: list[RemoteFileOut] = []
    images: list[RemoteImageOut] = []
    skipped: list[str] = []
    image_dir_present = False

    if platform.is_symlink:
        skipped.append(f"{platform.directory} (lien symbolique, non suivi)")
    else:
        stack: list[tuple[str, int]] = [(base, 0)]
        while stack:
            path, depth = stack.pop()
            dir_files: list[Entry] = []
            for e in await fs.listdir(path):
                rel = e.path[len(base) + 1:]
                if e.name.startswith("."):
                    skipped.append(rel)
                elif e.kind == "dir":
                    if e.name.lower() in IMAGE_DIR_NAMES:
                        image_dir_present = True
                        images.extend(await _list_images(fs, e.path, base))
                    elif e.name.lower() in MEDIA_DIR_NAMES:
                        skipped.append(f"{rel}/ (médias, pas des jeux)")
                    elif depth + 1 > MAX_DEPTH:
                        skipped.append(f"{rel}/ (profondeur > {MAX_DEPTH})")
                    else:
                        stack.append((e.path, depth + 1))
                elif e.kind == "file":
                    dir_files.append(e)
                elif e.kind == "symlink":
                    skipped.append(f"{rel} (lien symbolique, non suivi)")
                else:
                    skipped.append(f"{rel} (type spécial)")
            roles = classify_directory(platform.kind, [e.name for e in dir_files])
            for e in dir_files:
                files.append(RemoteFileOut(
                    id=file_id(e.path), platform=platform.directory, filename=e.name,
                    relative_path=e.path[len(base) + 1:], remote_path=e.path,
                    extension=extension_of(e.name), size=e.size, modified_at=e.modified_at,
                    role=roles[e.name], is_symlink=False,
                ))

    files.sort(key=lambda f: f.relative_path.lower())
    return PlatformInventoryOut(
        **platform.model_dump(),
        file_count=len(files),
        candidate_count=sum(1 for f in files if f.role == "candidate"),
        total_bytes=sum(f.size or 0 for f in files),
        image_dir_present=image_dir_present,
        image_count=len(images),
        skipped=skipped,
        files=files if include_files else None,
        images=images if include_files else None,
    )


ProgressCb = Callable[[PlatformInventoryOut | None, PlatformOut, Exception | None], Awaitable[None]]


async def scan_all(fs: ReadOnlyRemoteFS, include_files: bool = True, only: set[str] | None = None,
                   on_platform: ProgressCb | None = None,
                   platforms: list[PlatformOut] | None = None) -> InventoryOut:
    """Scanne toutes les plateformes. Si `on_platform` est fourni, une erreur sur une plateforme
    est transmise au callback au lieu d'interrompre le scan complet."""
    t0 = time.perf_counter()
    if platforms is None:
        platforms = await list_platforms(fs)
    if only:
        platforms = [p for p in platforms if p.directory in only]
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(p: PlatformOut) -> PlatformInventoryOut | None:
        async with sem:
            try:
                res = await scan_platform(fs, p, include_files)
            except Exception as exc:
                if on_platform is None:
                    raise
                await on_platform(None, p, exc)
                return None
            if on_platform:
                await on_platform(res, p, None)
            return res

    results = [r for r in await asyncio.gather(*(one(p) for p in platforms)) if r is not None]
    return InventoryOut(
        roms_root=fs.root,
        scanned_at=datetime.now(UTC),
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        platform_count=len(results),
        file_count=sum(r.file_count for r in results),
        candidate_count=sum(r.candidate_count for r in results),
        total_bytes=sum(r.total_bytes for r in results),
        platforms=results,
    )
