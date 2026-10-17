"""Sauvegardes : les lister sur la console, les copier sur le Mac, les restaurer ou les supprimer.

Toute écriture sur la carte est refusée pendant qu'un jeu tourne (il écraserait le fichier en quittant)
et est précédée d'une copie automatique sur le Mac du fichier remplacé ou supprimé.
"""

import asyncio
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import errors
from app.catalog_schemas import BackupOut, GameOut, HotkeyOut, SaveOut, SavesOut
from app.db.models import Platform, RemoteFile
from app.device import launcher
from app.device.remote_fs import ReadOnlyRemoteFS
from app.device.save_writer import SaveWriter
from app.device.ssh_client import DeviceClient
from app.services import catalog_query as cq
from app.services import saves as sv
from app.services.classify import stem_of
from app.platforms import canonical

router = APIRouter(prefix="/api", tags=["saves"])
MAX_SAVE_BYTES = 64 * 1024 * 1024
PAD_CFG = "/mnt/vendor/deep/retro/autoconfig/udev/ANBERNIC-keys.cfg"


def _client(request: Request) -> DeviceClient:
    st = request.app.state
    return DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)


def _roots(request: Request) -> tuple[str, str]:
    roms_root = request.app.state.settings_store.load().roms_root
    return sv.base_dir(roms_root), roms_root


def _where(request: Request) -> dict:
    """Emplacements des sauvegardes du firmware en vigueur (arguments de sv.scan et sv.is_save_path)."""
    p = request.app.state.system.profile()
    return {"sources": p.save_sources, "rom_states": p.states_in_rom_folder}


def _index(request: Request):
    """(dossiers de plateforme, index (CONSOLE, nom) -> jeu) depuis le catalogue."""
    with request.app.state.sessions() as s:
        dirs = [p.directory for p in s.scalars(select(Platform).where(Platform.present,
                                                                      Platform.kind.not_in(cq.GAME_KINDS_EXCLUDED)))]
        idx: dict[tuple[str, str], GameOut] = {}
        for f in s.scalars(select(RemoteFile).join(Platform).options(joinedload(RemoteFile.platform))
                           .where(RemoteFile.role == "candidate", RemoteFile.deleted_at.is_(None))):
            g = cq.to_game(f)
            d = canonical(f.platform.directory)
            idx.setdefault((d, stem_of(f.filename).lower()), g)
            idx.setdefault((d, f.filename.lower()), g)
        return dirs, idx


def _out(f: sv.SaveFile, idx: dict) -> SaveOut:
    game = idx.get((canonical(f.platform), f.stem.lower())) if f.platform else None
    return SaveOut(path=f.path, rel=f.rel, source=f.source, kind=f.kind, slot=f.slot, platform=f.platform,
                   name=f.stem, size=f.size, modified_at=f.mtime, game=game)


async def _scan(request: Request) -> list[SaveOut]:
    base, roms_root = _roots(request)
    dirs, idx = await asyncio.to_thread(_index, request)
    async with request.app.state.pool.session(_client(request)) as (conn, sftp):
        files = await sv.scan(ReadOnlyRemoteFS(conn, sftp, base), base, roms_root, dirs, **_where(request))
    order = {"sram": 0, "state": 1}
    files.sort(key=lambda f: ((f.platform or "~"), f.stem.lower(), order[f.kind], f.slot or ""))
    return [_out(f, idx) for f in files]


@router.get("/saves", response_model=SavesOut)
async def list_saves(request: Request) -> SavesOut:
    """Toutes les sauvegardes de la carte, rattachées à leur jeu quand c'est possible (lecture seule)."""
    return SavesOut(saves=await _scan(request), scanned_at=datetime.now(UTC))


@router.get("/games/{game_id}/saves", response_model=list[SaveOut])
async def game_saves(game_id: int, request: Request) -> list[SaveOut]:
    return [s for s in await _scan(request) if s.game and s.game.id == game_id]


async def _read(request: Request, path: str) -> bytes:
    base, roms_root = _roots(request)
    if not sv.is_save_path(path, base, roms_root, **_where(request)):
        raise errors.path_forbidden(path, "pas un emplacement de sauvegarde")
    async with request.app.state.pool.session(_client(request)) as (conn, sftp):
        return await ReadOnlyRemoteFS(conn, sftp, base).read_file(path, MAX_SAVE_BYTES)


