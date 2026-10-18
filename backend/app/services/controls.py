"""Commandes d'un jeu sur la console : quelle touche de la console fait quoi, rédigées par le LLM configuré
(Paramètres > Assistant : Claude, ChatGPT, Mistral, Gemini ou un modèle local ; app/services/llm.py).

Le modèle reçoit les passages du jeu qui parlent des commandes (Wikipédia, StrategyWiki : connaissances récupérées
sans IA, services/knowledge.py) : il n'a plus qu'à les convertir en touches de la console, ce qu'un petit modèle
local fait bien, au lieu de s'en souvenir. Sans passage utile, il s'appuie sur ce qu'il sait du jeu.

À la demande, depuis la fiche du jeu (un appel par jeu, pas de lot), puis gardées en base (table game_controls) :
toutes les éditions d'un même jeu (plateforme + titre normalisé) les partagent. Corrigeables à la main.
Claude reçoit la correspondance par défaut de RetroArch entre la manette d'origine et les touches de la console
(disposition Super Nintendo : A à droite, B en bas, X en haut, Y à gauche) et répond avec les touches de la
console, en français, anglais et espagnol. S'il ne connaît pas bien le jeu, il s'en tient aux commandes
habituelles de la console pour ce genre de jeu (« cautious »), affiché comme tel.
"""

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GameControls, RemoteFile, utcnow
from app.platforms import canonical
from app.services.classify import display_title
from app.services.descriptions import LANGS
from app.services.genres import ARCADE_DIRS, GENRES
from app.services.llm import LLM, parse_anthropic

MODEL = "claude-opus-5-5"
EFFORT = "medium"  # la correspondance manette d'origine -> touches de la console demande un peu de réflexion
MAX_TOKENS = 8000
BUTTONS = ("dpad", "left_stick", "right_stick", "a", "b", "x", "y", "l1", "r1", "l2", "r2", "l3", "r3",
           "start", "select")

# Correspondance par défaut des cœurs RetroArch : touche d'origine -> touche de la console (disposition SNES).
_SAME = "Same letters as the original pad (A = A, B = B…)."
MAPPINGS = {
    "FC": _SAME, "FDS": _SAME, "GB": _SAME, "GBC": _SAME, "GBA": _SAME + " L = L1, R = R1.", "SFC": _SAME,
    "VB": _SAME, "NGP": _SAME, "POKE": _SAME, "LYNX": _SAME,
    "MD": "Mega Drive / Genesis: A = Y, B = B, C = A; 6-button pads: X = L1, Y = X, Z = R1; Mode = Select.",
    "MDCD": "Mega-CD: A = Y, B = B, C = A; 6-button pads: X = L1, Y = X, Z = R1.",
    "SEGA32X": "32X: A = Y, B = B, C = A; 6-button pads: X = L1, Y = X, Z = R1.",
    "SMS": "Master System: button 1 = B, button 2 = A; Pause = Start.",
    "GG": "Game Gear: button 1 = B, button 2 = A.",
    "PCE": "PC Engine: I = A, II = B, Run = Start, Select = Select.",
    "PCECD": "PC Engine CD: I = A, II = B, Run = Start, Select = Select.",
    "WS": "WonderSwan: A = A, B = B; X/Y pads on the D-pad and face buttons depending on orientation.",
    "PS": "PlayStation: Cross = B, Circle = A, Square = Y, Triangle = X; L1, R1, L2, R2 identical; analog sticks "
          "identical when the console has them.",
    "N64": "Nintendo 64: A = B, B = Y, Z = L2, L = L1, R = R1, C buttons = right analog stick (or X/A + R2 on "
           "consoles without it), analog stick = left stick.",
    "DREAMCAST": "Dreamcast: A = B, B = A, X = Y, Y = X, triggers = L2 / R2, analog stick = left stick.",
    "SATURN": "Saturn: A = Y, B = B, C = A, X = L1, Y = X, Z = R1, L = L2, R = R2.",
    "PSP": "PSP (PPSSPP): Cross = B, Circle = A, Square = Y, Triangle = X, L = L1, R = R1, analog nub = left stick.",
    "NDS": "Nintendo DS (DraStic): same letters, L = L1, R = R1; the touch screen uses a cursor (stick or "
           "D-pad with a hotkey).",
}
ARCADE = ("Arcade (FBNeo / MAME): button 1 = B, button 2 = A, button 3 = Y, button 4 = X, button 5 = L1, "
          "button 6 = R1; insert coin = Select, start = Start. Neo Geo: A = B, B = A, C = Y, D = X.")

