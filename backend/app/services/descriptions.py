"""Descriptions des jeux en français, anglais et espagnol, rédigées ou traduites par le LLM configuré
(Paramètres > IA, app/services/llm.py). Avec Claude : par lot (moitié prix) ; avec un autre fournisseur ou un modèle
local : jeu par jeu, en arrière-plan.

Un jeu = plateforme + titre normalisé (toutes ses éditions partagent la description, table game_text).
- Jeu avec un résumé OpenVGDB (anglais, gameinfo.py) : le résumé est gardé tel quel en anglais (« source »), Claude
  le traduit en français et en espagnol (« translated »).
- Jeu sans résumé : Claude rédige les trois langues. S'il connaît le jeu : « written » ; sinon il n'écrit que ce
  qui est sûr d'après les informations fournies (console, genre, année, éditeur) : « cautious ».
Traitement par lot (API Message Batches : moitié prix, résultats en général en moins d'une heure). Le lot en cours
est noté dans STATE_FILE (dossier de données) : on peut suivre et importer plus tard, même après un redémarrage.
Le paramètre `fallbacks` (relais en cas de refus) n'existe pas en lot : un refus éventuel est compté et le jeu
reste sans description, à relancer.
"""

import hashlib
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import data_dir
from app.errors import AppError
from app.db.models import GameText, Platform, RemoteFile
from app.services.catalog_query import GAME_KINDS_EXCLUDED
from app.services.classify import display_title
from app.services.genres import GENRES
from app.services.llm import LLM, parse_anthropic
from app.services.subgenres import LABELS as SUB_LABELS

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
EFFORT = "low"  # descriptions courtes et traductions : peu de réflexion utile, coût réduit
MAX_TOKENS = 4000
LANGS = ("fr", "en", "es")
STATE_FILE = "descriptions_batches.json"
# Clé d'API Anthropic : Paramètres > IA (trousseau macOS), voir app/services/llm.py.
KEY_HOST, KEY_ACCOUNT = "api.anthropic.com", "game-descriptions"
KEY_RE = r"sk-ant-[A-Za-z0-9_\-]{20,}"
# Coût moyen observé par jeu en lot (Opus 5.5, effort bas, moitié prix) : pour l'estimation affichée.
COST_PER_GAME_USD = 0.008


def make_client(credentials) -> anthropic.Anthropic:
    """Client Anthropic : clé du trousseau si elle existe, sinon les identifiants du SDK (variable
    ANTHROPIC_API_KEY ou profil ~/.config/anthropic)."""
    key = credentials.get_password(KEY_HOST, KEY_ACCOUNT) if credentials else None
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def has_credentials(credentials) -> bool:
    import os

    if credentials and credentials.get_password(KEY_HOST, KEY_ACCOUNT):
        return True
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    creds = Path.home() / ".config" / "anthropic" / "credentials"
    return creds.is_dir() and any(creds.glob("*.json"))


def coverage(s: Session) -> dict:
    """Jeux (plateforme + titre) présents sur la carte, et combien ont leurs trois langues."""
    games = s.execute(select(func.count()).select_from(
        select(RemoteFile.platform_id, RemoteFile.normalized_title).join(Platform)
        .where(RemoteFile.role == "candidate", RemoteFile.deleted_at.is_(None), Platform.kind.not_in(GAME_KINDS_EXCLUDED))
        .distinct().subquery())).scalar() or 0
    complete = s.execute(select(func.count()).select_from(
        select(GameText.platform_id, GameText.normalized_title).group_by(GameText.platform_id, GameText.normalized_title)
        .having(func.count(GameText.id) >= len(LANGS)).subquery())).scalar() or 0
    return {"games": games, "complete": min(complete, games)}

SYSTEM = """You write the game descriptions of a retro video game library app, in French, English and Spanish.
Readers browse their collection and need to understand quickly what each game is.

Every description:
- 2 to 4 sentences, about 40 to 90 words: the kind of game, what the player does, and what makes it notable
  (series, famous port, mechanics). Neutral and informative: no hype, no marketing phrases, no spoilers.
- French as written in France, Spanish as written in Spain, natural rather than literal. Keep official game titles,
  character and company names as they are.
- Plain text only: no markdown, no lists, no quotes around the text.

Never invent facts. Accuracy matters more than richness."""

TRANSLATE = """Translate this English game summary into French ("fr") and Spanish ("es").
Stay faithful to its facts. If it is longer than about 120 words, condense it to about 80 words, keeping the
key facts; otherwise translate it whole.

Game: {title}
Platform: {platform}

English summary:
{summary}"""

