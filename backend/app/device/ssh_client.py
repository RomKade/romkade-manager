"""Connexion SSH/SFTP à la console via AsyncSSH, avec vérification de la clé d'hôte.

Une connexion est ouverte par opération (context manager). Les exceptions AsyncSSH et
réseau sont converties en AppError avec des codes stables.
"""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncssh

from app import errors
from app.config import DeviceSettings
from app.credentials import CredentialStore


def known_hosts_entry_host(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


class HostKeyStore:
    """known_hosts dédié à l'application."""

    def __init__(self, path: Path):
        self.path = path
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.touch(mode=0o600)

    def has_entry(self, host: str, port: int) -> bool:
        target = known_hosts_entry_host(host, port)
        for line in self.path.read_text().splitlines():
            if line.strip() and not line.startswith("#") and target in line.split()[0].split(","):
                return True
        return False

    def matches(self, host: str, port: int, key: asyncssh.SSHKey) -> bool:
        """La clé présentée est-elle celle approuvée pour cet hôte ?"""
        target = known_hosts_entry_host(host, port)
        pub = key.export_public_key("openssh").decode().split()[:2]
        for line in self.path.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and not line.startswith("#") and target in parts[0].split(",") and parts[1:3] == pub:
                return True
        return False

    def fingerprint(self, host: str, port: int) -> str | None:
        """Empreinte SHA-256 de la clé approuvée pour cet hôte, sans contacter la console (None si aucune)."""
        target = known_hosts_entry_host(host, port)
        for line in self.path.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and not line.startswith("#") and target in parts[0].split(","):
                try:
                    return fingerprint(asyncssh.import_public_key(" ".join(parts[1:3])))
                except (asyncssh.KeyImportError, ValueError):
                    return None
        return None

    def trust(self, host: str, port: int, key: asyncssh.SSHKey) -> None:
        target = known_hosts_entry_host(host, port)
        lines = [
            ln for ln in self.path.read_text().splitlines()
            if ln.strip() and target not in ln.split()[0].split(",")
        ]
        pub = key.export_public_key("openssh").decode().strip()
        lines.append(f"{target} {pub}")
        self.path.write_text("\n".join(lines) + "\n")


async def fetch_host_key(settings: DeviceSettings) -> asyncssh.SSHKey:
    """Récupère la clé d'hôte sans s'authentifier (pour le TOFU explicite)."""
    try:
        key = await asyncio.wait_for(
            asyncssh.get_server_host_key(settings.host, settings.port),
            timeout=settings.connect_timeout,
        )
    except (OSError, asyncio.TimeoutError, socket.gaierror, asyncssh.Error) as exc:
        raise errors.device_unreachable(settings.host, settings.port, type(exc).__name__ + ": " + str(exc)) from exc
    if key is None:
        raise errors.device_unreachable(settings.host, settings.port, "aucune clé d'hôte reçue")
    return key


def fingerprint(key: asyncssh.SSHKey) -> str:
    return key.get_fingerprint("sha256")


class DeviceClient:
    def __init__(self, settings: DeviceSettings, credentials: CredentialStore, host_keys: HostKeyStore):
        self.settings = settings
        self.credentials = credentials
        self.host_keys = host_keys

    def _auth_kwargs(self) -> dict:
        s = self.settings
        if s.auth_method == "key":
            if not s.key_path:
                raise errors.AppError("key_path_missing", "Chemin de clé privée non configuré", 409)
            return {"client_keys": [s.key_path], "password": None}
        password = self.credentials.get_password(s.host, s.username)
        if not password:
            raise errors.credentials_missing()
        # client_keys=None : ne pas essayer les clés de ~/.ssh ni l'agent quand on a choisi le mot de passe
        return {"password": password, "client_keys": None, "agent_path": None}

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[asyncssh.SSHClientConnection]:
        s = self.settings
        if not self.host_keys.has_entry(s.host, s.port):
            raise errors.host_key_unknown()
        kwargs = self._auth_kwargs()
        try:
            conn = await asyncssh.connect(
                s.host,
                port=s.port,
                username=s.username,
                known_hosts=str(self.host_keys.path),
                connect_timeout=s.connect_timeout,
                keepalive_interval=15,
                **kwargs,
            )
        except asyncssh.HostKeyNotVerifiable as exc:
            raise errors.host_key_mismatch() from exc
        except asyncssh.PermissionDenied as exc:
            raise errors.auth_failed() from exc
        except OSError as exc:
            from app.device.diagnose import network_error  # diagnose importe ce module

            raise await network_error(s.host, s.port, exc) from exc
        except (asyncio.TimeoutError, asyncssh.ConnectionLost, asyncssh.DisconnectError) as exc:
            raise errors.device_unreachable(s.host, s.port, type(exc).__name__ + ": " + str(exc)) from exc
        try:
            yield conn
        finally:
            conn.close()
            try:
                await asyncio.wait_for(conn.wait_closed(), timeout=3)
            except asyncio.TimeoutError:
                pass

    @asynccontextmanager
    async def sftp(self) -> AsyncIterator[tuple[asyncssh.SSHClientConnection, asyncssh.SFTPClient]]:
        async with self.connect() as conn:
            try:
                client = await conn.start_sftp_client()
            except (asyncssh.ChannelOpenError, asyncssh.SFTPError, asyncssh.ProcessError, OSError) as exc:
                raise errors.sftp_unavailable(type(exc).__name__ + ": " + str(exc)) from exc
            try:
                yield conn, client
            finally:
                client.exit()
