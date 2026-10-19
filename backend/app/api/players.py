"""Joueurs : quelle manette contrôle chaque joueur de RetroArch."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import errors
from app.device import players as pl
from app.device.ssh_client import DeviceClient

router = APIRouter(prefix="/api/players", tags=["players"])


class ControllerOut(BaseModel):
    index: int
    name: str
    builtin: bool
    usb_id: str | None = None  # « vvvv:pppp »


class PlayersOut(BaseModel):
    controllers: list[ControllerOut]
    players: list[int | None]
    directions: list[int | None]  # ce qui dirige chaque joueur : 0 croix seule, 1 + stick gauche, 2 + stick droit
    applied: bool
    game_running: bool


class PlayersIn(BaseModel):
    players: list[int] | None = None
    directions: list[int] | None = None


def _ctx(request: Request) -> tuple:
    st = request.app.state
    p = st.system.profile()
    if not p.capabilities()["players"]:
        raise errors.AppError("players_unsupported", f"Le choix des manettes n'est pas pris en charge sur {p.label}.",
                              409, {"system": p.id})
    return st.device_runner, DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)


@router.get("", response_model=PlayersOut)
async def players_status(request: Request) -> dict:
    return await pl.status(*_ctx(request))


@router.put("", response_model=PlayersOut)
async def players_set(body: PlayersIn, request: Request) -> dict:
    """Manette de chaque joueur (numéros de RetroArch, joueur 1 en premier) et/ou ce qui le dirige (croix seule ou
    croix + un stick) ; ce qui n'est pas donné ne change pas. Appliqué tout de suite si aucun jeu ne tourne, sinon
    au prochain jeu lancé depuis Game Manager."""
    return await pl.set_players(*_ctx(request), body.players, body.directions)