WRITE = """Write the description of this game in English ("en"), French ("fr") and Spanish ("es").

{facts}

First decide whether you really know this specific game (this title on this platform).
- If you do, set "known" to true and describe it.
- If you are not sure which game it is or know little about it, set "known" to false and write one or two
  sentences using only the facts listed above (platform, genre, year, publisher). Do not describe a story,
  characters or gameplay details you are not sure of."""

TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {"fr": {"type": "string"}, "es": {"type": "string"}},
    "required": ["fr", "es"],
    "additionalProperties": False,
}
WRITE_SCHEMA = {
    "type": "object",
    "properties": {"known": {"type": "boolean"}, "en": {"type": "string"}, "fr": {"type": "string"},
                   "es": {"type": "string"}},
    "required": ["known", "en", "fr", "es"],
    "additionalProperties": False,
}


def custom_id(platform_id: int, normalized_title: str) -> str:
    """Identifiant d'une demande du lot (64 caractères au plus, lettres, chiffres, - et _)."""
    return f"g{platform_id}-{hashlib.sha1(normalized_title.encode()).hexdigest()[:24]}"


def pending_games(s: Session, limit: int | None = None) -> list[dict]:
    """Jeux présents sur la carte à qui il manque au moins une langue, un par plateforme + titre normalisé.
    L'édition retenue est celle qui a le plus d'informations (résumé d'abord)."""
    done = {(p, t) for p, t, n in s.execute(
        select(GameText.platform_id, GameText.normalized_title, func.count(GameText.id))
        .group_by(GameText.platform_id, GameText.normalized_title)) if n >= len(LANGS)}
    q = (select(RemoteFile, Platform).join(Platform)
         .where(RemoteFile.role == "candidate", RemoteFile.deleted_at.is_(None), Platform.kind.not_in(GAME_KINDS_EXCLUDED))
         .order_by(Platform.directory, RemoteFile.normalized_title, RemoteFile.description.is_(None), RemoteFile.id))
    games: dict[tuple[int, str], dict] = {}
    for f, p in s.execute(q):
        key = (p.id, f.normalized_title)
        if key in done or key in games:
            continue
        games[key] = {
            "platform_id": p.id, "normalized_title": f.normalized_title,
            "title": display_title(f.full_title) if f.full_title else f.title,
            "platform": p.label or p.directory, "year": f.release_year, "publisher": f.publisher,
            "developer": f.developer, "genre": GENRES.get(f.genre or ""), "subgenre": SUB_LABELS.get(f.subgenre or ""),
            "summary": f.description,
        }
        if limit and len(games) >= limit:
            break
    return list(games.values())


def game_for(f: RemoteFile) -> dict:
    """Un jeu précis (fiche ouverte, test) au format des demandes."""
    return {"platform_id": f.platform_id, "normalized_title": f.normalized_title,
            "title": display_title(f.full_title) if f.full_title else f.title,
            "platform": f.platform.label or f.platform.directory, "year": f.release_year, "publisher": f.publisher,
            "developer": f.developer, "genre": GENRES.get(f.genre or ""), "subgenre": SUB_LABELS.get(f.subgenre or ""),
            "summary": f.description}


def draft_one(sessions, llm: LLM, file_id: int) -> dict:
    """Propose une description pour un seul jeu, sans l'enregistrer : l'utilisateur la valide ensuite (save_one).
    Sert aussi de test avant le lot. Renvoie {mode, model, known, texts: {lang: {text, origin}}} : en traduction,
    l'anglais reste le résumé d'origine (« source »)."""
    from app.services import catalog_query as cq

    with sessions() as s:
        game = game_for(cq.get_file(s, file_id))
    mode, prompt, schema = request_for(game)
    data = llm.complete_json(SYSTEM, prompt, schema, max_tokens=MAX_TOKENS, effort=EFFORT, name="description",
                             reasoning="none" if llm.provider.id == "local" else None)
    texts = _texts(game, mode, data or {}, llm.model)
    if not any(origin != "source" for _, origin, _ in texts.values()):
        raise AppError("description_unreadable", f"{llm.label} n'a pas rendu de description utilisable pour ce jeu.", 502)
    return {"mode": mode, "model": llm.model[:40], "known": bool((data or {}).get("known", True)),
            "texts": {lang: {"text": text, "origin": origin} for lang, (text, origin, _) in texts.items()}}


