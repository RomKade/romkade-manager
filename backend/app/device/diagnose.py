"""Diagnostic de la connexion à la console, étape par étape (page Paramètres).

Chaque étape dit ce qui a été vérifié, combien de temps elle a pris et, en cas d'échec, quoi faire. Les étapes
suivantes un échec sont « skipped ». Lecture seule : rien n'est écrit sur la console.

Cas propre au Mac : macOS (« Réseau local », Réglages > Confidentialité et sécurité) peut interdire à
l'application qui a lancé le serveur (Terminal, iTerm, VS Code…) de joindre les appareils du réseau local. La
connexion échoue alors avec « No route to host » (EHOSTUNREACH) alors que la console répond au ping (`ping`,
programme du système, n'est pas concerné). C'est aussi ce que renvoie une console vraiment éteinte : le ping
départage les deux.
"""

import asyncio
import errno
import sys
import time
from collections.abc import Awaitable, Callable

import asyncssh

from app import errors
from app.config import DeviceSettings
from app.credentials import CredentialStore
from app.device.remote_fs import ReadOnlyRemoteFS
from app.device.ssh_client import DeviceClient, HostKeyStore, fingerprint
from app.services import inventory

STEPS = ("network", "ssh", "host_key", "auth", "command", "roms")


async def ping(host: str, timeout: int = 2) -> bool:
    """La console répond-elle au ping ? (programme du système : pas soumis à l'autorisation « Réseau local »)."""
    flag = "-t" if sys.platform == "darwin" else "-W"
    try:
        proc = await asyncio.create_subprocess_exec("ping", "-c", "1", flag, str(timeout), host,
                                                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        return await asyncio.wait_for(proc.wait(), timeout + 2) == 0
    except (OSError, asyncio.TimeoutError):
        return False


async def network_error(host: str, port: int, exc: BaseException) -> errors.AppError:
    """Erreur réseau -> code précis : réseau local bloqué par macOS, connexion refusée, console injoignable."""
    reason = f"{type(exc).__name__}: {exc}"
    code = getattr(exc, "errno", None)
    if code == errno.EHOSTUNREACH and sys.platform == "darwin" and await ping(host):
        return errors.AppError("local_network_blocked", "macOS bloque l'accès au réseau local pour le serveur "
                               "Game Manager : la console répond au ping, mais pas aux connexions du serveur.",
                               503, {"reason": reason, "host": host})
    if code == errno.ECONNREFUSED:
        return errors.AppError("device_ssh_refused", f"La console {host} répond mais refuse la connexion sur le "
                               f"port {port} : SSH n'est pas activé.", 503, {"reason": reason})
    return errors.device_unreachable(host, port, reason)


def _step(id_: str, status: str, ms: float | None = None, detail: str | None = None,
          error: errors.AppError | None = None) -> dict:
    out = {"id": id_, "status": status, "ms": round(ms, 1) if ms is not None else None, "detail": detail,
           "code": None, "message": None}
    if error:
        out.update(code=error.code, message=error.message)
    return out


async def diagnose(settings: DeviceSettings, credentials: CredentialStore, host_keys: HostKeyStore) -> dict:
    s = settings
    if not s.host:
        raise errors.console_not_configured()
    steps: list[dict] = []
    failed = False

    async def run(id_: str, check: Callable[[], Awaitable[str | None]]) -> None:
        nonlocal failed
        if failed:
            steps.append(_step(id_, "skipped"))
            return
        t0 = time.perf_counter()
        try:
            detail = await check()
            steps.append(_step(id_, "ok", (time.perf_counter() - t0) * 1000, detail))
        except errors.AppError as exc:
            failed = True
            steps.append(_step(id_, "failed", (time.perf_counter() - t0) * 1000, error=exc))

    async def network() -> str:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(s.host, s.port), s.connect_timeout)
        except asyncio.TimeoutError as exc:
            raise errors.device_unreachable(s.host, s.port, f"pas de réponse en {s.connect_timeout:.0f} s") from exc
        except OSError as exc:
            raise await network_error(s.host, s.port, exc) from exc
        writer.close()
        return f"{s.host}:{s.port}"

    async def ssh() -> str:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(s.host, s.port), s.connect_timeout)
            banner = (await asyncio.wait_for(reader.readline(), s.connect_timeout)).decode(errors="replace").strip()
            writer.close()
        except (OSError, asyncio.TimeoutError) as exc:
            raise errors.device_unreachable(s.host, s.port, f"{type(exc).__name__}: {exc}") from exc
        if not banner.startswith("SSH-"):
            raise errors.AppError("device_not_ssh", f"Le port {s.port} ne répond pas en SSH.", 502, {"banner": banner[:80]})
        return banner

    async def host_key() -> str:
        if not host_keys.has_entry(s.host, s.port):
            raise errors.host_key_unknown()
        try:
            key = await asyncio.wait_for(asyncssh.get_server_host_key(s.host, s.port), s.connect_timeout)
        except (OSError, asyncio.TimeoutError, asyncssh.Error) as exc:
            raise errors.device_unreachable(s.host, s.port, f"{type(exc).__name__}: {exc}") from exc
        if key is None or not host_keys.matches(s.host, s.port, key):
            raise errors.host_key_mismatch()
        return fingerprint(key)

    client = DeviceClient(s, credentials, host_keys)

    async def auth() -> str:
        async with client.connect():
            return f"{s.username}@{s.host}"

    async def command() -> str:
        async with client.connect() as conn:
            r = await conn.run("head -n 1 /mnt/vendor/oem/board.ini 2>/dev/null; echo; uname -r", check=False, timeout=10)
        lines = [x.strip() for x in str(r.stdout or "").splitlines() if x.strip()]
        return " · ".join(lines) or "ok"

    async def roms() -> str:
        async with client.sftp() as (conn, sftp):
            fs = ReadOnlyRemoteFS(conn, sftp, s.roms_root)
            if not await fs.root_exists():
                raise errors.AppError("remote_not_found", f"Dossier des ROMs introuvable : {s.roms_root}", 404,
                                      {"path": s.roms_root})
            count = len(await inventory.list_platforms(fs))
        return f"{s.roms_root} · {count}"

    for id_, check in zip(STEPS, (network, ssh, host_key, auth, command, roms)):
        await run(id_, check)
    return {"ok": not failed, "host": s.host, "port": s.port, "steps": steps}
