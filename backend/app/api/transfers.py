"""Routes des transferts Mac -> console.

1. PUT  /api/uploads?filename=…    le navigateur envoie le fichier au serveur local (zone d'attente)
2. POST /api/transfers/plan         destination, conflits, format, espace : rien n'est écrit
3. POST /api/transfers              lance la copie (plan revérifié côté serveur)
4. GET  /api/transfers/events       progression en direct (Server-Sent Events)
"""

import asyncio
import json
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import errors
from app.db.models import Device, Transfer
from app.device.remote_writer import RemoteWriter
from app.device.ssh_client import DeviceClient
from app.services.transfer_plan import Plan, build_plan
from app.services.transfers import ACTIVE

router = APIRouter(prefix="/api")


# ---------- schémas ----------

class UploadOut(BaseModel):
    id: str
    filename: str
    size: int
    sha256: str
    received_at: str


class PlanRequestItem(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    platform: str | None = Field(None, max_length=100)


class PlanRequest(BaseModel):
    items: list[PlanRequestItem] = Field(min_length=1, max_length=500)


class PlanItemOut(BaseModel):
    upload_id: str
    filename: str
    size: int
    platform: str | None
    platform_label: str | None
    platform_choices: list[str]
    conflict: dict | None
    warnings: list[dict]
    error: dict | None


class PlanOut(BaseModel):
    items: list[PlanItemOut]
    total_bytes: int
    free_bytes: int | None
    margin_bytes: int
    fits: bool | None
    ready: bool = Field(description="Vrai si le lot peut être lancé tel quel (aucune erreur bloquante, espace suffisant)")


class StartItem(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    platform: str = Field(min_length=1, max_length=100)
    on_conflict: Literal["skip", "overwrite", "rename"] = "skip"


class StartRequest(BaseModel):
    items: list[StartItem] = Field(min_length=1, max_length=500)
    confirm_overwrite: bool = Field(False, description="Obligatoire si au moins un fichier remplace un fichier existant")


class TransferOut(BaseModel):
    id: int
    batch_id: str
    upload_id: str
    filename: str
    final_filename: str | None
    platform_dir: str
    size: int
    on_conflict: str
    status: Literal["queued", "running", "verifying", "completed", "skipped", "failed", "cancelled", "interrupted"]
    bytes_done: int
    speed_bps: float | None
    eta_seconds: float | None
    verify_method: str | None
    remote_path: str | None
    backup_path: str | None
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    retryable: bool


# ---------- utilitaires ----------

def _client(request: Request) -> DeviceClient:
    st = request.app.state
    return DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)


def _out(request: Request, t: Transfer) -> TransferOut:
    live = request.app.state.transfers.live.get(t.id)
    done = live.bytes_done if live and t.status == "running" else t.bytes_done
    speed = live.speed_bps if live and t.status == "running" and live.speed_bps else None
    eta = (t.size - done) / speed if speed else None
    staged = (request.app.state.staging.root / t.upload_id / "data").exists()
    return TransferOut(
        id=t.id, batch_id=t.batch_id, upload_id=t.upload_id, filename=t.filename, final_filename=t.final_filename, platform_dir=t.platform_dir,
        size=t.size, on_conflict=t.on_conflict, status=t.status, bytes_done=done, speed_bps=speed, eta_seconds=eta,
        verify_method=t.verify_method, remote_path=t.remote_path, backup_path=t.backup_path, error=t.error,
        created_at=t.created_at.isoformat(), started_at=t.started_at.isoformat() if t.started_at else None,
        finished_at=t.finished_at.isoformat() if t.finished_at else None,
        retryable=staged and t.status in ("failed", "cancelled", "interrupted"),
    )


def _plan_out(plan: Plan) -> PlanOut:
    items = [PlanItemOut(**{k: v for k, v in asdict(i).items()}) for i in plan.items]
    return PlanOut(items=items, total_bytes=plan.total_bytes, free_bytes=plan.free_bytes, margin_bytes=plan.margin_bytes,
                   fits=plan.fits, ready=plan.fits is True and not any(i.error for i in plan.items))


async def _plan(request: Request, reqs: list[tuple[str, str | None]]) -> Plan:
    st = request.app.state
    client = _client(request)
    async with client.sftp() as (conn, sftp):
        writer = RemoteWriter(conn, sftp, client.settings.roms_root)
        with st.sessions() as s:
            dev = s.get(Device, 1)
            return await build_plan(writer, s, st.staging, reqs, dev.total_bytes if dev else None)


# ---------- zone d'attente ----------

@router.put("/uploads", response_model=UploadOut, tags=["transfers"])
async def upload(request: Request, filename: str = Query(min_length=1, max_length=255)) -> UploadOut:
    """Reçoit le contenu brut d'un fichier (corps de la requête) et le place en zone d'attente sur le Mac."""
    up = await request.app.state.staging.receive(filename, request.stream())
    return UploadOut(**up.public())


@router.get("/uploads", response_model=list[UploadOut], tags=["transfers"])
def list_uploads(request: Request) -> list[UploadOut]:
    return [UploadOut(**u.public()) for u in request.app.state.staging.list()]


@router.delete("/uploads/{upload_id}", status_code=204, tags=["transfers"])
def delete_upload(upload_id: str, request: Request) -> None:
    """Retire un fichier de la zone d'attente du Mac. Ne touche pas à la console."""
    with request.app.state.sessions() as s:
        busy = s.query(Transfer).filter(Transfer.upload_id == upload_id, Transfer.status.in_(ACTIVE)).count()
    if busy:
        raise errors.AppError("upload_in_use", "Ce fichier est en cours de transfert", 409)
    request.app.state.staging.delete(upload_id)


# ---------- plan et lancement ----------

@router.post("/transfers/plan", response_model=PlanOut, tags=["transfers"])
async def plan(body: PlanRequest, request: Request) -> PlanOut:
    """Calcule le plan sans rien écrire : destination proposée, homonymes, format, titre déjà présent, espace."""
    return _plan_out(await _plan(request, [(i.upload_id, i.platform) for i in body.items]))


@router.post("/transfers", response_model=list[TransferOut], status_code=202, tags=["transfers"])
async def start(body: StartRequest, request: Request) -> list[TransferOut]:
    p = await _plan(request, [(i.upload_id, i.platform) for i in body.items])
    out = _plan_out(p)
    if not out.ready:
        raise errors.AppError("plan_not_ready", "Le lot ne peut pas être lancé : corrige les erreurs signalées", 409,
                              {"plan": out.model_dump()})
    choice = {i.upload_id: i.on_conflict for i in body.items}
    overwrites = [i.filename for i in p.items if i.conflict and choice[i.upload_id] == "overwrite"]
    if overwrites and not body.confirm_overwrite:
        raise errors.AppError("overwrite_not_confirmed", "Le remplacement de fichiers existants doit être confirmé", 409,
                              {"files": overwrites})
    ids = await request.app.state.transfers.enqueue(
        [{"upload_id": i.upload_id, "platform": i.platform, "on_conflict": i.on_conflict} for i in body.items])
    with request.app.state.sessions() as s:
        return [_out(request, s.get(Transfer, tid)) for tid in ids]


@router.get("/transfers", response_model=list[TransferOut], tags=["transfers"])
def list_transfers(request: Request, limit: int = Query(50, ge=1, le=500)) -> list[TransferOut]:
    """Transferts actifs d'abord, puis les plus récents."""
    with request.app.state.sessions() as s:
        return [_out(request, t) for t in request.app.state.transfers.list_rows(s, limit)]


@router.get("/transfers/events", tags=["transfers"])
async def events(request: Request) -> StreamingResponse:
    """Flux d'événements : la liste des transferts actifs, deux fois par seconde tant qu'il y en a."""
    async def gen():
        last = None
        while not await request.is_disconnected():
            with request.app.state.sessions() as s:
                active = [_out(request, t).model_dump() for t in
                          s.query(Transfer).filter(Transfer.status.in_(ACTIVE)).order_by(Transfer.id)]
                # Change dès qu'un transfert se termine, même s'il a été trop rapide pour être vu « en cours ».
                finished = s.query(Transfer).filter(Transfer.status.not_in(ACTIVE)).count()
            payload = json.dumps({"active": active, "finished": finished})
            if payload != last:
                yield f"event: transfers\ndata: {payload}\n\n"
                last = payload
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5 if active else 1)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/transfers/{transfer_id}", response_model=TransferOut, tags=["transfers"])
def get_transfer(transfer_id: int, request: Request) -> TransferOut:
    with request.app.state.sessions() as s:
        t = s.get(Transfer, transfer_id)
        if t is None:
            raise errors.AppError("transfer_not_found", "Transfert introuvable", 404)
        return _out(request, t)


@router.post("/transfers/{transfer_id}/cancel", response_model=TransferOut, tags=["transfers"])
async def cancel(transfer_id: int, request: Request) -> TransferOut:
    await request.app.state.transfers.cancel(transfer_id)
    await asyncio.sleep(0.05)
    with request.app.state.sessions() as s:
        return _out(request, s.get(Transfer, transfer_id))


@router.post("/transfers/{transfer_id}/retry", response_model=list[TransferOut], status_code=202, tags=["transfers"])
async def retry(transfer_id: int, request: Request) -> list[TransferOut]:
    """Relance un transfert échoué, annulé ou interrompu dont le fichier est encore en zone d'attente."""
    with request.app.state.sessions() as s:
        t = s.get(Transfer, transfer_id)
        if t is None:
            raise errors.AppError("transfer_not_found", "Transfert introuvable", 404)
        if not _out(request, t).retryable:
            raise errors.AppError("not_retryable", "Ce transfert ne peut pas être relancé", 409)
        item = StartItem(upload_id=t.upload_id, platform=t.platform_dir,
                         on_conflict="skip" if t.on_conflict == "overwrite" else t.on_conflict)
    return await start(StartRequest(items=[item]), request)
