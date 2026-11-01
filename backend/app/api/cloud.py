"""Relier la console à ROMKADE Cloud (ChatGPT, Claude…) depuis le Manager : voir services/cloud_agent.py.

Le jeton de session ROMKADE (Supabase) est passé par l'interface dans l'en-tête X-Romkade-Token : le Manager ne le
garde pas, il le transmet seulement au cloud pour enregistrer la console sur le compte de l'utilisateur.
"""

import asyncio
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app import errors
from app.api.catalog import _with_session, console_id
from app.catalog_schemas import GameOut
from app.services import catalog_query as cq
from app.device.ssh_client import DeviceClient
from app.services import cloud_agent

router = APIRouter(prefix="/api/cloud", tags=["cloud"])
LIKE_PERIODS = (7, 30, 365)  # jours, comme ROMKADE Cloud


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
        build = await cloud_agent.read_build(sftp, client.settings.roms_root) if config else None
    return {"supported": profile.id in cloud_agent.SUPPORTED, "installed": bool(config and config.get("secret")),
            "server": (config or {}).get("server"), "cloud": cloud_agent.CLOUD_URL,
            "version": version, "latest": cloud_agent.manager_version(),
            "update": bool(config) and build != cloud_agent.build_id()}


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
    await cloud_agent.push_favorites(request.app.state, console_id(request))
    return {"console": reply["console"], "reused": bool(reply.get("reused")), "splash": shown}


@router.delete("/agent")
async def unlink(request: Request) -> dict:
    """Arrête l'agent et efface son secret : la console n'est plus pilotable depuis le cloud."""
    client = _client(request)
    await cloud_agent.uninstall(request.app.state.device_runner, client, client.settings.roms_root)
    return {"installed": False}


@router.put("/likes")
async def share_likes(request: Request) -> dict:
    """Envoie au compte ROMKADE les jeux aimés (favoris) ou non (« Je n'aime pas ») de toutes les consoles, avec
    leur date, pour le classement des plus aimés. L'interface ne l'appelle qu'avec l'accord de l'utilisateur
    (statistiques anonymes)."""
    token = _token(request)
    likes = await asyncio.to_thread(_with_session, request, cq.reactions)
    return {"likes": await cloud_agent.put_likes(token, likes)}


@router.delete("/likes")
async def unshare_likes(request: Request) -> dict:
    """Accord retiré : le cloud oublie les jeux aimés ou non de ce compte."""
    await cloud_agent.delete_likes(_token(request))
    return {"likes": 0}


class TopLikedOut(BaseModel):
    key: str
    title: str
    platform_code: str
    platform_label: str
    platform_dir: str
    likes: int
    dislikes: int
    cover: str
    game: GameOut | None = None  # l'édition de la bibliothèque, si l'utilisateur a ce jeu


@router.get("/likes/top", response_model=list[TopLikedOut])
async def top_liked(request: Request, days: int = Query(30, description="7, 30 ou 365"),
                    limit: int = Query(12, ge=1, le=50)) -> list[TopLikedOut]:
    """Jeux les plus aimés de tous les comptes ROMKADE sur la période, reliés aux jeux de la bibliothèque."""
    if days not in LIKE_PERIODS:
        raise errors.AppError("bad_period", "Période : 7, 30 ou 365 jours.", 422, {"periods": list(LIKE_PERIODS)})
    games = await cloud_agent.top_liked(_token(request), days, limit)
    mine = await asyncio.to_thread(_with_session, request, cq.games_for_keys, [g["key"] for g in games])
    return [TopLikedOut(**g, game=mine.get(g["key"])) for g in games]
