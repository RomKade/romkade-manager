"""Codes de triche de RetroArch (libretro-database) : paquet téléchargé à la demande, codes d'un jeu, copie du
fichier choisi sur la console. Voir app/services/cheats.py."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import errors
from app.device.ssh_client import DeviceClient
from app.services import catalog_query as cq
from app.services import cheats as ch
from app.services.classify import stem_of

router = APIRouter(prefix="/api", tags=["cheats"])

MAX_INSTALL_BYTES = 90 * 1024  # écrit en une commande (base64) : au-delà, la ligne de commande devient trop longue


class CheatsStatusOut(BaseModel):
    available: bool
    files: int
    updated_at: datetime | None
    size: int
    license: str
    source_url: str


class CheatOut(BaseModel):
    desc: str
    code: str


class CheatFileOut(BaseModel):
    name: str  # chemin dans le paquet : « système/nom.cht »
    label: str  # étiquettes : « USA », « World · Game Genie »…
    system: str
    count: int
    cheats: list[CheatOut]


class GameCheatsOut(BaseModel):
    available: bool  # paquet téléchargé
    files: list[CheatFileOut]
    can_install: bool  # le système de la console a RetroArch (dossier des codes connu)
    license: str
    source_url: str


class InstallIn(BaseModel):
    name: str = Field(min_length=5, max_length=400)


class InstallOut(BaseModel):
    path: str


@router.get("/cheats", response_model=CheatsStatusOut)
async def cheats_status() -> dict:
    return await asyncio.to_thread(ch.status)


@router.post("/cheats/download", response_model=CheatsStatusOut)
async def cheats_download() -> dict:
    """Télécharge ou met à jour le paquet des codes de triche de RetroArch (environ 37 Mo)."""
    return await ch.download()


@router.get("/games/{game_id}/cheats", response_model=GameCheatsOut)
async def game_cheats(game_id: int, request: Request) -> dict:
    def read():
        with request.app.state.sessions() as s:
            f = cq.get_file(s, game_id)
            return f.platform.directory, f.filename

    directory, filename = await asyncio.to_thread(read)
    files = await asyncio.to_thread(ch.for_game, directory, filename)
    return {"available": ch.index() is not None, "files": files,
            "can_install": request.app.state.system.profile().ra_config is not None,
            "license": ch.LICENSE, "source_url": ch.SOURCE_URL}


@router.post("/games/{game_id}/cheats/install", response_model=InstallOut)
async def install_cheats(game_id: int, body: InstallIn, request: Request) -> dict:
    """Copie le fichier de codes choisi dans le dossier des codes de RetroArch, sous le nom du jeu."""
    st = request.app.state
    profile = st.system.profile()
    if not profile.ra_config:
        raise errors.AppError("cheats_unsupported", f"{profile.label} n'utilise pas RetroArch : copie impossible.", 409)

    def read():
        with st.sessions() as s:
            f = cq.get_file(s, game_id)
            return f.platform.directory, f.filename

    directory, filename = await asyncio.to_thread(read)
    idx = ch.index()
    if idx is None or body.name not in idx.files_for(directory, filename):
        raise errors.AppError("cheats_not_found", "Ce fichier de codes ne correspond pas à ce jeu.", 404)
    data = (await asyncio.to_thread(ch.read, body.name)).encode()
    if len(data) > MAX_INSTALL_BYTES:
        raise errors.AppError("cheats_too_big", "Ce fichier de codes est trop gros pour être copié d'ici.", 422)
    command = ch.install_command(profile.ra_config, body.name.split("/", 1)[0], stem_of(filename), data)
    client = DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)
    code, out = await st.device_runner(client, command, 20)
    line = next((x for x in out.splitlines() if x.startswith("OK:")), None)
    if code != 0 or line is None:
        raise errors.AppError("cheats_install_failed", "La copie du fichier de codes sur la console a échoué.", 502,
                              {"output": out[-300:]})
    return {"path": line[3:]}
