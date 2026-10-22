"""Le Manager sur le téléphone : QR code d'association, téléphones associés, déconnexion (app.services.phone)."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import errors

router = APIRouter(prefix="/api/phone", tags=["phone"])


class PairOut(BaseModel):
    url: str
    qr: str  # image SVG (data URI)
    expires_in: int
    devices: int


class StatusOut(BaseModel):
    devices: int
    listening: bool
    available: bool


def _from_computer(request: Request) -> None:
    """Associer ou déconnecter : depuis l'ordinateur seulement, pas depuis un téléphone déjà associé."""
    if request.scope.get("romkade_phone"):
        raise errors.AppError("phone_forbidden", "À faire depuis l'ordinateur.", 403)


@router.get("", response_model=StatusOut)
async def phone_status(request: Request) -> dict:
    return request.app.state.phone.status()


@router.post("/pair", response_model=PairOut)
async def phone_pair(request: Request) -> dict:
    _from_computer(request)
    port = (request.scope.get("server") or ("", 8765))[1] or 8765
    return await request.app.state.phone.pair(port)


@router.delete("", response_model=StatusOut)
async def phone_disconnect(request: Request) -> dict:
    _from_computer(request)
    await request.app.state.phone.disconnect()
    return request.app.state.phone.status()
