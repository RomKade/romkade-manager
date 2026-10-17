"""File d'attente des transferts Mac -> console, traitée un fichier à la fois.

Pour chaque fichier : vérifications de dernière minute (dossier, homonyme, espace), écriture sous un nom
temporaire, contrôle de taille puis d'empreinte SHA-256 calculée sur la console, sauvegarde éventuelle de
l'ancien fichier, renommage final. En cas d'erreur ou d'annulation, le fichier temporaire est supprimé
et l'ancien fichier, s'il avait été déplacé, est remis en place.
"""

import asyncio
import logging
import posixpath
import time
import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import errors
from app.db.models import Device, Transfer, utcnow
from app.device.remote_writer import RemoteWriter
from app.device.ssh_client import DeviceClient
from app.services import catalog_sync
from app.services.classify import extension_of, stem_of
from app.services.staging import StagingStore
from app.services.transfer_plan import margin_for

log = logging.getLogger(__name__)
ACTIVE = ("queued", "running", "verifying")


@dataclass
class Live:
    bytes_done: int = 0
    total: int = 0
    speed_bps: float = 0.0
    _last_t: float = 0.0
    _last_b: int = 0

    def update(self, done: int, total: int) -> None:
        now = time.monotonic()
        if self._last_t:
            dt = now - self._last_t
            if dt >= 0.25:
                inst = (done - self._last_b) / dt
                self.speed_bps = inst if not self.speed_bps else 0.7 * self.speed_bps + 0.3 * inst
                self._last_t, self._last_b = now, done
        else:
            self._last_t, self._last_b = now, done
        self.bytes_done, self.total = done, total


def unique_name(filename: str, taken_lower: set[str]) -> str:
    """« Jeu (USA).smc » -> « Jeu (USA) (2).smc », en ignorant la casse comme exFAT."""
    stem, ext = stem_of(filename), extension_of(filename)
    for i in range(2, 1000):
        candidate = f"{stem} ({i}).{ext}" if ext else f"{stem} ({i})"
        if candidate.lower() not in taken_lower:
            return candidate
    raise errors.AppError("no_free_name", "Impossible de trouver un nom libre", 409)


