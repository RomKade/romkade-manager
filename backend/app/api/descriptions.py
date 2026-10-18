"""Descriptions des jeux (fr, en, es) par le LLM configuré (Paramètres > IA) : lancement, suivi et import."""

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import errors
from app.services import descriptions as d
from app.services import llm as llm_mod

router = APIRouter(prefix="/api", tags=["descriptions"])


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
    credentials: bool  # LLM prêt (fournisseur, clé et modèle) : voir GET /api/settings/llm
    problem: str | None  # llm_key_missing, llm_no_model, llm_no_url
    provider: str
    provider_label: str
    model: str | None
    batch: bool  # lot à moitié prix (Claude) ; sinon jeu par jeu
    local: bool  # modèle local : gratuit
    games: int
    complete: int
    pending: int
    estimate_usd: float | None  # Claude seulement (coût observé) ; inconnu pour les autres fournisseurs
    batches: list[BatchOut]


def _status(request: Request) -> dict:
    st = request.app.state
    with st.sessions() as s:
        cov = d.coverage(s)
    batches = []
    client = None
    d.close_interrupted()
    for entry in reversed(d.load_state()):
        out = {"batch_id": entry["batch_id"], "created_at": entry["created_at"], "games": len(entry["games"]),
               "status": "unknown", "imported": entry.get("imported", False), "result": entry.get("result")}
        if d.is_direct(entry):
            c = entry.get("counts", {})
            out.update(status="in_progress" if d.running(entry["batch_id"]) else "ended",
                       succeeded=c.get("done", 0) - c.get("errored", 0), errored=c.get("errored", 0),
                       processing=len(entry["games"]) - c.get("done", 0))
        elif not out["imported"]:
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
    cfg = st.llm_config.load()
    provider = llm_mod.PROVIDERS[cfg.provider]
    try:
        llm = llm_mod.resolve(st)
        ready, problem, model = True, None, llm.model
    except errors.AppError as exc:
        ready, problem, model = False, exc.code, cfg.model or provider.default_model
    return {"credentials": ready, "problem": problem, "provider": provider.id, "provider_label": provider.label,
            "model": model, "batch": provider.batch, "local": provider.kind == "local", **cov, "pending": pending,
            "estimate_usd": round(pending * d.COST_PER_GAME_USD, 2) if provider.batch else None, "batches": batches}


@router.get("/descriptions", response_model=DescriptionsStatusOut)
async def descriptions_status(request: Request) -> dict:
    """Jeux décrits dans les trois langues, lots en cours (un lot terminé est importé à cette occasion)."""
    return await asyncio.to_thread(_status, request)


@router.post("/descriptions/start", response_model=DescriptionsStatusOut)
async def descriptions_start(request: Request) -> dict:
    """Décrit tous les jeux sans description complète : lot Anthropic (facturé sur le compte, moitié prix), ou jeu
    par jeu en arrière-plan avec un autre fournisseur ou un modèle local."""
    st = request.app.state
    llm = llm_mod.resolve(st)  # 409 si la clé, le modèle ou l'adresse manquent
    d.close_interrupted()
    if any(not e.get("imported") for e in d.load_state()):
        raise errors.AppError("descriptions_running", "Une génération est déjà en cours : attends qu'elle se termine.", 409)

    def run() -> None:
        if llm.provider.batch:
            with st.sessions() as s:
                d.submit(s, llm.anthropic_client(), model=llm.model)
        else:
            d.start_direct(st.sessions, llm)

    try:
        await asyncio.to_thread(run)
    except errors.AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise errors.AppError("descriptions_submit_failed", f"La génération n'a pas pu démarrer : {exc}", 502) from exc
    return await asyncio.to_thread(_status, request)
