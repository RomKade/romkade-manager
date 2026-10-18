"""Connaissances sur les jeux (Wikidata, Wikipédia, StrategyWiki) pour l'assistant : couverture, récupération pour
un jeu ou tous, option automatique après synchronisation, test de recherche d'un passage."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app import errors
from app.services import catalog_query as cq
from app.services import knowledge as kn

router = APIRouter(prefix="/api", tags=["knowledge"])


class KnowledgeJobOut(BaseModel):
    running: bool
    total: int
    done: int
    found: int
    current: str | None
    stopping: bool


class KnowledgeStatusOut(BaseModel):
    games: int
    found: int
    not_found: int
    errors: int
    pending: int
    chunks: int
    auto_after_sync: bool
    job: KnowledgeJobOut
    license: str


class KnowledgeSettingsIn(BaseModel):
    auto_after_sync: bool


class KnowledgeSourceOut(BaseModel):
    source: str
    lang: str
    page: str
    url: str
    chunks: int
    license: str


class GameKnowledgeOut(BaseModel):
    status: str  # none | found | not_found | error
    fetched_at: datetime | None
    error: str | None
    chunks: int
    sources: list[KnowledgeSourceOut]
    sections: list[str]


class KnowledgeHitOut(BaseModel):
    source: str
    lang: str
    page: str
    section: str
    url: str
    license: str
    excerpt: str


def _status(request: Request) -> dict:
    st = request.app.state
    with st.sessions() as s:
        cov = kn.coverage(s)
    return {**cov, "auto_after_sync": st.knowledge.settings.load().auto_after_sync, "job": st.knowledge.state,
            "license": kn.LICENSE}


@router.get("/knowledge", response_model=KnowledgeStatusOut)
async def knowledge_status(request: Request) -> dict:
    return await asyncio.to_thread(_status, request)


@router.put("/knowledge/settings", response_model=KnowledgeStatusOut)
async def knowledge_settings(body: KnowledgeSettingsIn, request: Request) -> dict:
    request.app.state.knowledge.settings.save(kn.KnowledgeSettings(auto_after_sync=body.auto_after_sync))
    return await asyncio.to_thread(_status, request)


@router.post("/knowledge/start", response_model=KnowledgeStatusOut)
async def knowledge_start(request: Request) -> dict:
    """Récupère les connaissances de tous les jeux jamais recherchés, une requête à la fois (en arrière-plan)."""
    if not request.app.state.knowledge.start():
        raise errors.AppError("knowledge_running", "Une récupération est déjà en cours.", 409)
    await asyncio.sleep(0)
    return await asyncio.to_thread(_status, request)


@router.post("/knowledge/stop", response_model=KnowledgeStatusOut)
async def knowledge_stop(request: Request) -> dict:
    request.app.state.knowledge.stop()
    return await asyncio.to_thread(_status, request)


def _key(request: Request, game_id: int) -> tuple[int, str]:
    with request.app.state.sessions() as s:
        f = cq.get_file(s, game_id)
        return f.platform_id, f.normalized_title


def _game(request: Request, key: tuple[int, str]) -> dict:
    with request.app.state.sessions() as s:
        return kn.game_out(s, *key)


@router.get("/games/{game_id}/knowledge", response_model=GameKnowledgeOut)
async def game_knowledge(game_id: int, request: Request) -> dict:
    key = await asyncio.to_thread(_key, request, game_id)
    return await asyncio.to_thread(_game, request, key)


@router.post("/games/{game_id}/knowledge", response_model=GameKnowledgeOut)
async def fetch_game_knowledge(game_id: int, request: Request) -> dict:
    """Récupère (ou récupère à nouveau) les connaissances de ce jeu tout de suite : sert aussi de test."""
    key = await asyncio.to_thread(_key, request, game_id)
    await request.app.state.knowledge.fetch_one(*key)
    return await asyncio.to_thread(_game, request, key)


@router.get("/games/{game_id}/knowledge/search", response_model=list[KnowledgeHitOut])
async def search_game_knowledge(game_id: int, request: Request, q: str = Query("", max_length=300),
                                limit: int = Query(4, ge=1, le=10)) -> list[dict]:
    """Passages que l'assistant recevrait pour cette question (Typesense, sinon classement simple)."""
    platform_id, title = await asyncio.to_thread(_key, request, game_id)
    search = request.app.state.search
    ids = None
    if search.ready:
        try:
            ids = await search.search_knowledge(kn.game_key(platform_id, title), q, limit)
        except Exception:  # noqa: BLE001 — repli sans Typesense
            ids = None

    def pick():
        with request.app.state.sessions() as s:
            return [{"source": c.source, "lang": c.lang, "page": c.page, "section": c.section, "url": c.url,
                     "license": c.license, "excerpt": c.text[:400]}
                    for c in kn.best_chunks(s, platform_id, title, q, limit, ids)]

    return await asyncio.to_thread(pick)