def save_one(sessions, file_id: int, mode: str, data: dict, model: str) -> int:
    """Met dans la fiche la description validée : remplace les textes de l'IA (le résumé d'origine est gardé).
    Renvoie le nombre de textes écrits."""
    from app.services import catalog_query as cq

    with sessions.begin() as s:
        game = game_for(cq.get_file(s, file_id))
        if mode == "translate" and not game["summary"]:
            mode = "write"
        s.execute(delete(GameText).where(GameText.platform_id == game["platform_id"],
                                         GameText.normalized_title == game["normalized_title"],
                                         GameText.origin != "source"))
        return store(s, game, mode, data, model)


def request_for(game: dict) -> tuple[str, str, dict]:
    """(mode, consigne, schéma) : « translate » s'il y a un résumé anglais, sinon « write »."""
    if game["summary"]:
        mode = "translate"
        prompt = TRANSLATE.format(title=game["title"], platform=game["platform"], summary=game["summary"])
        schema = TRANSLATE_SCHEMA
    else:
        mode = "write"
        facts = [f"Game: {game['title']}", f"Platform: {game['platform']}"]
        facts += [f"{label}: {game[k]}" for k, label in (("year", "Release year"), ("genre", "Genre (French label)"),
                                                          ("subgenre", "Sub-genre (French label)"),
                                                          ("publisher", "Publisher"), ("developer", "Developer"))
                  if game[k]]
        prompt = WRITE.format(facts="\n".join(facts))
        schema = WRITE_SCHEMA
    return mode, prompt, schema


def params_for(game: dict, model: str = MODEL) -> tuple[str, MessageCreateParamsNonStreaming]:
    """(mode, paramètres de la demande au format Anthropic, pour les lots)."""
    mode, prompt, schema = request_for(game)
    return mode, MessageCreateParamsNonStreaming(
        model=model, max_tokens=MAX_TOKENS, system=SYSTEM,
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )


def parse(message) -> dict | None:
    """Champs JSON d'un message Anthropic, ou None (refus, réponse tronquée ou illisible)."""
    return parse_anthropic(message)


def store(s: Session, game: dict, mode: str, data: dict, model: str = MODEL) -> int:
    """Enregistre les langues manquantes d'un jeu. Renvoie le nombre de textes écrits."""
    have = set(s.scalars(select(GameText.lang).where(GameText.platform_id == game["platform_id"],
                                                     GameText.normalized_title == game["normalized_title"])))
    written = 0
    for lang, (text, origin, model) in _texts(game, mode, data, model).items():
        if lang in have:
            continue
        s.add(GameText(platform_id=game["platform_id"], normalized_title=game["normalized_title"], lang=lang,
                       text=text, origin=origin, model=model))
        written += 1
    return written


def _texts(game: dict, mode: str, data: dict, model: str) -> dict[str, tuple[str, str, str | None]]:
    """{lang: (texte, origine, modèle)} pour les langues dont le texte est utilisable."""
    if mode == "translate":
        texts = {"en": (game["summary"], "source", None), "fr": (data.get("fr"), "translated", model[:40]),
                 "es": (data.get("es"), "translated", model[:40])}
    else:
        origin = "written" if data.get("known") else "cautious"
        texts = {lang: (data.get(lang), origin, model[:40]) for lang in LANGS}
    return {lang: (text.strip(), origin, m) for lang, (text, origin, m) in texts.items()
            if isinstance(text, str) and text.strip()}


# ---------- lot ----------

def _state_path() -> Path:
    return data_dir() / STATE_FILE


def load_state() -> list[dict]:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _save_state(state: list[dict]) -> None:
    path = _state_path()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    path.chmod(0o600)


def submit(s: Session, client: anthropic.Anthropic, limit: int | None = None, model: str = MODEL) -> dict:
    """Soumet un lot Anthropic pour les jeux sans description complète. Renvoie {batch_id, games}."""
    games = pending_games(s, limit)
    if not games:
        return {"batch_id": None, "games": 0}
    requests, index = [], {}
    for game in games:
        mode, params = params_for(game, model)
        cid = custom_id(game["platform_id"], game["normalized_title"])
        requests.append(Request(custom_id=cid, params=params))
        index[cid] = {**game, "mode": mode}
    batch = client.messages.batches.create(requests=requests)
    state = load_state()
    state.append({"batch_id": batch.id, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                  "provider": "anthropic", "model": model, "games": index, "imported": False})
    _save_state(state)
    return {"batch_id": batch.id, "games": len(games)}


