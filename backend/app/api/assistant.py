"""Assistant de jeu : POST /api/assistant, réponse en flux (text/event-stream). Voir app/services/assistant.py.

Événements : `meta` (dans le sujet ou non, intention, jeux cités, sources, fournisseur), `delta` (morceau de texte),
`done`, `error`. Hors sujet : un seul `meta` avec `in_scope: false` et la raison ; l'interface affiche son propre
message. Les erreurs de réglage de l'IA (aucune IA, clé manquante…) sont renvoyées en JSON, avant le flux.
"""

import asyncio
import json
import logging
import random
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import errors
from app.services import assistant as asst
from app.api import saves as saves_api
from app.api.catalog import console_id
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
    if intent == "console_action":
        return await _prepare_action(request, route, game, search_text)
    mentioned = [str(n)[:120] for n in route.get("games_mentioned") or []][:5]
    wants_solution = bool(route.get("wants_solution"))
    genre = route.get("genre") if route.get("genre") in asst.GENRES else ""
    console = str(route.get("console") or "")[:60]
    players = route.get("players") if isinstance(route.get("players"), int) and 1 <= route.get("players") <= 8 else 0
    sort = route.get("sort") if route.get("sort") in asst.SORTS else ""
    # Thème qui n'est pas un genre (« western ») : expressions à chercher, titres connus du modèle pour ce thème.
    theme = [p.strip()[:40] for p in str(route.get("theme") or "").split(",") if len(p.strip()) >= 3][:6] \
        if intent == "find_games" and not mentioned else []
    theme_titles = [str(t)[:80] for t in route.get("theme_titles") or [] if isinstance(t, str)][:asst.THEME_TITLES] \
        if theme else []

    def dirs_for_console():
        with st.sessions() as s:
            return asst.console_dirs(s, console)

    dirs = await asyncio.to_thread(dirs_for_console) if intent == "find_games" else []
    library_ids = None
    theme_keys: list[str] = []
    if theme and st.search.ready:
        # Chaque expression à part, en phrase exacte ; un jeu cité par plusieurs expressions passe devant.
        votes: dict[str, int] = {}
        for phrase in theme:
            try:
                for rank, key in enumerate(await st.search.search_knowledge_games(phrase)):
                    votes[key] = votes.get(key, 0) + 100 - rank
            except Exception:  # noqa: BLE001 — sans Typesense : les titres connus du modèle seulement
                break
        theme_keys = sorted(votes, key=lambda k: -votes[k])
    if intent == "find_games" and st.search.ready and not theme:
        # Genre et console en filtres ; les mots-clés seulement s'ils nomment des jeux.
        q = " ".join(mentioned) if mentioned else ("*" if genre or dirs or sort else search_text)
        order = {"newest": ("year", "desc"), "oldest": ("year", "asc"), "added": ("added", "desc")}.get(sort)
        try:
            library_ids, _ = await st.search.search(q, genres=[genre] if genre else None, platforms=dirs or None,
                                                    limit=asst.LIBRARY_GAMES,
                                                    **({"sort": order[0], "order": order[1]} if order and not mentioned else {}))
        except Exception:  # noqa: BLE001 — repli SQLite
            library_ids = None

    console_key = console_id(request)  # favoris de la console branchée
    # « Ai-je une sauvegarde de Zelda ? » : sauvegardes lues sur la carte à l'instant (None : console injoignable).
    want_saves = intent in ("game_help", "library_info", "app_help") and bool(asst.SAVES_RE.search(question))
    saves = None
    if want_saves:
        try:
            saves = await asyncio.wait_for(saves_api._scan(request), 10)
        except Exception as exc:  # noqa: BLE001 — console éteinte, hors Wi-Fi…
            log.info("sauvegardes non lues pour l'assistant : %s", exc)

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
            if intent == "library_info":
                overview, favs = asst.library_overview(s, console_key)
                return None, (favs if asst.FAVORITES_RE.search(question) else []), overview
            if intent == "find_games":
                if theme:
                    games = asst.theme_games(s, theme_titles, theme_keys, dirs)
                    if genre:
                        games = [g for g in games if g.genre == genre]
                    if players:
                        games = [g for g in games if g.players and (g.players == 1 if players == 1 else g.players >= players)]
                elif players and not mentioned:  # nombre de joueurs : seulement en base, jamais deviné
                    games = asst.find_by_filters(s, genre, dirs, players, sort)
                elif library_ids is None and not mentioned and (genre or dirs or sort):
                    games = asst.find_by_filters(s, genre, dirs, sort=sort)
                else:
                    games = asst.find_library_games(s, mentioned or [search_text], library_ids)
                games = asst.sort_games(games, sort)
                filters = ", ".join(x for x in (asst.GENRES.get(genre, ""), f"theme: {theme[0]}" if theme else "", console,
                                                 f"{players}+ players" if players > 1 else "1 player" if players else "",
                                                 asst.SORT_LABELS.get(sort, "")) if x)
                # Une carte cliquable par jeu sous la réponse : le texte n'a pas à les énumérer (doublon).
                more = len(games) > asst.LIBRARY_GAMES
                seen: set = set()
                games = [g for g in games if not ((g.platform_id, g.normalized_title) in seen
                                                   or seen.add((g.platform_id, g.normalized_title)))][:asst.LIBRARY_GAMES]
                head = (f"Games of the user's library matching {filters}" if filters else "Games of the user's library") + \
                    (" (a selection: more games match)" if more else "") + \
                    ". They are shown to the user as clickable game cards right under your answer:\n"
                # Les consoles de la bibliothèque aussi : « ai-je la Magadrive ? » se répond même mal orthographié.
                overview = asst.library_overview(s, console_key)[0].split("\nFavorites")[0]
                return None, games, head + asst.library_lines(games, asst.broken_ids(s, console_key, games)) + "\n\n" + overview
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
                if extra := kn.version_chunk(s, f.platform_id, f.normalized_title, f.platform.directory, chunks):
                    chunks = [*chunks, extra]
                passages, srcs = asst.passages_text(chunks)
                text = asst.game_card(s, f, body.lang, console_key)
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

    if want_saves:
        def saves_block():
            with st.sessions() as s:
                targets = ([cq.get_file(s, target.id)] if target is not None else
                           [cq.get_file(s, game[0])] if game else
                           asst.find_library_games(s, mentioned, None) if mentioned else [])
                return asst.saves_text(s, saves, targets)

        context = ((context or "") + "\n\n" + await asyncio.to_thread(saves_block)).strip()

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