SYSTEM = """You explain how to play retro games on an Anbernic handheld running RetroArch with default settings.
The player looks at this while playing and wants to know which button of the handheld does what.

The handheld has a Super Nintendo style layout: D-pad, A (right), B (bottom), X (top), Y (left), L1, R1, L2, R2,
Start, Select, and on some models two analog sticks (left_stick, right_stick, clicks l3 / r3).
Always answer with the HANDHELD buttons, converting from the original controller with the mapping given.

Each control: one button and what it does in this game, short (2 to 8 words), e.g. "Jump", "Punch",
"Fire / confirm", "Pause". List the buttons that matter, the most used first; use "dpad" or "left_stick" for
movement. In French as written in France and Spanish as written in Spain; keep game-specific names.
"notes": one or two sentences of useful extra tips (special moves, button combos, 2-player), or "" if none.

Reference passages about the game (Wikipedia, StrategyWiki) may follow the game facts. When they describe the
controls, base your answer on them (they name the ORIGINAL controller buttons: convert them with the mapping) and
set "from_sources" to true; otherwise set "from_sources" to false and use what you know of the game.

Never invent controls. If the passages do not describe the controls and you do not really know this specific game,
set "known" to false and list only the controls that are standard for its platform and genre, keeping actions
generic."""

PROMPT = """Game: {title}
Platform: {platform}
{facts}
Button mapping from the original controller to the handheld: {mapping}{passages}"""

# Passages des connaissances envoyés au modèle : les plus proches de cette recherche, coupés à cette longueur.
CONTROLS_QUERY = "controls buttons button joystick move attack jump punch kick gameplay commandes touches"
PASSAGES = 3
PASSAGE_CHARS = 1200
# Pages ou sections consacrées aux commandes (StrategyWiki : « Jeu/Controls », sections « Buttons », « Joystick »…).
CONTROLS_HEADING = re.compile(r"control|button|joystick|joypad|gamepad|commande|touche|mando|bot[oó]n", re.I)
# Un passage qui parle de boutons à presser (le reste, intrigue ou critiques, n'aide pas et ralentit un modèle local).
CONTROLS_TEXT = re.compile(r"\b(buttons?|press(es|ed|ing)?|d-pad|directional pad|joystick|boutons?|appuy\w*|"
                           r"croix directionnelle|botón|botones|pulsa\w*)\b", re.I)


def pick_passages(chunks: list, ranked: list) -> list:
    """Seulement des passages sur les commandes : ceux dont la page ou la section en parle d'abord, puis ceux de la
    recherche (`ranked`) qui parlent de boutons, sans doublon, au plus PASSAGES. Aucun : rédaction sans passage."""
    first = [c for c in chunks if CONTROLS_HEADING.search(f"{c.page} {c.section}")]
    out = []
    for c in first + [c for c in ranked if CONTROLS_TEXT.search(c.text)]:
        if c not in out:
            out.append(c)
    return out[:PASSAGES]

SCHEMA = {
    "type": "object",
    "properties": {
        "known": {"type": "boolean"},
        "from_sources": {"type": "boolean"},
        "controls": {"type": "array", "items": {
            "type": "object",
            "properties": {"button": {"type": "string", "enum": list(BUTTONS)}, "en": {"type": "string"},
                           "fr": {"type": "string"}, "es": {"type": "string"}},
            "required": ["button", "en", "fr", "es"], "additionalProperties": False}},
        "notes": {"type": "object", "properties": {lang: {"type": "string"} for lang in LANGS},
                  "required": list(LANGS), "additionalProperties": False},
    },
    "required": ["known", "from_sources", "controls", "notes"],
    "additionalProperties": False,
}


def mapping_for(directory: str) -> str:
    code = canonical(directory)
    if code in ARCADE_DIRS:
        return ARCADE
    return MAPPINGS.get(code, "Use the RetroArch default core mapping for this platform.")


def passages_text(passages: list[dict]) -> str:
    """Bloc ajouté à la demande : chaque passage avec sa source, sa page et sa section."""
    if not passages:
        return ""
    blocks = [f"[{p['source']} · {p['page']} · {p['section']}]\n{p['text'][:PASSAGE_CHARS]}" for p in passages]
    return "\n\nReference passages about this game:\n\n" + "\n\n".join(blocks)


