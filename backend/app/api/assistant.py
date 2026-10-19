"""Assistant de jeu : POST /api/assistant, réponse en flux (text/event-stream). Voir app/services/assistant.py.

Événements : `meta` (dans le sujet ou non, intention, jeux cités, sources, fournisseur), `delta` (morceau de texte),
`done`, `error`. Hors sujet : un seul `meta` avec `in_scope: false` et la raison ; l'interface affiche son propre
message. Les erreurs de réglage de l'IA (aucune IA, clé manquante…) sont renvoyées en JSON, avant le flux.
"""

import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import errors
from app.services import assistant as asst
from app.services import catalog_query as cq
from app.services import knowledge as kn
from app.services import llm as llm_mod

router = APIRouter(prefix="/api", tags=["assistant"])
log = logging.getLogger("agm.assistant")


class TurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AssistantIn(BaseModel):
    scope: Literal["library", "game"] = "library"
    game_id: int | None = None
    lang: Literal["fr", "en", "es"] = "fr"
    name: str = Field("Duke", max_length=20)  # prénom de l'assistant (Paramètres > Assistant IA)
    messages: list[TurnIn] = Field(min_length=1, max_length=60)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _prepare(request: Request, body: AssistantIn, llm) -> asst.Prepared:
    st = request.app.state
    turns = [asst.Turn(m.role, m.content.strip()) for m in body.messages]
    question = turns[-1].content
    reason = asst.prefilter(question, sum(t.role == "user" for t in turns))
    if reason:
        return asst.Prepared(False, reason)

    def load_game():
        with st.sessions() as s:
            f = cq.get_file(s, body.game_id)
            return f.id, asst._game_title(f), f.platform_id, f.normalized_title

    game = await asyncio.to_thread(load_game) if body.scope == "game" and body.game_id else None
    route_system = asst.ROUTE_SYSTEM.format(game_scope=f", here « {game[1]} »" if game else "",
                                            genres=", ".join(f"{k}: {v}" for k, v in asst.GENRES.items()))
    # Modèle local : sans réflexion préalable (« reasoning_effort: none »), l'aiguillage prend moins d'une seconde.
    reasoning = "none" if llm.provider.id == "local" else None
    route = await asyncio.to_thread(lambda: llm.complete_json(
        route_system, asst.route_prompt(turns, game[1] if game else None), asst.ROUTE_SCHEMA, max_tokens=1500,
        name="route", reasoning=reasoning))
    if route is None:
        return asst.Prepared(False, "unclear")
    intent = route.get("intent") if route.get("intent") in asst.INTENTS else "off_topic"
    if not route.get("in_scope") or intent == "off_topic":
        return asst.Prepared(False, "off_topic", intent="off_topic")
    search_text = (route.get("search") or question)[:200]
    mentioned = [str(n)[:120] for n in route.get("games_mentioned") or []][:5]
    wants_solution = bool(route.get("wants_solution"))
    genre = route.get("genre") if route.get("genre") in asst.GENRES else ""
    console = str(route.get("console") or "")[:60]

    def dirs_for_console():
        with st.sessions() as s:
            return asst.console_dirs(s, console)

    dirs = await asyncio.to_thread(dirs_for_console) if intent == "find_games" else []
    library_ids = None
    if intent == "find_games" and st.search.ready:
        # Genre et console en filtres ; les mots-clés seulement s'ils nomment des jeux.
        q = " ".join(mentioned) if mentioned else ("*" if genre or dirs else search_text)
        try:
            library_ids, _ = await st.search.search(q, genres=[genre] if genre else None, platforms=dirs or None,
                                                    limit=asst.LIBRARY_GAMES)
        except Exception:  # noqa: BLE001 — repli SQLite
            library_ids = None

    def build():
        with st.sessions() as s:
            games: list = []
            target = None
            if game:
                target = cq.get_file(s, game[0])
            elif intent == "game_help" and mentioned:
                found = asst.find_library_games(s, mentioned, None)
                target = found[0] if found else None
            if intent == "game_help" and target is not None:
                games = [target]
                return target, games, None
            if intent == "find_games":
                if library_ids is None and not mentioned and (genre or dirs):
                    games = asst.find_by_filters(s, genre, dirs)
                else:
                    games = asst.find_library_games(s, mentioned or [search_text], library_ids)
                filters = ", ".join(x for x in (asst.GENRES.get(genre, ""), console) if x)
                head = f"Games of the user's library matching {filters}:\n" if filters else "Games of the user's library:\n"
                return None, games, head + asst.library_lines(games)
            if intent == "game_help":  # jeu cité absent de la bibliothèque
                return None, [], "The game asked about is not in the user's library; answer from general knowledge " \
                                 "only if you are sure, and say it is not in the library."
            return None, [], asst.app_help(question + " " + search_text)

    target, files, context = await asyncio.to_thread(build)
    sources: list[dict] = []
    if target is not None:
        ids = None
        if st.search.ready:
            try:
                ids = await st.search.search_knowledge(kn.game_key(target.platform_id, target.normalized_title),
                                                       search_text, asst.PASSAGES)
            except Exception:  # noqa: BLE001 — repli SQLite
                ids = None

        def card():
            with st.sessions() as s:
                f = cq.get_file(s, target.id)
                chunks = kn.best_chunks(s, f.platform_id, f.normalized_title, search_text, asst.PASSAGES, ids)
                passages, srcs = asst.passages_text(chunks)
                text = asst.game_card(s, f, body.lang)
                if passages:
                    text += "\n\nPassages:\n" + passages
                else:
                    text += "\n\n(No reference passage for this game.)"
                if asst.CHEAT_RE.search(question + " " + search_text):
                    codes, src = asst.cheats_text(f.platform.directory, f.filename)
                    if src:
                        text += "\n\n" + codes
                        srcs = [src, *srcs]
                return text, srcs

        context, sources = await asyncio.to_thread(card)

    if game:
        scope = (f"This conversation is only about the game « {game[1]} » and about using the app with it: "
                 "politely refuse anything else.")
    else:
        scope = ("This conversation is about the games of the user's library and about using the app: politely "
                 "refuse anything else.")

    def outs():
        with st.sessions() as s:
            return [asst.game_out(cq.get_file(s, f.id)) for f in files[:asst.LIBRARY_GAMES]]

    return asst.Prepared(True, intent=intent, system=asst.answer_system(body.lang, scope, context or "", wants_solution, body.name),
                         games=await asyncio.to_thread(outs), sources=sources)