@router.get("/saves/file")
async def download_save(request: Request, path: str = Query(..., max_length=1024)) -> Response:
    data = await _read(request, path)
    name = re.sub(r'["\\\r\n]', "_", path.rsplit("/", 1)[-1])
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_quote(name)}"})


def _quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


class BackupIn(BaseModel):
    paths: list[str] | None = None  # rien : toutes les sauvegardes


async def _snapshot(request: Request, saves: list[SaveOut], auto: bool) -> dict:
    base, _ = _roots(request)
    files = []
    async with request.app.state.pool.session(_client(request)) as (conn, sftp):
        fs = ReadOnlyRemoteFS(conn, sftp, base)
        for s in saves:
            data = await fs.read_file(s.path, MAX_SAVE_BYTES)
            files.append((s.rel, data, {"kind": s.kind, "slot": s.slot, "platform": s.platform,
                                        "game_title": s.game.title if s.game else None,
                                        "modified_at": s.modified_at.isoformat() if s.modified_at else None}))
    return await asyncio.to_thread(request.app.state.save_vault.create, files, auto)


@router.post("/saves/backup", response_model=BackupOut)
async def backup_saves(body: BackupIn, request: Request) -> dict:
    """Copie des sauvegardes (toutes, ou celles demandées) sur le Mac, dans un dossier daté."""
    saves = await _scan(request)
    if body.paths is not None:
        wanted = set(body.paths)
        saves = [s for s in saves if s.path in wanted]
    if not saves:
        raise errors.AppError("no_saves", "Aucune sauvegarde à copier", 404)
    return await _snapshot(request, saves, auto=False)


@router.get("/saves/backups", response_model=list[BackupOut])
def list_backups(request: Request) -> list[dict]:
    return request.app.state.save_vault.list()


@router.get("/saves/backups/{snap_id}/zip")
def backup_zip(snap_id: str, request: Request) -> Response:
    data = request.app.state.save_vault.zip(snap_id)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="sauvegardes-{snap_id}.zip"'})


@router.delete("/saves/backups/{snap_id}", status_code=204)
def delete_backup(snap_id: str, request: Request) -> None:
    request.app.state.save_vault.delete(snap_id)


async def _no_game_running(request: Request) -> None:
    st = await launcher.status(request.app.state.device_runner, _client(request),
                               await request.app.state.system.ensure())
    if st["playing"]:
        raise errors.AppError("game_running", "Un jeu tourne sur la console : quitte-le avant de modifier ses "
                              "sauvegardes (il réécrirait le fichier en sortant).", 409)


class RestoreIn(BaseModel):
    backup_id: str
    rel: str


@router.post("/saves/restore")
async def restore_save(body: RestoreIn, request: Request) -> dict:
    """Remet sur la carte un fichier d'une copie du Mac. Le fichier actuel est d'abord copié sur le Mac."""
    base, roms_root = _roots(request)
    vault = request.app.state.save_vault
    data = await asyncio.to_thread(vault.read, body.backup_id, body.rel)
    target = f"{base}/{vault._safe_rel(body.rel)}"
    if not sv.is_save_path(target, base, roms_root, **_where(request)):
        raise errors.path_forbidden(target, "pas un emplacement de sauvegarde")
    await _no_game_running(request)
    current = [s for s in await _scan(request) if s.path == target]
    safety = await _snapshot(request, current, auto=True) if current else None
    async with request.app.state.pool.session(_client(request)) as (_conn, sftp):
        await SaveWriter(sftp, base, roms_root, **_where(request)).write(target, data)
    return {"restored": target, "previous_copy": safety["id"] if safety else None}


class DeleteIn(BaseModel):
    path: str


@router.post("/saves/delete")
async def delete_save(body: DeleteIn, request: Request) -> dict:
    """Supprime une sauvegarde de la carte, après en avoir gardé une copie sur le Mac."""
    base, roms_root = _roots(request)
    if not sv.is_save_path(body.path, base, roms_root, **_where(request)):
        raise errors.path_forbidden(body.path, "pas un emplacement de sauvegarde")
    await _no_game_running(request)
    current = [s for s in await _scan(request) if s.path == body.path]
    if not current:
        raise errors.remote_not_found(body.path)
    safety = await _snapshot(request, current, auto=True)
    async with request.app.state.pool.session(_client(request)) as (_conn, sftp):
        await SaveWriter(sftp, base, roms_root, **_where(request)).remove(body.path)
    return {"deleted": body.path, "copy": safety["id"]}


