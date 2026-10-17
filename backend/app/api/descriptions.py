"""Descriptions des jeux (fr, en, es) par Claude : clé d'API, lancement d'un lot, suivi et import."""

import asyncio
import re

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import errors
from app.services import descriptions as d

router = APIRouter(prefix="/api", tags=["descriptions"])


class AnthropicKeyIn(BaseModel):
    api_key: str


class BatchOut(BaseModel):
    batch_id: str
    created_at: str
    games: int
    status: str  # in_progress | canceling | ended | unknown
    succeeded: int = 0
    errored: int = 0
    processing: int = 0
    imported: bool
    result: dict | None = None


class DescriptionsStatusOut(BaseModel):
    credentials: bool  # clé du trousseau, variable d'environnement ou profil Anthropic
    key_in_keychain: bool
    model: str
    games: int
    complete: int
    pending: int
    estimate_usd: float
    batches: list[BatchOut]


def _status(request: Request) -> dict:
    st = request.app.state
    with st.sessions() as s:
        cov = d.coverage(s)
    batches = []
    client = None
    for entry in reversed(d.load_state()):
        out = {"batch_id": entry["batch_id"], "created_at": entry["created_at"], "games": len(entry["games"]),
               "status": "unknown", "imported": entry.get("imported", False), "result": entry.get("result")}
        if not out["imported"]:
            try:
                client = client or d.make_client(st.credentials)
                b = client.messages.batches.retrieve(entry["batch_id"])
                c = b.request_counts
                out.update(status=b.processing_status, succeeded=c.succeeded, errored=c.errored, processing=c.processing)
                if b.processing_status == "ended":  # lot terminé : on l'importe tout de suite
                    with st.sessions.begin() as s:
                        out["result"] = d.import_results(s, client, entry["batch_id"])
                    out["imported"] = True
                    with st.sessions() as s:
                        cov = d.coverage(s)
            except Exception as exc:  # noqa: BLE001 — réseau, identifiants : l'état reste lisible
                out["status"] = f"unknown: {type(exc).__name__}"
        else:
            out["status"] = "ended"
        batches.append(out)
    pending = cov["games"] - cov["complete"]
    return {"credentials": d.has_credentials(st.credentials),
            "key_in_keychain": bool(st.credentials.get_password(d.KEY_HOST, d.KEY_ACCOUNT)),
            "model": d.MODEL, **cov, "pending": pending, "estimate_usd": round(pending * d.COST_PER_GAME_USD, 2),
            "batches": batches}


@router.get("/descriptions", response_model=DescriptionsStatusOut)
async def descriptions_status(request: Request) -> dict:
    """Jeux décrits dans les trois langues, lots en cours (un lot terminé est importé à cette occasion)."""
    return await asyncio.to_thread(_status, request)


@router.post("/descriptions/start", response_model=DescriptionsStatusOut)
async def descriptions_start(request: Request) -> dict:
    """Soumet un lot pour tous les jeux sans description complète (coût facturé sur le compte Anthropic)."""
    st = request.app.state
    if not d.has_credentials(st.credentials):
        raise errors.AppError("anthropic_key_missing", "Ajoute d'abord une clé d'API Anthropic.", 409)
    if any(not e.get("imported") for e in d.load_state()):
        raise errors.AppError("descriptions_running", "Un lot est déjà en cours : attends qu'il se termine.", 409)

    def run() -> None:
        with st.sessions() as s:
            d.submit(s, d.make_client(st.credentials))

    try:
        await asyncio.to_thread(run)
    except Exception as exc:  # noqa: BLE001
        raise errors.AppError("descriptions_submit_failed", f"Le lot n'a pas pu être soumis : {exc}", 502) from exc
    return await asyncio.to_thread(_status, request)


@router.put("/settings/anthropic", status_code=204)
def put_anthropic_key(body: AnthropicKeyIn, request: Request) -> None:
    key = body.api_key.strip()
    if not re.fullmatch(d.KEY_RE, key):
        raise errors.AppError("anthropic_key_format", "Ce n'est pas une clé d'API Anthropic (elle commence par « sk-ant- »).", 422)
    request.app.state.credentials.set_password(d.KEY_HOST, d.KEY_ACCOUNT, key)


@router.delete("/settings/anthropic", status_code=204)
def delete_anthropic_key(request: Request) -> None:
    request.app.state.credentials.delete_password(d.KEY_HOST, d.KEY_ACCOUNT)
