"""Commandes d'un jeu (quelle touche fait quoi) : lecture, rédaction par Claude à la demande, correction à la main."""

import asyncio
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app import errors
from app.services import catalog_query as cq
from app.services import controls as ctl
from app.services import descriptions as d

router = APIRouter(prefix="/api", tags=["controls"])

Button = Literal["dpad", "left_stick", "right_stick", "a", "b", "x", "y", "l1", "r1", "l2", "r2", "l3", "r3",
                 "start", "select"]


class ControlOut(BaseModel):
    button: Button
    fr: str
    en: str
    es: str


class GameControlsOut(BaseModel):
    status: Literal["found", "none"]
    origin: Literal["written", "cautious", "edited"] | None
    controls: list[ControlOut]
    notes: dict[str, str] | None
    updated_at: datetime | None
    can_generate: bool  # identifiants Anthropic disponibles


class ControlIn(BaseModel):
    button: Button
    text: str = Field(min_length=1, max_length=120)


class GameControlsIn(BaseModel):
    """Correction à la main, dans la langue de l'utilisateur : le texte vaut pour les trois langues."""
    controls: list[ControlIn] = Field(min_length=1, max_length=len(ctl.BUTTONS))
    notes: str = Field("", max_length=600)


def _out(request: Request, row) -> dict:
    return {**ctl.to_out(row), "can_generate": d.has_credentials(request.app.state.credentials)}


@router.get("/games/{game_id}/controls", response_model=GameControlsOut)
async def game_controls(game_id: int, request: Request) -> dict:
    def read():
        with request.app.state.sessions() as s:
            return _out(request, ctl.cached(s, cq.get_file(s, game_id)))

    return await asyncio.to_thread(read)


@router.post("/games/{game_id}/controls", response_model=GameControlsOut)
async def generate_controls(game_id: int, request: Request) -> dict:
    """Fait rédiger les commandes par Claude (un appel, facturé sur le compte Anthropic) et les garde."""
    st = request.app.state
    if not d.has_credentials(st.credentials):
        raise errors.AppError("anthropic_key_missing", "Ajoute d'abord une clé d'API Anthropic (Paramètres).", 409)

    def run():
        with st.sessions() as s:
            f = cq.get_file(s, game_id)
            try:
                data = ctl.generate(d.make_client(st.credentials), f)
            except Exception as exc:  # noqa: BLE001 — réseau, identifiants, quota
                raise errors.AppError("controls_failed", f"Claude n'a pas pu répondre : {exc}", 502) from exc
        if data is None:
            raise errors.AppError("controls_unreadable", "Claude n'a pas donné de commandes utilisables pour ce jeu.", 502)
        with st.sessions.begin() as s:
            row = ctl.store_generated(s, cq.get_file(s, game_id), data)
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
