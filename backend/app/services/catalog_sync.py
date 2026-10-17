"""Synchronisation du catalogue SQLite avec la carte, en tâche de fond.

Garanties :
- aucune écriture sur la console (scan via ReadOnlyRemoteFS) ;
- aucune suppression physique en base : un fichier disparu reçoit `deleted_at` ;
- une plateforme dont le scan échoue ne voit aucun de ses fichiers marqué supprimé ;
- racine absente ou vide alors que le catalogue contient des jeux : synchronisation refusée
  (carte démontée, mauvais chemin), pour ne pas tout marquer comme supprimé.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import errors
from app.config import DeviceSettings
from app.db.models import Device, Platform, PlatformImage, RemoteFile, ScanChange, ScanRun, utcnow
from app.device.remote_fs import ReadOnlyRemoteFS
from app.device.ssh_client import DeviceClient
from app.schemas import PlatformInventoryOut, PlatformOut
from app.services import gameinfo, genres, inventory
from app.services.classify import display_title, normalize_title, region_of, search_key, stem_of

log = logging.getLogger(__name__)


class SyncManager:
    """Une seule synchronisation à la fois ; la tâche asyncio est conservée pour éviter son ramasse-miettes."""

    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions
        self.lock = asyncio.Lock()
        self.task: asyncio.Task | None = None

    def running(self) -> bool:
        return self.lock.locked()

    async def start(self, client: DeviceClient) -> int:
        if self.lock.locked():
            raise errors.AppError("sync_already_running", "Une synchronisation est déjà en cours", 409)
        await self.lock.acquire()
        try:
            run_id = await asyncio.to_thread(_create_run, self.sessions, client.settings)
        except BaseException:
            self.lock.release()
            raise
        self.task = asyncio.create_task(self._run(client, run_id))
        return run_id

    async def _run(self, client: DeviceClient, run_id: int) -> None:
        try:
            await run_sync(self.sessions, client, run_id)
        except Exception as exc:  # noqa: BLE001
            msg = exc.message if isinstance(exc, errors.AppError) else f"{type(exc).__name__}: {exc}"
            code = exc.code if isinstance(exc, errors.AppError) else "internal_error"
            if code == "internal_error":
                log.exception("synchronisation %s échouée", run_id)
            await asyncio.to_thread(_finish_run, self.sessions, run_id, "failed", f"{code}: {msg}")
        finally:
            self.lock.release()


# ---------- accès base (exécutés dans un thread) ----------

def _get_device(s: Session, settings: DeviceSettings) -> Device:
    dev = s.get(Device, 1)
    if dev is None:
        dev = Device(id=1, host=settings.host, port=settings.port, username=settings.username,
                     roms_root=settings.roms_root)
        s.add(dev)
    else:
        dev.host, dev.port, dev.username, dev.roms_root = settings.host, settings.port, settings.username, settings.roms_root
    return dev


def _create_run(sessions: sessionmaker[Session], settings: DeviceSettings, trigger: str = "manual") -> int:
    with sessions.begin() as s:
        _get_device(s, settings)
        run = ScanRun(device_id=1, status="running", trigger=trigger)
        s.add(run)
        s.flush()
        return run.id


def _finish_run(sessions: sessionmaker[Session], run_id: int, status: str, error: str | None = None) -> None:
    with sessions.begin() as s:
        run = s.get(ScanRun, run_id)
        run.status, run.error, run.finished_at = status, error, utcnow()


def _set_progress(sessions: sessionmaker[Session], run_id: int, total: int | None = None,
                  done: int | None = None, platform_error: tuple[str, str] | None = None) -> None:
    with sessions.begin() as s:
        run = s.get(ScanRun, run_id)
        if total is not None:
            run.platforms_total = total
        if done is not None:
            run.platforms_done = done
        if platform_error:
            run.platform_errors = {**(run.platform_errors or {}), platform_error[0]: platform_error[1]}


def _active_catalog_size(sessions: sessionmaker[Session]) -> int:
    with sessions() as s:
        return len(s.scalars(select(RemoteFile.id).where(RemoteFile.deleted_at.is_(None)).limit(1)).all())


def _storage(sessions, total: int, free: int) -> None:
    with sessions.begin() as s:
        dev = s.get(Device, 1)
        dev.total_bytes, dev.free_bytes, dev.storage_measured_at = total, free, utcnow()


def _match_image(stem: str, filename: str, images: dict[str, PlatformImage]) -> PlatformImage | None:
    return images.get(stem.lower()) or images.get(filename.lower())


def apply_platform(s: Session, run: ScanRun, listed: PlatformOut, inv: PlatformInventoryOut, now: datetime) -> None:
    plat = s.scalar(select(Platform).where(Platform.device_id == 1, Platform.directory == listed.directory))
    if plat is None:
        plat = Platform(device_id=1, directory=listed.directory)
        s.add(plat)
    plat.label, plat.label_status, plat.kind = listed.label, listed.label_status, listed.kind
    plat.present, plat.is_symlink = True, listed.is_symlink
    plat.image_dir_present, plat.last_scanned_at = inv.image_dir_present, now
    s.flush()

    # Images : simple reflet de l'état actuel (pas d'historique nécessaire).
    existing_imgs = {i.relative_path: i for i in s.scalars(select(PlatformImage).where(PlatformImage.platform_id == plat.id))}
    seen_imgs: set[str] = set()
    for img in inv.images or []:
        seen_imgs.add(img.relative_path)
        row = existing_imgs.get(img.relative_path)
        if row is None:
            row = PlatformImage(platform_id=plat.id, relative_path=img.relative_path)
            s.add(row)
        row.filename, row.stem_lower = img.filename, stem_of(img.filename).lower()
        row.size, row.mtime, row.matched = img.size, img.modified_at, False
    for rel, row in existing_imgs.items():
        if rel not in seen_imgs:
            s.delete(row)
    s.flush()
    by_stem: dict[str, PlatformImage] = {}
    for row in s.scalars(select(PlatformImage).where(PlatformImage.platform_id == plat.id)):
        # Priorité aux images du dossier Imgs racine de la plateforme.
        if row.stem_lower not in by_stem or row.relative_path.count("/") < by_stem[row.stem_lower].relative_path.count("/"):
            by_stem[row.stem_lower] = row

    existing = {f.relative_path: f for f in s.scalars(select(RemoteFile).where(RemoteFile.platform_id == plat.id))}
    seen: set[str] = set()
    pending: list[tuple[RemoteFile, str, int | None, datetime | None]] = []
    for f in inv.files or []:
        seen.add(f.relative_path)
        stem = stem_of(f.filename)
        row = existing.get(f.relative_path)
        change: str | None = None
        old_size, old_mtime = (row.size, row.mtime) if row else (None, None)
        if row is None:
            row = RemoteFile(platform_id=plat.id, relative_path=f.relative_path, first_seen_at=now)
            s.add(row)
            change = "added"
        elif row.deleted_at is not None:
            row.deleted_at = None
            change = "restored"
        elif row.size != f.size or row.mtime != f.modified_at:
            change = "modified"
        row.filename, row.extension, row.size, row.mtime, row.role = f.filename, f.extension, f.size, f.modified_at, f.role
        row.title, row.normalized_title = display_title(stem), normalize_title(stem)
        row.search_key, row.region = search_key(f.filename), region_of(stem)
        row.last_seen_at, row.last_scan_run_id = now, run.id
        img = _match_image(stem, f.filename, by_stem) if f.role == "candidate" else None
        row.image_relpath = img.relative_path if img else None
        if img:
            img.matched = True
        if change:
            pending.append((row, change, old_size, old_mtime))
            setattr(run, change, getattr(run, change) + 1)

    s.flush()  # un seul flush par plateforme pour obtenir les identifiants des nouveaux fichiers
    s.add_all(ScanChange(scan_run_id=run.id, remote_file_id=row.id, change=change, old_size=old_size,
                         new_size=row.size, old_mtime=old_mtime, new_mtime=row.mtime)
              for row, change, old_size, old_mtime in pending)

    for rel, row in existing.items():
        if rel not in seen and row.deleted_at is None:
            _mark_removed(s, run, row, now)

    run.files_seen += len(inv.files or [])
    run.images_seen += len(inv.images or [])
    run.images_matched += sum(1 for i in by_stem.values() if i.matched)


def _mark_removed(s: Session, run: ScanRun, row: RemoteFile, now: datetime) -> None:
    row.deleted_at = now
    s.add(ScanChange(scan_run_id=run.id, remote_file_id=row.id, change="removed",
                     old_size=row.size, new_size=None, old_mtime=row.mtime, new_mtime=None))
    run.removed += 1


def _apply(sessions: sessionmaker[Session], run_id: int, listed: list[PlatformOut],
           results: dict[str, PlatformInventoryOut], failed: set[str], partial_scope: bool = False) -> str:
    now = datetime.now(UTC)
    with sessions.begin() as s:
        run = s.get(ScanRun, run_id)
        for p in listed:
            if p.directory in results:
                apply_platform(s, run, p, results[p.directory], now)
        listed_dirs = {p.directory for p in listed}
        # Une actualisation ciblée (après transfert) ne lit que quelques dossiers : elle ne doit pas
        # conclure que les autres ont disparu.
        for plat in ([] if partial_scope else s.scalars(select(Platform).where(Platform.device_id == 1))):
            if plat.directory not in listed_dirs and plat.present:
                # Dossier disparu de la carte : la plateforme et ses fichiers passent à "absent".
                plat.present = False
                for row in s.scalars(select(RemoteFile).where(RemoteFile.platform_id == plat.id,
                                                              RemoteFile.deleted_at.is_(None))):
                    _mark_removed(s, run, row, now)
        if results:
            synced = set(s.scalars(select(Platform.id).where(Platform.directory.in_(results))))
            genres.apply_genres(s, synced)
            gameinfo.apply_info(s, synced)
        status = "partial" if failed else "completed"
        run.status, run.finished_at = status, utcnow()
        run.platforms_done = len(results) + len(failed)
        return status


# ---------- orchestration ----------

async def run_sync(sessions: sessionmaker[Session], client: DeviceClient, run_id: int) -> str:
    async with client.sftp() as (conn, sftp):
        fs = ReadOnlyRemoteFS(conn, sftp, client.settings.roms_root)
        if not await fs.root_exists():
            raise errors.remote_not_found(fs.root)
        listed = await inventory.list_platforms(fs)
        if not listed and await asyncio.to_thread(_active_catalog_size, sessions):
            raise errors.AppError("root_empty", "La racine des ROMs est vide alors que le catalogue contient des "
                                  "fichiers (carte démontée ?). Synchronisation annulée, rien n'a été modifié.", 409)
        try:
            st = await fs.storage()
            await asyncio.to_thread(_storage, sessions, st.total_bytes, st.free_bytes)
        except errors.AppError:
            pass
        await asyncio.to_thread(_set_progress, sessions, run_id, total=len(listed), done=0)

        results: dict[str, PlatformInventoryOut] = {}
        failed: set[str] = set()

        async def on_platform(res, p, exc):
            if exc is not None:
                failed.add(p.directory)
                detail = exc.message if isinstance(exc, errors.AppError) else f"{type(exc).__name__}: {exc}"
                await asyncio.to_thread(_set_progress, sessions, run_id, platform_error=(p.directory, detail))
            else:
                results[p.directory] = res
            await asyncio.to_thread(_set_progress, sessions, run_id, done=len(results) + len(failed))

        await inventory.scan_all(fs, include_files=True, on_platform=on_platform, platforms=listed)

    # Les plateformes en échec restent dans `listed` : leurs fichiers ne sont ni modifiés ni supprimés.
    return await asyncio.to_thread(_apply, sessions, run_id, listed, results, failed)


async def refresh_platforms(sessions: sessionmaker[Session], client: DeviceClient, dirs: set[str],
                            trigger: str = "transfer") -> int:
    """Relit seulement quelques dossiers (après un transfert) et met leur contenu à jour dans le catalogue."""
    run_id = await asyncio.to_thread(_create_run, sessions, client.settings, trigger)
    try:
        async with client.sftp() as (conn, sftp):
            fs = ReadOnlyRemoteFS(conn, sftp, client.settings.roms_root)
            listed = [p for p in await inventory.list_platforms(fs) if p.directory in dirs]
            await asyncio.to_thread(_set_progress, sessions, run_id, total=len(listed), done=0)
            results = {p.directory: await inventory.scan_platform(fs, p) for p in listed}
            try:
                st = await fs.storage()
                await asyncio.to_thread(_storage, sessions, st.total_bytes, st.free_bytes)
            except errors.AppError:
                pass
        await asyncio.to_thread(_apply, sessions, run_id, listed, results, set(), True)
    except Exception as exc:  # noqa: BLE001
        msg = f"{exc.code}: {exc.message}" if isinstance(exc, errors.AppError) else f"{type(exc).__name__}: {exc}"
        await asyncio.to_thread(_finish_run, sessions, run_id, "failed", msg)
    return run_id