async def _prepare_action(request: Request, route: dict, game, search_text: str) -> asst.Prepared:
    """Action sur la console demandée à l'assistant : proposée à l'utilisateur, jamais exécutée sans son clic."""
    st = request.app.state
    kind = route.get("action") if route.get("action") in asst.ACTIONS[1:] else ""
    if not kind:
        return asst.Prepared(False, "unclear")
    profile = st.system.profile()
    caps = profile.capabilities(st.system.es_http())
    games: list[dict] = []
    shots: list[dict] = []
    if kind in asst.SCREENSHOT_VIEWS:
        def gallery():
            store = st.screenshots
            gid = game[0] if game else next((g["game_id"] for g in store.all()), None)
            if gid is None:
                return [], []
            with st.sessions() as s:
                try:
                    outs = [asst.game_out(cq.get_file(s, gid))]
                except errors.AppError:  # jeu sorti du catalogue : titre gardé avec ses captures
                    info = next((g for g in store.all() if g["game_id"] == gid), {})
                    outs = [{"id": gid, "title": info.get("title", f"#{gid}"), "platform": info.get("platform_label") or "",
                             "code": info.get("platform_code") or ""}]
            return outs, store.for_game(gid)

        games, shots = await asyncio.to_thread(gallery)
    if kind == "launch_game":
        mentioned = [str(n)[:120] for n in route.get("games_mentioned") or []][:5]
        ids = None
        if not game and st.search.ready:
            try:
                ids, _ = await st.search.search(" ".join(mentioned) or search_text, limit=asst.LIBRARY_GAMES)
            except Exception:  # noqa: BLE001 — repli SQLite
                ids = None

        def find():
            with st.sessions() as s:
                files = [cq.get_file(s, game[0])] if game else asst.find_library_games(s, mentioned or [search_text], ids)
                outs = [asst.game_out(f) for f in files if f.role == "candidate" and f.deleted_at is None]
                # Hors d'une fiche de jeu, seulement les jeux dont le titre est bien celui demandé.
                return outs if game else [g for g in outs if asst.title_matches(g["title"], mentioned or [search_text])]

        games = await asyncio.to_thread(find)
    volume = route.get("volume")
    action = asst.action_proposal(kind, volume if isinstance(volume, int) else None, caps, profile.label, games, shots)
    return asst.Prepared(True, intent="console_action", games=action["games"], action=action)


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
        if prepared.action is not None:  # action à confirmer dans la bulle : pas de réponse rédigée
            yield _sse("action", prepared.action)
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


