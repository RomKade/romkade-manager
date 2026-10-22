"""Relier la console à ROMKADE Cloud (ChatGPT, Claude…) depuis le Manager : voir services/cloud_agent.py.

Le jeton de session ROMKADE (Supabase) est passé par l'interface dans l'en-tête X-Romkade-Token : le Manager ne le
garde pas, il le transmet seulement au cloud pour enregistrer la console sur le compte de l'utilisateur.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import errors
from app.device.ssh_client import DeviceClient
from app.services import cloud_agent

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


def _client(request: Request) -> DeviceClient:
    st = request.app.state
    return DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)


def _token(request: Request) -> str:
    token = request.headers.get("x-romkade-token", "").strip()
    if not token:
        raise errors.AppError("cloud_unauthorized", "Connexion ROMKADE requise.", 401)
    return token


class LinkIn(BaseModel):
    name: str | None = None


@router.get("/agent")
async def agent_status(request: Request) -> dict:
    """Agent ROMKADE installé sur la console, et vers quel cloud (jamais le secret)."""
    client = _client(request)
    profile = await request.app.state.system.ensure()
    async with request.app.state.pool.session(client) as (_conn, sftp):
        config = await cloud_agent.read_agent(sftp, client.settings.roms_root)
        version = await cloud_agent.read_version(sftp, client.settings.roms_root) if config else None
    return {"supported": profile.id in cloud_agent.SUPPORTED, "installed": bool(config and config.get("secret")),
            "server": (config or {}).get("server"), "cloud": cloud_agent.CLOUD_URL,
            "version": version, "latest": cloud_agent.manager_version()}


@router.post("/link")
async def link(request: Request, body: LinkIn | None = None) -> dict:
    """Relie la console au compte ROMKADE connecté : enregistrement dans le cloud, puis installation de l'agent."""
    token = _token(request)
    client = _client(request)
    profile = await request.app.state.system.ensure()
    if profile.id not in cloud_agent.SUPPORTED:
        raise errors.AppError("cloud_unsupported", f"La liaison au cloud n'est pas encore possible sur {profile.label}.", 409,
                              {"system": profile.id})
    roms_root = client.settings.roms_root
    async with request.app.state.pool.session(client) as (_conn, sftp):
        current = await cloud_agent.read_agent(sftp, roms_root)
    _, model = await request.app.state.device_runner(client, "head -1 /mnt/vendor/oem/board.ini 2>/dev/null")
    info = {"model": model.strip() or None, "firmware": profile.label, "profile": profile.id, "roms_root": roms_root}
    secret = (current or {}).get("secret") if (current or {}).get("server", "").rstrip("/") == cloud_agent.CLOUD_URL else None
    reply = await cloud_agent.register(token, (body.name if body else None), info, secret)
    async with request.app.state.pool.session(client) as (_conn, sftp):
        shown = await cloud_agent.install(request.app.state.device_runner, client, sftp, roms_root, reply["server"],
                                          reply["secret"], splash="updated" if secret else "installed")
    return {"console": reply["console"], "reused": bool(reply.get("reused")), "splash": shown}


@router.delete("/agent")
async def unlink(request: Request) -> dict:
    """Arrête l'agent et efface son secret : la console n'est plus pilotable depuis le cloud."""
    client = _client(request)
    await cloud_agent.uninstall(request.app.state.device_runner, client, client.settings.roms_root)
    return {"installed": False}