@router.post("/assistant")
async def assistant(body: AssistantIn, request: Request) -> StreamingResponse:
    """Question à l'assistant (bibliothèque, ou un jeu). Réponse en flux SSE."""
    if body.messages[-1].role != "user":
        raise errors.AppError("assistant_no_question", "La conversation doit se terminer par une question.", 422)
    if body.scope == "game" and not body.game_id:
        raise errors.AppError("assistant_no_game", "Aucun jeu choisi pour cette conversation.", 422)
    llm = llm_mod.resolve(request.app.state)  # 409 si aucune IA, clé, modèle ou adresse manquant
    prepared = await _prepare(request, body, llm)
    meta = {"in_scope": prepared.in_scope, "reason": prepared.reason, "intent": prepared.intent,
            "games": prepared.games, "sources": prepared.sources, "provider": llm.provider.id, "local": llm.local}
    history = asst._history([asst.Turn(m.role, m.content) for m in body.messages])

    def events():
        yield _sse("meta", meta)
        if not prepared.in_scope:
            yield _sse("done", {})
            return
        out = asst.OutputFilter()
        try:
            reasoning = "none" if llm.provider.id == "local" else None
            for chunk in llm.stream_chat(prepared.system, history, max_tokens=1500, reasoning=reasoning):
                text = out.feed(chunk)
                if text:
                    yield _sse("delta", {"text": text})
                if out.stopped:
                    break
            rest = out.done()
            if rest:
                yield _sse("delta", {"text": rest})
            yield _sse("done", {})
        except errors.AppError as exc:
            yield _sse("error", {"code": exc.code, "message": exc.message})
        except Exception as exc:  # noqa: BLE001
            log.exception("assistant")
            yield _sse("error", {"code": "assistant_failed", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