class TransferManager:
    def __init__(self, sessions: sessionmaker[Session], staging: StagingStore, sync: "catalog_sync.SyncManager",
                 client_factory: Callable[[], DeviceClient]):
        self.sessions = sessions
        self.staging = staging
        self.sync = sync
        self.client_factory = client_factory
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.live: dict[int, Live] = {}
        self.current: tuple[int, asyncio.Task] | None = None
        self.worker: asyncio.Task | None = None
        self.dirty: set[str] = set()
        self.idle = asyncio.Event()
        self.idle.set()

    # ---------- base ----------

    def _update(self, tid: int, **values) -> None:
        with self.sessions.begin() as s:
            row = s.get(Transfer, tid)
            for k, v in values.items():
                setattr(row, k, v)

    def _get(self, tid: int) -> Transfer:
        with self.sessions() as s:
            row = s.get(Transfer, tid)
            if row is None:
                raise errors.AppError("transfer_not_found", "Transfert introuvable", 404, {"id": tid})
            s.expunge(row)
            return row

    # ---------- API interne ----------

    async def enqueue(self, items: list[dict]) -> list[int]:
        batch = uuid.uuid4().hex
        ids = []
        with self.sessions.begin() as s:
            for it in items:
                up = self.staging.get(it["upload_id"])
                row = Transfer(batch_id=batch, upload_id=up.id, filename=up.filename, platform_dir=it["platform"],
                               size=up.size, sha256=up.sha256, on_conflict=it["on_conflict"], status="queued")
                s.add(row)
                s.flush()
                ids.append(row.id)
        for tid in ids:
            self.queue.put_nowait(tid)
        self.idle.clear()
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._work())
        return ids

    async def cancel(self, tid: int) -> None:
        row = await asyncio.to_thread(self._get, tid)
        if row.status not in ACTIVE:
            raise errors.AppError("transfer_not_active", "Ce transfert est déjà terminé", 409, {"status": row.status})
        if self.current and self.current[0] == tid:
            self.current[1].cancel()
        else:
            await asyncio.to_thread(self._update, tid, status="cancelled", finished_at=utcnow(),
                                    error="Annulé avant le début de la copie")

    async def wait_idle(self, timeout: float = 30) -> None:
        await asyncio.wait_for(self.idle.wait(), timeout)

    async def close(self) -> None:
        if self.current:
            self.current[1].cancel()
        if self.worker:
            self.worker.cancel()

    # ---------- traitement ----------

    async def _work(self) -> None:
        swept: set[str] = set()
        try:
            while True:
                try:
                    tid = self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                row = await asyncio.to_thread(self._get, tid)
                if row.status != "queued":
                    continue
                task = asyncio.create_task(self._process(row, swept))
                self.current = (tid, task)
                try:
                    await task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():  # arrêt du serveur, pas une annulation utilisateur
                        raise
                except Exception:  # noqa: BLE001
                    log.exception("transfert %s", tid)
                finally:
                    self.current = None
                    self.live.pop(tid, None)
            await self._refresh_catalog()
        finally:
            self.idle.set()

    async def _refresh_catalog(self) -> None:
        if not self.dirty:
            return
        dirs, self.dirty = set(self.dirty), set()
        if self.sync.lock.locked():
            return  # une synchronisation complète est en cours, elle verra les nouveaux fichiers
        async with self.sync.lock:
            await catalog_sync.refresh_platforms(self.sessions, self.client_factory(), dirs)

    def _card_total(self) -> int | None:
        with self.sessions() as s:
            dev = s.get(Device, 1)
            return dev.total_bytes if dev else None

    async def _process(self, row: Transfer, swept: set[str]) -> None:
        tid = row.id
        live = self.live[tid] = Live(total=row.size)
        temp: str | None = None
        backup: tuple[str, str] | None = None
        writer: RemoteWriter | None = None
        upd = lambda **v: asyncio.to_thread(self._update, tid, **v)  # noqa: E731
        # La connexion reste ouverte jusqu'après le nettoyage (fichier temporaire, restauration de sauvegarde).
        stack = AsyncExitStack()
        try:
            await upd(status="running", started_at=utcnow(), error=None)
            local = self.staging.data_path(row.upload_id)
            if not local.exists():
                raise errors.AppError("upload_not_found", "Le fichier en attente sur le Mac a disparu", 410)
            client = self.client_factory()
            conn, sftp = await stack.enter_async_context(client.sftp())
            writer = RemoteWriter(conn, sftp, client.settings.roms_root)
            ppath = await writer.platform_dir(row.platform_dir)
            if ppath not in swept:
                swept.add(ppath)
                if n := await writer.sweep_temps(ppath):
                    log.info("%s fichier(s) temporaire(s) orphelin(s) supprimé(s) dans %s", n, ppath)

            names = await writer.names_in(ppath)
            lower = {n.lower(): n for n in names}
            existing = row.filename if row.filename in names else lower.get(row.filename.lower())
            target = row.filename
            if existing is not None:
                if row.on_conflict == "skip":
                    await upd(status="skipped", finished_at=utcnow(), final_filename=existing,
                              remote_path=f"{ppath}/{existing}",
                              error="Un fichier du même nom est déjà sur la carte : rien n'a été copié")
                    self.staging.delete(row.upload_id)
                    return
                if row.on_conflict == "rename":
                    target = unique_name(row.filename, set(lower))
            final = writer.final_path(ppath, target)

            free = await writer.free_bytes()
            margin = margin_for(await asyncio.to_thread(self._card_total))
            if free is not None and row.size + margin > free:
                raise errors.AppError("insufficient_space", "Espace insuffisant sur la carte", 507,
                                      {"needed": row.size + margin, "free": free})

            token = uuid.uuid4().hex
            temp = writer.temp_path(ppath, token)
            await writer.upload_temp(str(local), ppath, token, live.update)

            await upd(status="verifying", bytes_done=row.size)
            remote_size = await writer.exists(temp)
            if remote_size != row.size:
                raise errors.AppError("verify_failed", "La taille du fichier copié ne correspond pas", 502,
                                      {"expected": row.size, "got": remote_size})
            digest = await writer.sha256(temp)
            if digest is not None and digest != row.sha256:
                raise errors.AppError("verify_failed", "L'empreinte du fichier copié ne correspond pas", 502)
            method = "sha256" if digest else "size"

            if existing is not None and row.on_conflict == "overwrite":
                original = f"{ppath}/{existing}"
                # Si l'existant ne diffère que par la casse, il est sauvegardé et le nouveau prend le nom demandé.
                backup = (await writer.move_to_backup(row.platform_dir, original), original)
            await writer.finalize(temp, final)
            temp = None
            await upd(status="completed", finished_at=utcnow(), final_filename=posixpath.basename(final),
                      remote_path=final, backup_path=backup[0] if backup else None, verify_method=method,
                      bytes_done=row.size)
            backup = None
            self.dirty.add(row.platform_dir)
            self.staging.delete(row.upload_id)
        except asyncio.CancelledError:
            await self._cleanup(writer, temp, backup)
            await upd(status="cancelled", finished_at=utcnow(), error="Annulé pendant la copie. Rien n'a été modifié sur la carte.")
            raise
        except Exception as exc:  # noqa: BLE001
            await self._cleanup(writer, temp, backup)
            msg = exc.message if isinstance(exc, errors.AppError) else f"{type(exc).__name__}: {exc}"
            code = exc.code if isinstance(exc, errors.AppError) else "transfer_error"
            await upd(status="failed", finished_at=utcnow(), error=f"{code}: {msg}")
        finally:
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def _cleanup(self, writer: RemoteWriter | None, temp: str | None, backup: tuple[str, str] | None) -> None:
        if writer is None:
            return
        try:
            if temp:
                await asyncio.shield(writer.remove_temp(temp))
            if backup:
                await asyncio.shield(writer.restore_backup(*backup))
        except Exception:  # noqa: BLE001 - connexion perdue : nettoyage au prochain envoi (sweep_temps)
            log.warning("nettoyage incomplet (temp=%s, backup=%s)", temp, backup)

    # ---------- lecture ----------

    def list_rows(self, s: Session, limit: int) -> list[Transfer]:
        active = list(s.scalars(select(Transfer).where(Transfer.status.in_(ACTIVE)).order_by(Transfer.id)))
        done = list(s.scalars(select(Transfer).where(Transfer.status.not_in(ACTIVE))
                              .order_by(Transfer.id.desc()).limit(limit)))
        return active + done
