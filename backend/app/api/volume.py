"""Volume des jeux (RetroArch) : couper, rétablir, régler, aussi pendant un jeu."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import errors
from app.device import volume as vol
from app.device.ssh_client import DeviceClient

router = APIRouter(prefix="/api/volume", tags=["volume"])


class VolumeOut(BaseModel):
    mode: str  # game_manager | console | retroarch | none (voir app.device.volume.parse_status)
    adjustable: bool  # notre réglage existe : jeu lancé depuis Game Manager (sinon seule la coupure marche)
    percent: int
    muted: bool
    game_running: bool


class VolumeIn(BaseModel):
    percent: int | None = None
    muted: bool | None = None


def _ctx(request: Request) -> tuple:
    st = request.app.state
    p = st.system.profile()
    if not p.capabilities()["volume"]:
        raise errors.AppError("volume_unsupported", f"Le réglage du volume n'est pas pris en charge sur {p.label}.",
                              409, {"system": p.id})
    return st.device_runner, DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)


@router.get("", response_model=VolumeOut)
async def volume_status(request: Request) -> dict:
    return await vol.status(*_ctx(request))


@router.put("", response_model=VolumeOut)
async def volume_set(body: VolumeIn, request: Request) -> dict:
    """`percent` règle le volume (et rétablit le son) ; `muted` coupe ou rétablit le son."""
    return await vol.set_volume(*_ctx(request), body.percent, body.muted)
