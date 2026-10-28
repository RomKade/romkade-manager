"""Manettes de l'ordinateur lues par le Manager (app.services.pc_pads) : liste, relais vers la console, arrêt."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import errors

router = APIRouter(prefix="/api/pc-pads", tags=["gamepad"])


class PadOut(BaseModel):
    id: int
    name: str
    relayed: bool


class RelayOut(BaseModel):
    token: str
    pad: int
    name: str
    status: str
    error: str | None = None


class PcPadsOut(BaseModel):
    available: bool  # faux : pas de pygame-ce, ou Docker → l'interface lit les manettes par le navigateur
    reason: str | None = None
    pads: list[PadOut]
    relays: list[RelayOut]


class RelayIn(BaseModel):
    pad: int


def _check(request: Request) -> None:
    p = request.app.state.system.profile()
    if not p.capabilities()["players"]:
        raise errors.AppError("gamepad_unsupported", f"La manette de l'ordinateur n'est pas prise en charge sur {p.label}.",
                              409, {"system": p.id})


@router.get("", response_model=PcPadsOut)
async def pc_pads(request: Request) -> dict:
    pads = request.app.state.pc_pads
    await pads.ensure_started()
    return pads.snapshot()


@router.post("/relays", response_model=RelayOut, status_code=201)
async def start_relay(body: RelayIn, request: Request) -> dict:
    _check(request)
    r = await request.app.state.pc_pads.start_relay(body.pad)
    return {"token": r.token, "pad": r.pad, "name": r.name, "status": r.status, "error": r.error}


@router.delete("/relays/{token}", status_code=204)
async def stop_relay(token: str, request: Request) -> None:
    await request.app.state.pc_pads.stop_relay(token)
