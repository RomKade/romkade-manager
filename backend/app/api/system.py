"""Système de la console (firmware) : profils connus, détection, fonctions disponibles."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import errors
from app.device import clock
from app.device.ssh_client import DeviceClient
from app.device.systems import PROFILES, profile_out

router = APIRouter(prefix="/api", tags=["system"])


class CapabilitiesOut(BaseModel):
    launch: bool
    resume_slot: bool
    quit: bool
    save_state: bool
    now_playing: bool
    saves: bool
    retroarch_logs: bool
    bluetooth: bool
    bluetooth_audio: bool
    players: bool
    volume: bool
    on_screen_message: bool
    clock: bool
    screenshot: bool = False
    break_screen: bool = False


class SystemProfileOut(BaseModel):
    id: str
    label: str
    status: str
    roms_roots: list[str]
    launcher: str | None
    quit: str
    save_sources: list[str]
    states_in_rom_folder: bool
    bluetooth: str | None
    notes: str
    makers: list[str]
    capabilities: CapabilitiesOut


class DetectedOut(BaseModel):
    profile: str
    label: str
    os_name: str | None
    roms_roots: list[str]
    suggested_roms_root: str | None
    es_http: bool


class DeviceSystemOut(BaseModel):
    chosen: str
    profile: SystemProfileOut
    capabilities: CapabilitiesOut
    detected: DetectedOut | None


@router.get("/systems", response_model=list[SystemProfileOut])
def list_systems() -> list[dict]:
    """Firmwares connus, avec leurs emplacements habituels et ce que Game Manager sait y faire."""
    return [profile_out(p) for p in PROFILES.values()]


@router.get("/device/system", response_model=DeviceSystemOut)
async def device_system(request: Request) -> dict:
    """Profil en vigueur (choisi dans les Paramètres ou détecté) et fonctions disponibles. Détecte une fois par
    SSH (lecture seule) si besoin ; console éteinte : profil choisi, ou celui par défaut."""
    await request.app.state.system.ensure()
    return request.app.state.system.describe()


@router.post("/device/system/detect", response_model=DeviceSystemOut)
async def detect_system(request: Request) -> dict:
    """Relance la détection (quelques `test -d` en lecture seule sur la console)."""
    await request.app.state.system.refresh()
    return request.app.state.system.describe()


class ClockOut(BaseModel):
    console_epoch: int  # heure de la console (secondes UTC)
    timezone: str | None  # fuseau de la console (« Europe/Paris », « Etc/UTC »)
    utc_offset: str | None  # « +0200 »
    mac_epoch: int
    drift_seconds: int  # console - Mac


class ClockSyncIn(BaseModel):
    timezone: str | None = None  # fuseau du Mac (nom IANA), à régler aussi sur la console


def _clock_ctx(request: Request) -> tuple:
    st = request.app.state
    return st.device_runner, DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)


@router.get("/device/clock", response_model=ClockOut)
async def device_clock(request: Request) -> dict:
    """Date et heure de la console, comparées à celles du Mac."""
    return await clock.status(*_clock_ctx(request))


@router.post("/device/clock/sync", response_model=ClockOut)
async def device_clock_sync(body: ClockSyncIn, request: Request) -> dict:
    """Met la console à l'heure du Mac (horloge système et matérielle) et, si donné, au fuseau du Mac."""
    profile = await request.app.state.system.ensure()
    if not profile.capabilities()["clock"]:
        raise errors.AppError("clock_unsupported", f"L'heure de la console ne se règle pas à distance sur "
                              f"{profile.label} : elle suit l'heure du réseau.", 409, {"system": profile.id})
    return await clock.sync(*_clock_ctx(request), body.timezone)
