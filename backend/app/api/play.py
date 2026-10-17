"""Jouer : lancer un jeu du catalogue sur la console, voir ce qui tourne, le quitter."""

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import errors
from app.catalog_schemas import GameOut
from app.db.models import Platform, RemoteFile
from app.device import launcher
from app.device.paths import safe_join
from app.device.ssh_client import DeviceClient
from app.services import catalog_query as cq

router = APIRouter(prefix="/api", tags=["play"])


class NowPlayingOut(BaseModel):
    playing: bool
    process: str | None
    rom_path: str | None
    menu: bool
    game: GameOut | None = None


def _client(request: Request) -> DeviceClient:
    st = request.app.state
    return DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)


class LaunchIn(BaseModel):
    slot: str | None = None  # « auto » ou numéro d'emplacement de sauvegarde instantanée


@router.post("/games/{game_id}/launch", status_code=202)
async def launch_game(game_id: int, request: Request, body: LaunchIn | None = None) -> dict:
    """Ferme le menu (ou le jeu en cours) et lance ce jeu sur la console. Le menu revient à la sortie du jeu.
    Avec `slot`, le jeu reprend sur cette sauvegarde instantanée."""
    root = request.app.state.settings_store.load().roms_root

    def lookup():
        with request.app.state.sessions() as s:
            f = cq.get_file(s, game_id)
            if f.role != "candidate" or f.platform.kind in cq.GAME_KINDS_EXCLUDED:
                raise errors.AppError("not_launchable", "Ce fichier ne se lance pas comme un jeu", 409)
            if f.deleted_at is not None:
                raise errors.AppError("not_on_card", "Ce jeu n'est plus sur la carte", 409)
            return f.platform.directory, safe_join(root, f.platform.directory, f.relative_path)

    platform_dir, rom = await asyncio.to_thread(lookup)
    slot = body.slot if body else None
    profile = await request.app.state.system.ensure()
    await launcher.launch(request.app.state.device_runner, _client(request), platform_dir, rom, slot, profile)
    request.app.state.tracker.invalidate()
    return {"status": "launching", "rom_path": rom, "slot": slot}


@router.get("/device/now-playing", response_model=NowPlayingOut)
async def now_playing(request: Request) -> NowPlayingOut:
    # Le suivi du temps de jeu interroge déjà la console : on réutilise son dernier état s'il est récent.
    tracker = request.app.state.tracker
    st = tracker.fresh_status() or await tracker.poll_once()
    if st is None:
        st = await launcher.status(request.app.state.device_runner, _client(request),
                                   await request.app.state.system.ensure())
    out = NowPlayingOut(**st)
    if st["rom_path"]:
        root = request.app.state.settings_store.load().roms_root.rstrip("/") + "/"

        def find():
            if not st["rom_path"].startswith(root):
                return None
            directory, _, rel = st["rom_path"][len(root):].partition("/")
            with request.app.state.sessions() as s:
                f = s.scalar(select(RemoteFile).join(Platform).options(joinedload(RemoteFile.platform))
                             .where(Platform.directory == directory, RemoteFile.relative_path == rel))
                return cq.to_game(f) if f else None

        out.game = await asyncio.to_thread(find)
    return out


@router.post("/device/quit-game")
async def quit_game(request: Request) -> dict:
    """Quitte le jeu RetroArch en cours (sauvegarde automatique comprise) ; le menu revient."""
    result = await launcher.quit_game(request.app.state.device_runner, _client(request),
                                      await request.app.state.system.ensure())
    request.app.state.tracker.invalidate()
    return {"result": result}