@router.post("/device/save-state")
async def save_state_now(request: Request) -> dict:
    """Sauvegarde instantanée du jeu RetroArch en cours, dans son emplacement actuel."""
    run = request.app.state.device_runner
    profile = await request.app.state.system.ensure()
    if not profile.capabilities()["save_state"]:
        raise errors.AppError("save_state_unsupported", f"Sauvegarde à distance impossible sur {profile.label} : "
                              "utilise le raccourci de la console.", 409)
    st = await launcher.status(run, _client(request), profile)
    if not st["playing"] or st["process"] != "retroarch":
        raise errors.AppError("no_retroarch_game", "Aucun jeu RetroArch en cours sur la console", 409)
    await run(_client(request), "{ bash -c 'echo -n SAVE_STATE > /dev/udp/127.0.0.1/55355' || "
                                "printf SAVE_STATE | nc -u -w1 127.0.0.1 55355; } 2>/dev/null")
    return {"result": "saved"}


ACTIONS = {"save_state": "input_save_state_btn", "load_state": "input_load_state_btn",
           "slot_next": "input_state_slot_increase_btn", "slot_prev": "input_state_slot_decrease_btn",
           "quit": "input_exit_emulator_btn", "menu": "input_menu_toggle_btn"}
PAD_NAMES = {"a": "A", "b": "B", "x": "X", "y": "Y", "l": "L1", "r": "R1", "l2": "L2", "r2": "R2", "l3": "L3",
             "r3": "R3", "start": "Start", "select": "Select", "up": "↑", "down": "↓", "left": "←", "right": "→"}
DEFAULT_HOTKEYS = [HotkeyOut(action="save_state", combo=["Menu", "R1"]), HotkeyOut(action="load_state", combo=["Menu", "L1"]),
                   HotkeyOut(action="slot_prev", combo=["Menu", "←"]), HotkeyOut(action="slot_next", combo=["Menu", "→"]),
                   HotkeyOut(action="quit", combo=["Menu", "Start"])]


def parse_cfg(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(r'^\s*([\w]+)\s*=\s*"([^"]*)"', text, re.M)}


def hotkeys(ra_cfg: str, pad_cfg: str) -> list[HotkeyOut]:
    """Raccourcis RetroArch réellement configurés : touche « hotkey » + bouton, en noms de la manette."""
    ra, pad = parse_cfg(ra_cfg), parse_cfg(pad_cfg)
    by_btn = {}
    for key, value in pad.items():
        m = re.fullmatch(r"input_(\w+?)_btn", key)
        if m and m.group(1) in PAD_NAMES:
            by_btn.setdefault(value, PAD_NAMES[m.group(1)])
    def name(btn: str | None) -> str | None:
        if not btn or btn == "nul":
            return None
        return by_btn.get(btn, "Menu" if btn == ra.get("input_enable_hotkey_btn") else f"#{btn}")
    hot = name(ra.get("input_enable_hotkey_btn"))
    out = []
    for action, key in ACTIONS.items():
        b = name(ra.get(key))
        if b:
            out.append(HotkeyOut(action=action, combo=[hot, b] if hot and hot != b else [b]))
    return out or DEFAULT_HOTKEYS


@router.get("/saves/howto", response_model=list[HotkeyOut])
async def howto(request: Request) -> list[HotkeyOut]:
    """Raccourcis de sauvegarde lus dans la configuration RetroArch de la console (lecture seule)."""
    profile = request.app.state.system.profile()
    if not profile.ra_config:
        return DEFAULT_HOTKEYS
    pad = PAD_CFG if profile.id.startswith("anbernic") else "/dev/null"
    code, out = await request.app.state.device_runner(_client(request),
                                                      f"cat {profile.ra_config}; echo '@@PAD@@'; cat {pad}")
    if "@@PAD@@" not in out:
        return DEFAULT_HOTKEYS
    ra, pad = out.split("@@PAD@@", 1)
    return hotkeys(ra, pad)
