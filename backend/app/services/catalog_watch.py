"""Veille de la carte : retrouve dans le catalogue (et donc dans la recherche) les jeux ajoutés ou retirés sans
passer par Game Manager (carte lue sur le Mac, autre outil, copie à la main).

Toutes les WATCH_SECONDS, une seule lecture du dossier des ROMs (SFTP, connexion partagée du pool) donne la date
de modification de chaque dossier de console : ajouter, renommer ou supprimer un fichier dans un dossier change
sa date. Seuls les dossiers dont la date a bougé sont relus (catalog_sync.refresh_platforms) ; un dossier de
console apparu ou disparu déclenche une synchronisation complète.

Au premier passage (démarrage, console de nouveau joignable), un dossier est relu si sa date est postérieure à
sa dernière lecture : on rattrape ce qui a changé pendant que l'application était fermée. Ensuite, on compare à
la lecture précédente, ce qui ne dépend plus de l'horloge de la console.

Limite : un fichier ajouté dans un sous-dossier (jeu multi-disque, Imgs) ne change que la date du sous-dossier ;
il apparaît à la prochaine synchronisation complète.

Rien n'est écrit sur la console. La veille se tait quand la console est éteinte ou pas encore configurée, et attend
pendant une synchronisation ou un transfert. AGM_NO_WATCH=1 la coupe.
"""

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import errors
from app.db.models import Platform
from app.device.pool import DevicePool
from app.device.ssh_client import DeviceClient
from app.services import catalog_sync, inventory

log = logging.getLogger("agm.watch")
WATCH_SECONDS = 60


class CatalogWatcher:
    def __init__(self, sessions: sessionmaker[Session], sync: catalog_sync.SyncManager, transfers_idle: asyncio.Event,
                 pool: DevicePool, client_factory: Callable[[], DeviceClient]):
        self.sessions = sessions
        self.sync = sync
        self.transfers_idle = transfers_idle
        self.pool = pool
        self.client_factory = client_factory
        self._seen: dict[str, datetime | None] | None = None  # dernière lecture : dossier -> date
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if os.environ.get("AGM_NO_WATCH") != "1" and self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.check_once()
            except Exception:  # noqa: BLE001 — la veille ne doit jamais s'arrêter
                log.exception("veille de la carte")
            await asyncio.sleep(WATCH_SECONDS)

    def _last_scans(self) -> dict[str, datetime | None]:
        with self.sessions() as s:
            return {p.directory: p.last_scanned_at for p in s.scalars(select(Platform).where(Platform.present))}

    async def check_once(self) -> str:
        """Un passage. Renvoie ce qui a été fait : busy, offline, unchanged, refresh, full."""
        if self.sync.lock.locked() or not self.transfers_idle.is_set():
            return "busy"
        client = self.client_factory()
        try:
            async with self.pool.fs(client) as fs:
                entries = await fs.listdir(fs.root)
        except errors.AppError:
            self._seen = None  # console éteinte ou pas configurée : on rattrapera au retour
            return "offline"
        names = {p.directory for p in inventory.platforms_from(entries)}
        current = {e.name: e.modified_at for e in entries if e.name in names}
        known = await asyncio.to_thread(self._last_scans)

        if set(current) != set(known):
            if not known:
                return "offline"  # catalogue jamais synchronisé : c'est à l'utilisateur de lancer la première
            log.info("veille : dossiers de consoles ajoutés ou retirés, synchronisation complète")
            await self.sync.start(client)
            self._seen = current
            return "full"

        if self._seen is None:
            changed = {d for d, m in current.items() if m and (known[d] is None or m > known[d])}
        else:
            changed = {d for d, m in current.items() if m != self._seen.get(d)}
        self._seen = current
        if not changed:
            return "unchanged"
        log.info("veille : %s relu(s)", ", ".join(sorted(changed)))
        async with self.sync.lock:
            await catalog_sync.refresh_platforms(self.sessions, client, changed, trigger="watch")
        return "refresh"
