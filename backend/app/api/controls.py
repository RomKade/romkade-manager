"""Commandes d'un jeu (quelle touche fait quoi) : lecture, rédaction par le LLM configuré à la demande, correction
à la main. Avant la rédaction, les passages du jeu qui parlent des commandes (Wikipédia, StrategyWiki) sont joints à
la demande ; s'ils manquent, les connaissances du jeu sont récupérées sur le moment (au plus FETCH_TIMEOUT s)."""

import asyncio
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import errors
from app.services import catalog_query as cq
from app.services import controls as ctl
from app.services import descriptions as d
from app.services import knowledge as kn
from app.services import llm as llm_mod

router = APIRouter(prefix="/api", tags=["controls"])

FETCH_TIMEOUT = 25  # s : récupération des connaissances d'un jeu au moment de « Demander à l'IA »

Button = Literal["dpad", "left_stick", "right_stick", "a", "b", "x", "y", "l1", "r1", "l2", "r2", "l3", "r3",
                 "start", "select"]


class ControlOut(BaseModel):
    button: Button
    fr: str
    en: str
    es: str


class ControlSourceOut(BaseModel):
    source: str
    page: str
    url: str


class GameControlsOut(BaseModel):
    status: Literal["found", "none"]
    origin: Literal["sourced", "written", "cautious", "edited"] | None
    sources: list[ControlSourceOut] | None = None  # pages dont l'IA s'est servie (origin « sourced »)
    controls: list[ControlOut]
    notes: dict[str, str] | None
    updated_at: datetime | None
    can_generate: bool  # LLM prêt (Paramètres > Assistant)


class ControlIn(BaseModel):
    button: Button
    text: str = Field(min_length=1, max_length=120)


class GameControlsIn(BaseModel):
    """Correction à la main, dans la langue de l'utilisateur : le texte vaut pour les trois langues."""
    controls: list[ControlIn] = Field(min_length=1, max_length=len(ctl.BUTTONS))
    notes: str = Field("", max_length=600)


def _ready(request: Request) -> bool:
    try:
        llm_mod.resolve(request.app.state)
        return True
    except errors.AppError:
        return False


def _out(request: Request, row) -> dict:
    return {**ctl.to_out(row), "can_generate": _ready(request)}


@router.get("/games/{game_id}/controls", response_model=GameControlsOut)
async def game_controls(game_id: int, request: Request) -> dict:
    def read():
        with request.app.state.sessions() as s:
            return _out(request, ctl.cached(s, cq.get_file(s, game_id)))

    return await asyncio.to_thread(read)


async def _passages(st, game_id: int) -> list[dict]:
    """Passages du jeu sur ses commandes ; connaissances récupérées d'abord si le jeu n'a jamais été cherché."""
    def key():
        with st.sessions() as s:
            f = cq.get_file(s, game_id)
            return f.platform_id, f.normalized_title, kn.game_out(s, f.platform_id, f.normalized_title)["status"]

    platform_id, title, status = await asyncio.to_thread(key)
    if status == "none":
        try:  # shield : une récupération trop longue continue en arrière-plan, sans bloquer la rédaction
            await asyncio.wait_for(asyncio.shield(st.knowledge.fetch_one(platform_id, title)), FETCH_TIMEOUT)
        except Exception:  # noqa: BLE001 — réseau, délai : on rédige sans passages
            pass
    ids = None
    if st.search.ready:
        try:
            ids = await st.search.search_knowledge(kn.game_key(platform_id, title), ctl.CONTROLS_QUERY, ctl.PASSAGES)
        except Exception:  # noqa: BLE001 — repli sans Typesense
            ids = None

    def pick():
        with st.sessions() as s:
            ranked = kn.best_chunks(s, platform_id, title, ctl.CONTROLS_QUERY, ctl.PASSAGES, ids)
            chosen = ctl.pick_passages(kn.chunks_for(s, platform_id, title), ranked)
            return [{"source": c.source, "page": c.page, "section": c.section, "url": c.url, "text": c.text}
                    for c in chosen]

    return await asyncio.to_thread(pick)


@router.post("/games/{game_id}/controls", response_model=GameControlsOut)
async def generate_controls(game_id: int, request: Request) -> dict:
    """Fait rédiger les commandes par le LLM configuré (un appel ; facturé chez le fournisseur, gratuit en local)."""
    st = request.app.state
    llm = llm_mod.resolve(st)  # 409 si la clé, le modèle ou l'adresse manquent
    passages = await _passages(st, game_id)

    def run():
        with st.sessions() as s:
            f = cq.get_file(s, game_id)
            try:
                data = ctl.generate(llm, f, passages)
            except errors.AppError:
                raise
            except Exception as exc:  # noqa: BLE001 — réseau, identifiants, quota
                raise errors.AppError("controls_failed", f"{llm.provider.label} n'a pas pu répondre : {exc}", 502) from exc
        if data is None:
            raise errors.AppError("controls_unreadable", f"{llm.label} n'a pas donné de commandes utilisables pour ce jeu.", 502)
        with st.sessions.begin() as s:
            row = ctl.store_generated(s, cq.get_file(s, game_id), data, llm.model, passages)
            s.flush()
            return _out(request, row)

    return await asyncio.to_thread(run)


@router.put("/games/{game_id}/controls", response_model=GameControlsOut)
async def edit_controls(game_id: int, body: GameControlsIn, request: Request) -> dict:
    def run():
        with request.app.state.sessions.begin() as s:
            rows = [{"button": c.button, **{lang: c.text for lang in d.LANGS}} for c in body.controls]
            row = ctl.store(s, cq.get_file(s, game_id), rows, {lang: body.notes for lang in d.LANGS}, "edited", None)
            s.flush()
            return _out(request, row)

    return await asyncio.to_thread(run)
