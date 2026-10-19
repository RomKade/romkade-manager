"""Routes santé, réglages et console (accès direct, en lecture seule). Les écritures passent par api/transfers.py."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, Query, Request

from app import errors
from app.config import DeviceSettings
from app.device import diagnose
from app.device.paths import platform_dir_name_ok
from app.device.remote_fs import ReadOnlyRemoteFS, Storage
from app.device.ssh_client import DeviceClient, HostKeyStore, fetch_host_key, fingerprint
from app.schemas import (
    DiagnoseOut,
    ConnectionTestOut, FilesPageOut, HostKeyOut, InventoryOut, Page, PasswordIn,
    PlatformOut, SettingsOut, StorageOut, TrustHostKeyIn,
)
from app.services import inventory

router = APIRouter(prefix="/api")


def _settings(request: Request) -> DeviceSettings:
    return request.app.state.settings_store.load()


def _host_keys(request: Request) -> HostKeyStore:
    return request.app.state.host_keys


def _client(request: Request) -> DeviceClient:
    return DeviceClient(_settings(request), request.app.state.credentials, _host_keys(request))


@asynccontextmanager
async def _fs(request: Request) -> AsyncIterator[ReadOnlyRemoteFS]:
    client = _client(request)
    async with client.sftp() as (conn, sftp):
        fs = ReadOnlyRemoteFS(conn, sftp, client.settings.roms_root)
        if not await fs.root_exists():
            raise errors.remote_not_found(fs.root)
        yield fs


def _storage_out(s: Storage) -> StorageOut:
    pct = round(100 * s.used_bytes / s.total_bytes, 1) if s.total_bytes else 0.0
    return StorageOut(path=s.path, total_bytes=s.total_bytes, free_bytes=s.free_bytes,
                      used_bytes=s.used_bytes, used_percent=pct, method=s.method)


# ---------- santé et réglages ----------

@router.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "read_only": False, "writes": "transfers_only", "version": "0.4.0"}


@router.get("/settings", response_model=SettingsOut, tags=["settings"])
async def get_settings(request: Request) -> SettingsOut:
    s = _settings(request)
    return SettingsOut(
        **s.model_dump(),
        has_password=bool(request.app.state.credentials.get_password(s.host, s.username)),
        host_key_trusted=_host_keys(request).has_entry(s.host, s.port),
    )


@router.put("/settings", response_model=SettingsOut, tags=["settings"])
async def put_settings(body: DeviceSettings, request: Request) -> SettingsOut:
    request.app.state.settings_store.save(body)
    request.app.state.system.detection = None  # autre console ou autre système : détection à refaire
    return await get_settings(request)


@router.put("/settings/password", status_code=204, tags=["settings"])
async def put_password(body: PasswordIn, request: Request) -> None:
    """Enregistre le mot de passe dans le trousseau. Il n'est jamais renvoyé par l'API."""
    s = _settings(request)
    request.app.state.credentials.set_password(s.host, s.username, body.password.get_secret_value())


# ---------- clé d'hôte (TOFU explicite) ----------

@router.get("/device/host-key", response_model=HostKeyOut, tags=["device"])
async def get_host_key(request: Request) -> HostKeyOut:
    s = _settings(request)
    key = await fetch_host_key(s)
    return HostKeyOut(host=s.host, port=s.port, algorithm=key.get_algorithm(),
                      fingerprint=fingerprint(key), trusted=_host_keys(request).has_entry(s.host, s.port))


@router.post("/device/host-key/trust", response_model=HostKeyOut, tags=["device"])
async def trust_host_key(body: TrustHostKeyIn, request: Request) -> HostKeyOut:
    s = _settings(request)
    key = await fetch_host_key(s)
    fp = fingerprint(key)
    if body.fingerprint.strip() != fp:
        raise errors.AppError("fingerprint_mismatch", "L'empreinte fournie ne correspond pas à celle présentée par la console",
                              409, {"presented": fp})
    _host_keys(request).trust(s.host, s.port, key)
    return HostKeyOut(host=s.host, port=s.port, algorithm=key.get_algorithm(), fingerprint=fp, trusted=True)


# ---------- console ----------

@router.post("/device/test-connection", response_model=ConnectionTestOut, tags=["device"])
async def test_connection(request: Request) -> ConnectionTestOut:
    s = _settings(request)
    t0 = time.perf_counter()
    async with _client(request).sftp() as (conn, sftp):
        fs = ReadOnlyRemoteFS(conn, sftp, s.roms_root)
        exists = await fs.root_exists()
        count = len(await inventory.list_platforms(fs)) if exists else None
        storage = None
        if exists:
            try:
                storage = _storage_out(await fs.storage())
            except errors.AppError:
                storage = None
    return ConnectionTestOut(connected=True, host=s.host, port=s.port, username=s.username, sftp=True,
                             roms_root=s.roms_root, roms_root_exists=exists, platform_dir_count=count,
                             storage=storage, latency_ms=round((time.perf_counter() - t0) * 1000, 1))


@router.post("/device/diagnose", response_model=DiagnoseOut, tags=["device"])
async def device_diagnose(request: Request) -> dict:
    """Diagnostic de la connexion étape par étape (réseau, SSH, clé d'hôte, identifiants, commande, ROMs).
    Ne lève pas d'erreur : chaque étape porte son résultat. Lecture seule."""
    st = request.app.state
    return await diagnose.diagnose(_settings(request), st.credentials, _host_keys(request))


@router.get("/device/status", tags=["device"])
async def device_status(request: Request) -> dict:
    """Ne lève pas d'erreur : renvoie l'état et le code d'erreur éventuel."""
    st = request.app.state
    host = st.settings_store.load().host
    try:
        await st.pool.run(_client(request), "true", 10)
        st.presence.seen(host)
        return {"connected": True, "error": None}
    except errors.AppError as exc:
        return {"connected": False, "error": st.presence.explain(exc, host).to_dict()["error"]}


@router.get("/device/storage", response_model=StorageOut, tags=["device"])
async def device_storage(request: Request) -> StorageOut:
    async with _fs(request) as fs:
        return _storage_out(await fs.storage())


# ---------- inventaire en direct (diagnostic ; l'interface utilise le catalogue /api/games) ----------

@router.get("/device/platforms", response_model=list[PlatformOut], tags=["device-live"])
async def live_platforms(request: Request) -> list[PlatformOut]:
    async with _fs(request) as fs:
        return await inventory.list_platforms(fs)


@router.get("/device/inventory", response_model=InventoryOut, tags=["device-live"])
async def full_inventory(
    request: Request,
    include_files: bool = Query(False, description="Inclure la liste des fichiers de chaque plateforme"),
    platform: list[str] | None = Query(None, description="Limiter à ces dossiers"),
) -> InventoryOut:
    if platform:
        for p in platform:
            if not platform_dir_name_ok(p):
                raise errors.path_forbidden(p, "nom de dossier invalide")
    async with _fs(request) as fs:
        return await inventory.scan_all(fs, include_files=include_files, only=set(platform) if platform else None)


@router.get("/device/platforms/{directory}/files", response_model=FilesPageOut, tags=["device-live"])
async def platform_files(
    directory: str,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    role: Literal["candidate", "component", "auxiliary", "program", "all"] = "all",
    q: str | None = Query(None, max_length=100, description="Filtre sur le nom de fichier"),
    sort: Literal["name", "size", "date"] = "name",
    order: Literal["asc", "desc"] = "asc",
) -> FilesPageOut:
    if not platform_dir_name_ok(directory):
        raise errors.path_forbidden(directory, "nom de dossier invalide")
    async with _fs(request) as fs:
        plats = {p.directory: p for p in await inventory.list_platforms(fs)}
        if directory not in plats:
            raise errors.AppError("platform_not_found", "Dossier de plateforme introuvable", 404, {"directory": directory})
        inv = await inventory.scan_platform(fs, plats[directory])
    files = inv.files or []
    if role != "all":
        files = [f for f in files if f.role == role]
    if q:
        ql = q.lower()
        files = [f for f in files if ql in f.filename.lower()]
    key = {"name": lambda f: f.relative_path.lower(), "size": lambda f: f.size or 0,
           "date": lambda f: f.modified_at.timestamp() if f.modified_at else 0}[sort]
    files.sort(key=key, reverse=order == "desc")
    return FilesPageOut(platform=inv.model_copy(update={"files": None}),
                        page=Page(total=len(files), offset=offset, limit=limit),
                        files=files[offset:offset + limit])
