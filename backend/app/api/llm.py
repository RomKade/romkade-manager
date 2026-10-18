"""Paramètres > IA : fournisseur de LLM (Claude, ChatGPT, Mistral, Gemini, modèle local ou service compatible
OpenAI), modèle, adresse, clés d'API (trousseau du système), liste des modèles, vérification et état de connexion."""

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
    provider: str | None  # None : aucune IA choisie
    model: str | None
    base_url: str | None
    ready: bool
    problem: str | None  # llm_none | llm_key_missing | llm_no_model | llm_no_url
    state: str  # none | incomplete | untested | connected | error
    last_error: str | None
    tested_at: str | None
    local: bool  # service sur cet ordinateur ou le réseau local : gratuit
    local_presets: dict[str, str]
    providers: list[ProviderOut]


class LlmSettingsIn(BaseModel):
    provider: str | None  # None : déconnecter l'IA
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
    error: str | None = None


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
    st = request.app.state
    store = st.llm_config
    old = store.load()
    if body.provider is None:
        store.save(llm_mod.LlmConfig())
        return llm_mod.status(st)
    p = _provider(body.provider)
    url = _clean_url(body.base_url)
    if url == p.base_url:
        url = None
    store.save(llm_mod.LlmConfig(provider=p.id, model=(body.model or "").strip() or None, base_url=url,
                                 last_test=old.last_test))
    llm_mod.autofill_model(st)  # sans modèle choisi : celui que suggère la liste du fournisseur
    return llm_mod.status(st)


@router.put("/settings/llm/key", response_model=LlmSettingsOut)
def put_llm_key(body: LlmKeyIn, request: Request) -> dict:
    st = request.app.state
    p = _provider(body.provider)
    llm_mod.set_key(st.credentials, p, body.api_key)
    if llm_mod.effective_provider(st.llm_config.load(), st.credentials) == p.id:
        llm_mod.autofill_model(st)
    return llm_mod.status(st)


@router.delete("/settings/llm/key/{provider}", response_model=LlmSettingsOut)
def delete_llm_key(provider: str, request: Request) -> dict:
    llm_mod.delete_key(request.app.state.credentials, _provider(provider))
    return llm_mod.status(request.app.state)


@router.get("/settings/llm/models", response_model=list[str])
async def llm_models(request: Request, provider: str = Query(...), base_url: str | None = Query(None)) -> list[str]:
    """Modèles proposés par le fournisseur (avec la clé enregistrée), pour choisir sans rien deviner."""
    st = request.app.state
    cfg = llm_mod.LlmConfig(provider=_provider(provider).id, base_url=_clean_url(base_url))
    llm = llm_mod.build(cfg, st.credentials, getattr(st, "llm_transport", None), require_model=False)
    return await asyncio.to_thread(llm.list_models)


@router.post("/settings/llm/test", response_model=LlmTestOut)
async def llm_test(request: Request) -> dict:
    """Petite demande réelle au modèle configuré (quelques jetons) ; le résultat allume le voyant d'état."""
    st = request.app.state
    llm = llm_mod.resolve(st)
    try:
        out = await asyncio.to_thread(llm.test)
    except errors.AppError as exc:
        llm_mod.record_test(st, llm, False, exc.message)
        raise
    llm_mod.record_test(st, llm, out["ok"], None if out["ok"] else "Réponse dans un format inattendu.")
    return out