class ShotAnalysisIn(BaseModel):
    lang: Literal["fr", "en", "es"] = "fr"


class ShotAnalysisOut(BaseModel):
    text: str
    model: str


@router.post("/games/{game_id}/screenshots/{name}/analyze", response_model=ShotAnalysisOut)
async def analyze_screenshot(game_id: int, name: str, body: ShotAnalysisIn, request: Request) -> dict:
    """Lecture d'une capture d'écran par le modèle réglé (qui doit lire les images) : quel écran, texte lisible,
    et rôle des touches si c'est un écran de commandes. Rien n'est enregistré."""
    st = request.app.state
    llm = llm_mod.resolve(st)
    path = st.screenshots.path(game_id, name)  # 404 si la capture n'existe pas

    def read():
        with st.sessions() as s:
            try:
                f = cq.get_file(s, game_id)
                return asst._game_title(f), f.platform.label or f.platform.directory
            except errors.AppError:
                return f"#{game_id}", ""

    title, console = await asyncio.to_thread(read)
    image = await asyncio.to_thread(path.read_bytes)
    prompt = "Read this screenshot." if body.lang == "en" else "Lis cette capture d'écran." if body.lang == "fr" else "Lee esta captura."
    try:
        text = await asyncio.to_thread(llm.describe_image, asst.shot_system(title, console, body.lang), prompt, image)
    except errors.AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise errors.AppError("screenshot_analysis_failed", f"{llm.provider.label} n'a pas pu lire la capture : {exc}",
                              502) from exc
    if not text:
        raise errors.AppError("screenshot_analysis_empty", f"{llm.label} n'a rien rendu pour cette capture.", 502)
    return {"text": text[:2000],
            "model": llm.label}


class CaptionIn(BaseModel):
    lang: Literal["fr", "en", "es"] = "fr"
    tone: Literal["nostalgic", "fun", "challenge", "story"] = "nostalgic"
    previous: list[str] = Field(default_factory=list, max_length=10)  # brouillons déjà proposés, à ne pas répéter


class CaptionOut(BaseModel):
    text: str
    model: str
    saw_image: bool  # le modèle a lu la capture (sinon : seulement les faits du jeu)


@router.post("/games/{game_id}/screenshots/{name}/caption", response_model=CaptionOut)
async def caption_screenshot(game_id: int, name: str, body: CaptionIn, request: Request) -> dict:
    """Post pour les réseaux sur une capture, rédigé par le modèle réglé : faits du jeu et passages de référence
    (petit RAG), plus la capture si le modèle lit les images. Rien n'est publié ni enregistré."""
    st = request.app.state
    llm = llm_mod.resolve(st)
    path = st.screenshots.path(game_id, name)  # 404 si la capture n'existe pas

    def read():
        with st.sessions() as s:
            f = cq.get_file(s, game_id)
            return asst._game_title(f), f.platform.label or f.platform.directory, asst.caption_context(s, f, body.lang)

    title, console, context = await asyncio.to_thread(read)
    angle = random.choice(asst.CAPTION_ANGLES)
    system = asst.caption_system(title, console, body.lang, body.tone, angle, context, body.previous)
    prompt = {"fr": "Écris le post.", "es": "Escribe la publicación."}.get(body.lang, "Write the post.")
    image = await asyncio.to_thread(path.read_bytes)
    saw_image = True
    try:
        text = await asyncio.to_thread(llm.describe_image, system, prompt, image, max_tokens=400)
    except errors.AppError as exc:
        if exc.code != "llm_no_vision":
            raise
        saw_image = False  # modèle sans vision : le post s'appuie seulement sur les faits du jeu
        system = system.replace("Describe the screenshot only if you can see it", "You cannot see the screenshot: do not describe it")
        out = await asyncio.to_thread(llm.complete_json, system, prompt, asst.CAPTION_SCHEMA, max_tokens=400, name="post")
        text = (out or {}).get("post", "")
    text = asst.clean_caption(text)
    if not text:
        raise errors.AppError("caption_empty", f"{llm.label} n'a rien rédigé pour cette capture : réessaie.", 502)
    return {"text": text[:1000], "model": llm.label, "saw_image": saw_image}