def import_results(s: Session, client: anthropic.Anthropic, batch_id: str) -> dict:
    """Importe les résultats d'un lot terminé. Renvoie les comptes (textes écrits, refus, erreurs)."""
    state = load_state()
    entry = next((e for e in state if e["batch_id"] == batch_id), None)
    if entry is None:
        raise ValueError(f"lot inconnu : {batch_id}")
    counts = {"texts": 0, "games": 0, "refused": 0, "errored": 0, "unreadable": 0}
    for result in client.messages.batches.results(batch_id):
        game = entry["games"].get(result.custom_id)
        if game is None:
            continue
        if result.result.type != "succeeded":
            counts["errored"] += 1
            continue
        message = result.result.message
        data = parse(message)
        if data is None:
            counts["refused" if message.stop_reason == "refusal" else "unreadable"] += 1
            continue
        written = store(s, game, game["mode"], data, entry.get("model", MODEL))
        counts["texts"] += written
        counts["games"] += written > 0
    entry["imported"] = True
    entry["result"] = counts
    _save_state(state)
    return counts


# ---------- sans lot (autres fournisseurs, modèle local) ----------

MAX_FAILURES = 5
_RUNNING: set[str] = set()
_LOCK = threading.Lock()


def is_direct(entry: dict) -> bool:
    return entry["batch_id"].startswith("direct-")


def running(batch_id: str) -> bool:
    return batch_id in _RUNNING


def close_interrupted() -> None:
    """Une génération sans lot coupée (application arrêtée) est close avec ce qu'elle a déjà écrit."""
    with _LOCK:
        state = load_state()
        changed = False
        for e in state:
            if is_direct(e) and not e.get("imported") and e["batch_id"] not in _RUNNING:
                e["imported"], e["result"] = True, {**e.get("counts", {}), "interrupted": True}
                changed = True
        if changed:
            _save_state(state)


def _update(batch_id: str, **fields) -> None:
    with _LOCK:
        state = load_state()
        entry = next((e for e in state if e["batch_id"] == batch_id), None)
        if entry is not None:
            entry.update(fields)
            _save_state(state)


def start_direct(sessions, llm: LLM, limit: int | None = None) -> dict:
    """Décrit les jeux un par un avec `llm`, dans un fil à part. Renvoie {batch_id, games}."""
    with sessions() as s:
        games = pending_games(s, limit)
    if not games:
        return {"batch_id": None, "games": 0}
    batch_id = f"direct-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    index = {custom_id(g["platform_id"], g["normalized_title"]): g for g in games}
    counts = {"texts": 0, "games": 0, "refused": 0, "errored": 0, "unreadable": 0, "done": 0}
    with _LOCK:
        state = load_state()
        state.append({"batch_id": batch_id, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                      "provider": llm.provider.id, "model": llm.model, "games": index, "imported": False,
                      "counts": counts})
        _save_state(state)
        _RUNNING.add(batch_id)

    def work() -> None:
        failures = 0
        try:
            for game in games:
                mode, prompt, schema = request_for(game)
                try:
                    data = llm.complete_json(SYSTEM, prompt, schema, max_tokens=MAX_TOKENS, effort=EFFORT,
                                             name="description",
                                             reasoning="none" if llm.provider.id == "local" else None)
                    failures = 0
                except Exception as exc:  # noqa: BLE001 — réseau, quota, modèle arrêté : on passe au jeu suivant
                    log.warning("description de %s impossible", game["title"], exc_info=True)
                    counts["errored"] += 1
                    failures += 1
                    data = None
                    if failures >= MAX_FAILURES:  # le modèle ne répond plus : inutile d'insister sur tous les jeux
                        counts["stopped"] = str(getattr(exc, "message", exc))[:300]
                        break
                else:
                    if data is None:
                        counts["unreadable"] += 1
                if data is not None:
                    with sessions.begin() as s:
                        written = store(s, game, mode, data, llm.model)
                    counts["texts"] += written
                    counts["games"] += written > 0
                counts["done"] += 1
                _update(batch_id, counts=dict(counts))
        finally:
            _RUNNING.discard(batch_id)
            _update(batch_id, imported=True, result=dict(counts), counts=dict(counts))

    threading.Thread(target=work, name=f"descriptions-{batch_id}", daemon=True).start()
    return {"batch_id": batch_id, "games": len(games)}

