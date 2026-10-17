"""Bluetooth de la console : manettes, enceintes, casques."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import errors
from app.device import bluetooth as bt
from app.device.ssh_client import DeviceClient

router = APIRouter(prefix="/api/bluetooth", tags=["bluetooth"])


class BtDeviceOut(BaseModel):
    address: str
    name: str
    icon: str
    kind: str
    paired: bool
    trusted: bool
    connected: bool
    rssi: int | None


class BtAdapterOut(BaseModel):
    present: bool
    powered: bool = False
    discovering: bool = False
    name: str | None = None


class BtStatusOut(BaseModel):
    adapter: BtAdapterOut
    devices: list[BtDeviceOut]
    bluealsa: bool
    audio_output: str | None


class AddressIn(BaseModel):
    address: str


class AudioIn(BaseModel):
    address: str | None


def _ctx(request: Request, audio: bool = False) -> tuple:
    st = request.app.state
    p = st.system.profile()
    if p.bluetooth is None or (audio and p.bluetooth != "stock"):
        what = "Le son vers une enceinte" if audio and p.bluetooth else "Le Bluetooth"
        raise errors.AppError("bluetooth_unsupported", f"{what} n'est pas pris en charge sur {p.label}.", 409,
                              {"system": p.id})
    return st.device_runner, DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)


@router.get("", response_model=BtStatusOut)
async def bt_status(request: Request) -> dict:
    return await bt.status(*_ctx(request))


@router.post("/scan", response_model=BtStatusOut)
async def bt_scan(request: Request) -> dict:
    """Recherche les appareils à portée (une douzaine de secondes)."""
    return await bt.scan(*_ctx(request))


@router.post("/connect", response_model=BtStatusOut)
async def bt_connect(body: AddressIn, request: Request) -> dict:
    return await bt.connect(*_ctx(request), body.address)


@router.post("/disconnect", response_model=BtStatusOut)
async def bt_disconnect(body: AddressIn, request: Request) -> dict:
    return await bt.disconnect(*_ctx(request), body.address)


@router.post("/forget", response_model=BtStatusOut)
async def bt_forget(body: AddressIn, request: Request) -> dict:
    return await bt.forget(*_ctx(request), body.address)


@router.post("/audio-output", response_model=BtStatusOut)
async def bt_audio_output(body: AudioIn, request: Request) -> dict:
    """Envoie le son des jeux lancés depuis Game Manager vers une enceinte Bluetooth (address = null : haut-parleurs
    de la console). Vaut à partir du prochain jeu lancé."""
    return await bt.set_audio_output(*_ctx(request, audio=True), body.address)
