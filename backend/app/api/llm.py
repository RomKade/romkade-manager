"""Paramètres > IA : fournisseur de LLM (Claude, ChatGPT, Mistral, Gemini, service compatible OpenAI ou modèle
local), modèle, adresse, clés d'API (trousseau macOS), liste des modèles et test de connexion."""

import asyncio
import re

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app import errors
from app.services import llm as llm_mod

router = APIRouter(prefix="/api", tags=["llm"])
_URL_RE = re.compile(r"https?://[^\s/$.?#][^\s]*")


class ProviderOut(BaseModel):
    id: str
    label: str
    kind: str  # cloud | local
    key: str  # required | optional | none
    keys_url: str | None
    base_url: str | None
    default_model: str | None
    batch: bool
    key_source: str | None  # keychain | environment | None


class LlmSettingsOut(BaseModel):
    provider: str
    model: str | None
    base_url: str | None
    ready: bool
    problem: str | None  # llm_key_missing | llm_no_model | llm_no_url
    local_presets: dict[str, str]
    providers: list[ProviderOut]


class LlmSettingsIn(BaseModel):
    provider: str
    model: str | None = Field(None, max_length=200)
    base_url: str | None = Field(None, max_length=300)


class LlmKeyIn(BaseModel):
    provider: str
    api_key: str = Field(min_length=1, max_length=400)


class LlmTestOut(BaseModel):
    ok: bool
    provider: str
    model: str
    seconds: float


def _provider(pid: str) -> llm_mod.Provider:
    p = llm_mod.PROVIDERS.get(pid)
    if p is None:
        raise errors.AppError("llm_provider_unknown", f"Fournisseur inconnu : {pid}", 422, {"provider": pid})
    return p


def _clean_url(url: str | None) -> str | None:
    url = (url or "").strip().rstrip("/") or None
    if url and not _URL_RE.fullmatch(url):
        raise errors.AppError("llm_url_format", "Adresse invalide : elle doit commencer par http:// ou https://.", 422)
    return url


@router.get("/settings/llm", response_model=LlmSettingsOut)
def llm_settings(request: Request) -> dict:
    return llm_mod.status(request.app.state)


@router.put("/settings/llm", response_model=LlmSettingsOut)
def put_llm_settings(body: LlmSettingsIn, request: Request) -> dict:
    p = _provider(body.provider)
    url = _clean_url(body.base_url)
    if url == p.base_url:
        url = None
    request.app.state.llm_config.save(llm_mod.LlmConfig(provider=p.id, model=(body.model or "").strip() or None,
                                                        base_url=url))
    return llm_mod.status(request.app.state)


@router.put("/settings/llm/key", status_code=204)
def put_llm_key(body: LlmKeyIn, request: Request) -> None:
    llm_mod.set_key(request.app.state.credentials, _provider(body.provider), body.api_key)


@router.delete("/settings/llm/key/{provider}", status_code=204)
def delete_llm_key(provider: str, request: Request) -> None:
    llm_mod.delete_key(request.app.state.credentials, _provider(provider))


@router.get("/settings/llm/models", response_model=list[str])
async def llm_models(request: Request, provider: str = Query(...), base_url: str | None = Query(None)) -> list[str]:
    """Modèles proposés par le fournisseur (avec la clé enregistrée), pour choisir sans rien deviner."""
    st = request.app.state
    cfg = llm_mod.LlmConfig(provider=_provider(provider).id, base_url=_clean_url(base_url))
    llm = llm_mod.build(cfg, st.credentials, getattr(st, "llm_transport", None), require_model=False)
    return await asyncio.to_thread(llm.list_models)


@router.post("/settings/llm/test", response_model=LlmTestOut)
async def llm_test(request: Request) -> dict:
    """Petite demande réelle au modèle configuré (quelques jetons)."""
    llm = llm_mod.resolve(request.app.state)
    return await asyncio.to_thread(llm.test)
