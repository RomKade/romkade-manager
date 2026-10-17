"""Connexion SSH/SFTP partagée pour les lectures fréquentes (jaquettes).

Sans elle, chaque image affichée ouvrirait sa propre connexion SSH ; le serveur de la console
refuse alors les connexions simultanées au-delà de quelques-unes (MaxStartups).
Une seule connexion est gardée ouverte, réutilisée par toutes les requêtes (SFTP accepte des
requêtes concurrentes), recréée si les réglages changent ou si elle tombe, et fermée après
IDLE_SECONDS sans usage.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import asyncssh

from app import errors

from app.device.remote_fs import ReadOnlyRemoteFS
from app.device.ssh_client import DeviceClient

IDLE_SECONDS = 90
# Après un échec de connexion (console éteinte, en veille), les appels suivants échouent tout de suite pendant
# ce délai au lieu d'attendre chacun le délai de connexion (8 s par défaut).
DOWN_SECONDS = 15


class DevicePool:
    _key_down: tuple | None = None

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._stack: AsyncExitStack | None = None
        self._fs: ReadOnlyRemoteFS | None = None
        self._conn: asyncssh.SSHClientConnection | None = None
        self._sftp: asyncssh.SFTPClient | None = None
        self._down_until = 0.0
        self._down_error: errors.AppError | None = None
        self._key: tuple | None = None
        self._last_used = 0.0
        self._users = 0
        self._reaper: asyncio.Task | None = None

    @staticmethod
    def _settings_key(client: DeviceClient) -> tuple:
        s = client.settings
        return (s.host, s.port, s.username, s.auth_method, s.key_path, s.roms_root)

    async def _open(self, client: DeviceClient) -> ReadOnlyRemoteFS:
        key = self._settings_key(client)
        if self._down_error is not None and self._key_down == key and time.monotonic() < self._down_until:
            raise self._down_error
        stack = AsyncExitStack()
        try:
            conn, sftp = await stack.enter_async_context(client.sftp())
        except errors.AppError as exc:
            await stack.aclose()
            if exc.code in errors.NETWORK_CODES:
                self._down_error, self._key_down, self._down_until = exc, key, time.monotonic() + DOWN_SECONDS
            raise
        except BaseException:
            await stack.aclose()
            raise
        self._down_error = None
        self._conn, self._sftp = conn, sftp
        self._stack, self._key = stack, key
        self._fs = ReadOnlyRemoteFS(conn, sftp, client.settings.roms_root)
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self._reap())
        return self._fs

    async def _close_locked(self) -> None:
        stack, self._stack, self._fs, self._key = self._stack, None, None, None
        self._conn = self._sftp = None
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001 - connexion déjà morte
                pass

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()
        if self._reaper:
            self._reaper.cancel()

    async def _reap(self) -> None:
        while True:
            await asyncio.sleep(10)
            async with self._lock:
                if self._fs is None:
                    return
                if self._users == 0 and time.monotonic() - self._last_used > IDLE_SECONDS:
                    await self._close_locked()
                    return

    @asynccontextmanager
    async def fs(self, client: DeviceClient) -> AsyncIterator[ReadOnlyRemoteFS]:
        async with self._lock:
            if self._fs is not None and self._key != self._settings_key(client):
                await self._close_locked()
            fs = self._fs or await self._open(client)
            self._users += 1
        try:
            yield fs
        except (asyncssh.ConnectionLost, asyncssh.DisconnectError, OSError, BrokenPipeError):
            async with self._lock:
                if self._fs is fs:
                    await self._close_locked()
            raise
        finally:
            self._users -= 1
            self._last_used = time.monotonic()

    @asynccontextmanager
    async def session(self, client: DeviceClient) -> AsyncIterator[tuple[asyncssh.SSHClientConnection, asyncssh.SFTPClient]]:
        """Connexion SSH et client SFTP partagés (pour lire hors de la racine des ROMs : sauvegardes…)."""
        async with self.fs(client):
            yield self._conn, self._sftp

    async def run(self, client: DeviceClient, command: str, timeout: float = 20) -> tuple[int, str]:
        """Exécute une commande sur la connexion partagée ; une seule nouvelle tentative si elle est tombée."""
        for attempt in (1, 2):
            try:
                async with self.session(client) as (conn, _sftp):
                    r = await conn.run(command, check=False, timeout=timeout)
                    return (r.exit_status or 0), str(r.stdout or "")
            except asyncssh.TimeoutError as exc:
                raise errors.AppError("device_command_timeout", f"La console n'a pas répondu à temps ({timeout:.0f} s).",
                                      504, {"timeout": timeout}) from exc
            except (asyncssh.ConnectionLost, asyncssh.DisconnectError, asyncssh.ChannelOpenError, BrokenPipeError, OSError):
                async with self._lock:
                    await self._close_locked()
                if attempt == 2:
                    raise errors.AppError("device_unreachable", "Connexion à la console perdue", 503)
        raise AssertionError("inaccessible")