def prompt_for(f: RemoteFile, passages: list[dict] | None = None) -> str:
    facts = [f"{label}: {value}" for label, value in (
        ("Release year", f.release_year), ("Genre (French label)", GENRES.get(f.genre or "")),
        ("Publisher", f.publisher), ("Developer", f.developer), ("Summary", f.description)) if value]
    return PROMPT.format(title=display_title(f.full_title) if f.full_title else f.title,
                         platform=f.platform.label or f.platform.directory, facts="\n".join(facts),
                         mapping=mapping_for(f.platform.directory), passages=passages_text(passages or []))


def params_for(f: RemoteFile, model: str = MODEL) -> dict:
    """Paramètres de la demande au format Anthropic (aussi ce que reçoivent les autres fournisseurs)."""
    return {"model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM,
            "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
            "messages": [{"role": "user", "content": prompt_for(f)}]}


def clean(data: dict | None) -> dict | None:
    """Garde les touches connues ; None si aucune commande utilisable."""
    if not data:
        return None
    controls = [c for c in data.get("controls", []) if isinstance(c, dict) and c.get("button") in BUTTONS
                and all(isinstance(c.get(lang), str) for lang in LANGS)]
    return {**data, "controls": controls} if controls else None


def parse(message) -> dict | None:
    """Champs JSON d'un message Anthropic, ou None (refus, réponse tronquée ou illisible)."""
    return clean(parse_anthropic(message))


def generate(llm: LLM, f: RemoteFile, passages: list[dict] | None = None) -> dict | None:
    # Modèle local à raisonnement (Gemma 4, Qwen 3…) : sans « reasoning_effort: none », LM Studio peut réfléchir
    # plusieurs minutes et épuiser les jetons sans rien répondre (comme pour l'assistant, api/assistant.py).
    reasoning = "none" if llm.provider.id == "local" else None
    return clean(llm.complete_json(SYSTEM, prompt_for(f, passages), SCHEMA, max_tokens=MAX_TOKENS, effort=EFFORT,
                                   name="controls", reasoning=reasoning))


def page_sources(passages: list[dict]) -> list[dict]:
    """Pages distinctes des passages envoyés, dans l'ordre : ce qu'affiche la fiche sous « d'après »."""
    seen, out = set(), []
    for p in passages:
        if p["url"] not in seen:
            seen.add(p["url"])
            out.append({"source": p["source"], "page": p["page"], "url": p["url"]})
    return out


def cached(s: Session, f: RemoteFile) -> GameControls | None:
    return s.scalar(select(GameControls).where(GameControls.platform_id == f.platform_id,
                                               GameControls.normalized_title == f.normalized_title))


def _clean_notes(notes: dict | None) -> dict | None:
    notes = {lang: (notes or {}).get(lang, "").strip() for lang in LANGS}
    return notes if any(notes.values()) else None


def store(s: Session, f: RemoteFile, controls: list[dict], notes: dict | None, origin: str,
          model: str | None, sources: list[dict] | None = None) -> GameControls:
    row = cached(s, f) or GameControls(platform_id=f.platform_id, normalized_title=f.normalized_title)
    row.controls = [{"button": c["button"], **{lang: c[lang].strip() for lang in LANGS}} for c in controls]
    row.notes = _clean_notes(notes)
    row.origin, row.model, row.sources, row.updated_at = origin, model, sources or None, utcnow()
    s.add(row)
    return row


def store_generated(s: Session, f: RemoteFile, data: dict, model: str = MODEL,
                    passages: list[dict] | None = None) -> GameControls:
    notes = data.get("notes") if isinstance(data.get("notes"), dict) else None
    if passages and data.get("from_sources"):
        return store(s, f, data["controls"], notes, "sourced", model[:40], page_sources(passages))
    return store(s, f, data["controls"], notes, "written" if data.get("known") else "cautious", model[:40])


def to_out(row: GameControls | None) -> dict:
    if row is None:
        return {"status": "none", "controls": [], "notes": None, "origin": None, "sources": None, "updated_at": None}
    updated: datetime = row.updated_at
    return {"status": "found", "controls": row.controls, "notes": row.notes, "origin": row.origin,
            "sources": row.sources, "updated_at": updated}
