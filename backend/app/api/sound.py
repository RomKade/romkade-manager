"""Son des jeux : haut-parleurs de la console, TV (HDMI) ou enceinte Bluetooth."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import errors
from app.api.bluetooth import BtDeviceOut
from app.device import sound
from app.device.ssh_client import DeviceClient

router = APIRouter(prefix="/api/sound", tags=["sound"])

Output = Literal["speakers", "tv", "bluetooth"]


class SoundOut(BaseModel):
    output: Output
    address: str | None  # enceinte choisie (output = bluetooth)
    hdmi: bool  # câble HDMI branché : la console est sur une TV
    devices: list[BtDeviceOut]  # enceintes et casques Bluetooth déjà appairés (page Bluetooth)


class OutputIn(BaseModel):
    output: Output
    address: str | None = None


class OutputTestOut(BaseModel):
    result: Literal["played", "in_use", "menu"]  # in_use : un jeu s'en sert déjà ; menu : le menu de la console la garde


def _ctx(request: Request) -> tuple:
    st = request.app.state
    p = st.system.profile()
    if not p.capabilities()["bluetooth_audio"]:
        raise errors.AppError("sound_unsupported", f"Le choix de la sortie du son n'est pas pris en charge sur {p.label}.",
                              409, {"system": p.id})
    return st.device_runner, DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)


@router.get("", response_model=SoundOut)
async def sound_status(request: Request) -> dict:
    return await sound.status(*_ctx(request))


@router.put("", response_model=SoundOut)
async def sound_set(body: OutputIn, request: Request) -> dict:
    """Sortie du son des jeux lancés depuis Game Manager, à partir du prochain jeu lancé. Une enceinte Bluetooth
    appairée mais pas connectée est d'abord connectée."""
    return await sound.set_output(*_ctx(request), body.output, body.address)


@router.post("/test", response_model=OutputTestOut)
async def sound_test(body: OutputIn, request: Request) -> dict:
    """Test sonore : un court carillon sur la sortie, pour vérifier que le son y arrive."""
    return {"result": await sound.sound_test(*_ctx(request), body.output, body.address)}
