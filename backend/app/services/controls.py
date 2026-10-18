"""Commandes d'un jeu sur la console : quelle touche de la console fait quoi, rédigées par le LLM configuré
(Paramètres > Assistant : Claude, ChatGPT, Mistral, Gemini ou un modèle local ; app/services/llm.py).

Le modèle fait le moins possible, pour qu'un petit modèle local s'en sorte :
1. il reçoit les passages du jeu qui parlent des commandes (Wikipédia, StrategyWiki : connaissances récupérées
   sans IA, services/knowledge.py) ;
2. il répond avec les boutons de la manette D'ORIGINE, choisis dans une liste fermée (LAYOUTS : Y, X, L… pour la
   Super Nintendo, A, B, C… pour la Mega Drive) : il ne peut pas citer une touche qui n'existe pas ;
3. il n'écrit qu'en anglais.
Ensuite, sans IA : la table LAYOUTS (correspondance par défaut des cœurs RetroArch) convertit chaque bouton
d'origine en touche de la console, et le glossaire (GLOSSARY) traduit les actions courantes en français et en
espagnol ; ce qu'il ne connaît pas part dans une petite demande de traduction séparée.

À la demande, depuis la fiche du jeu (un appel par jeu, pas de lot), puis gardées en base (table game_controls) :
toutes les éditions d'un même jeu (plateforme + titre normalisé) les partagent. Corrigeables à la main. S'il ne
connaît pas bien le jeu, le modèle s'en tient aux commandes habituelles de la console (« cautious »).
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
from app.services.llm import LLM

MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TOKENS = 8000
# Touches de la console (disposition Super Nintendo : A à droite, B en bas, X en haut, Y à gauche).
BUTTONS = ("dpad", "left_stick", "right_stick", "a", "b", "x", "y", "l1", "r1", "l2", "r2", "l3", "r3",
           "start", "select")

# Manette d'origine -> touche de la console, d'après la correspondance par défaut des cœurs RetroArch.
_DPAD = {"D-pad": "dpad"}
_NES = {**_DPAD, "A": "a", "B": "b", "Start": "start", "Select": "select"}
_SEGA6 = {**_DPAD, "A": "y", "B": "b", "C": "a", "X": "l1", "Y": "x", "Z": "r1", "Start": "start", "Mode": "select"}
_PLAYSTATION = {**_DPAD, "Cross": "b", "Circle": "a", "Square": "y", "Triangle": "x", "L1": "l1", "R1": "r1",
                "L2": "l2", "R2": "r2", "Start": "start", "Select": "select", "Left analog stick": "left_stick",
                "Right analog stick": "right_stick", "L3": "l3", "R3": "r3"}
_PCE = {**_DPAD, "I": "a", "II": "b", "Run": "start", "Select": "select"}
LAYOUTS: dict[str, dict[str, str]] = {
    "FC": _NES, "FDS": _NES, "GB": _NES, "GBC": _NES, "POKE": _NES,
    "GBA": {**_NES, "L": "l1", "R": "r1"},
    "SFC": {**_NES, "X": "x", "Y": "y", "L": "l1", "R": "r1"},
    "VB": {**_NES, "L": "l1", "R": "r1", "Right D-pad": "right_stick"},
    "NGP": {**_DPAD, "A": "a", "B": "b", "Option": "start"},
    "LYNX": {**_DPAD, "A": "a", "B": "b", "Option 1": "l1", "Option 2": "r1", "Pause": "start"},
    "MD": _SEGA6, "MDCD": _SEGA6, "SEGA32X": _SEGA6,
    "SMS": {**_DPAD, "Button 1": "b", "Button 2": "a", "Pause": "start"},
    "GG": {**_DPAD, "Button 1": "b", "Button 2": "a", "Start": "start"},
    "PCE": _PCE, "PCECD": _PCE,
    "PS": _PLAYSTATION,
    "PSP": {**_DPAD, "Cross": "b", "Circle": "a", "Square": "y", "Triangle": "x", "L": "l1", "R": "r1",
            "Start": "start", "Select": "select", "Analog nub": "left_stick"},
    "N64": {**_DPAD, "A": "b", "B": "y", "Z": "l2", "L": "l1", "R": "r1", "Start": "start",
            "C buttons": "right_stick", "Analog stick": "left_stick"},
    "DREAMCAST": {**_DPAD, "A": "b", "B": "a", "X": "y", "Y": "x", "L trigger": "l2", "R trigger": "r2",
                  "Start": "start", "Analog stick": "left_stick"},
    "SATURN": {**_DPAD, "A": "y", "B": "b", "C": "a", "X": "l1", "Y": "x", "Z": "r1", "L": "l2", "R": "r2",
               "Start": "start"},
    "NDS": {**_NES, "X": "x", "Y": "y", "L": "l1", "R": "r1"},
}
ARCADE = {"Joystick": "dpad", "Button 1": "b", "Button 2": "a", "Button 3": "y", "Button 4": "x", "Button 5": "l1",
          "Button 6": "r1", "Coin": "select", "Start": "start"}
NEOGEO = {"Joystick": "dpad", "A": "b", "B": "a", "C": "y", "D": "x", "Coin": "select", "Start": "start"}
# Console sans table : le modèle répond directement avec les touches de la console.
IDENTITY = {b: b for b in BUTTONS}


def layout_for(directory: str) -> dict[str, str]:
    code = canonical(directory)
    if code == "NEOGEO":
        return NEOGEO
    if code in ARCADE_DIRS:
        return ARCADE
    return LAYOUTS.get(code, IDENTITY)


def mapping_for(directory: str) -> str:
    """Correspondance en clair (lisible, pour l'assistant et les tests) : « Y = y, X = x… »."""
    return ", ".join(f"{k} = {v}" for k, v in layout_for(directory).items())


SYSTEM = """You explain how to play a retro game. The player wants to know what each button of the ORIGINAL
controller does in this game.

Answer with the original controller's buttons, using ONLY the names in the list given (the list is the original
controller of this platform). Each control: one button and what it does in this game, in English, short (1 to 6
words), e.g. "Jump", "Punch", "Light punch", "Fire", "Pause". List the buttons that matter, the most used first;
use the D-pad, joystick or analog stick for movement. "notes": one or two sentences in English with useful extra
tips (special moves, button combos, 2-player), or "" if none.

Reference passages about the game (Wikipedia, StrategyWiki) may follow. When they describe the controls, base
your answer on them and set "from_sources" to true; otherwise set "from_sources" to false.

Never invent controls. If the passages do not describe the controls and you do not really know this specific game,
set "known" to false and list only the controls that are standard for its platform and genre, keeping actions
generic."""

PROMPT = """Game: {title}
Platform: {platform}
{facts}
Original controller buttons: {buttons}{passages}"""

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


def schema_for(layout: dict[str, str]) -> dict:
    """Réponse attendue : boutons d'origine dans une liste fermée, actions et astuces en anglais."""
    return {
        "type": "object",
        "properties": {
            "known": {"type": "boolean"},
            "from_sources": {"type": "boolean"},
            "controls": {"type": "array", "items": {
                "type": "object",
                "properties": {"button": {"type": "string", "enum": list(layout)}, "action": {"type": "string"}},
                "required": ["button", "action"], "additionalProperties": False}},
            "notes": {"type": "string"},
        },
        "required": ["known", "from_sources", "controls", "notes"],
        "additionalProperties": False,
    }


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
                         buttons=", ".join(layout_for(f.platform.directory)), passages=passages_text(passages or []))


def convert(data: dict | None, layout: dict[str, str]) -> dict | None:
    """Boutons d'origine -> touches de la console (table, sans IA). Deux boutons d'origine sur la même touche, ou
    un bouton cité deux fois : actions réunies (« Jump / Swim »). None si aucune commande utilisable."""
    if not data:
        return None
    merged: dict[str, list[str]] = {}
    for c in data.get("controls", []):
        if not isinstance(c, dict) or not isinstance(c.get("action"), str) or not c["action"].strip():
            continue
        key = layout.get(c.get("button", ""))
        if key is None:
            continue
        actions = merged.setdefault(key, [])
        if c["action"].strip() not in actions:
            actions.append(c["action"].strip())
    if not merged:
        return None
    controls = [{"button": b, "en": " / ".join(a)} for b, a in merged.items()]
    notes = data.get("notes") if isinstance(data.get("notes"), str) else ""
    return {"known": bool(data.get("known")), "from_sources": bool(data.get("from_sources")),
            "controls": controls, "notes": notes.strip()}


# Actions courantes, traduites sans IA (clé : anglais en minuscules).
GLOSSARY: dict[str, tuple[str, str]] = {
    "move": ("Se déplacer", "Moverse"), "movement": ("Déplacement", "Movimiento"),
    "jump": ("Sauter", "Saltar"), "fire": ("Tirer", "Disparar"), "shoot": ("Tirer", "Disparar"),
    "attack": ("Attaquer", "Atacar"), "punch": ("Coup de poing", "Puñetazo"), "kick": ("Coup de pied", "Patada"),
    "light punch": ("Coup de poing faible", "Puñetazo débil"), "medium punch": ("Coup de poing moyen", "Puñetazo medio"),
    "heavy punch": ("Coup de poing fort", "Puñetazo fuerte"), "light kick": ("Coup de pied faible", "Patada débil"),
    "medium kick": ("Coup de pied moyen", "Patada media"), "heavy kick": ("Coup de pied fort", "Patada fuerte"),
    "block": ("Parer", "Bloquear"), "guard": ("Garde", "Guardia"), "run": ("Courir", "Correr"),
    "dash": ("Sprint", "Esprint"), "pause": ("Pause", "Pausa"), "menu": ("Menu", "Menú"),
    "pause / menu": ("Pause / menu", "Pausa / menú"), "start": ("Démarrer", "Empezar"),
    "confirm": ("Valider", "Confirmar"), "cancel": ("Annuler", "Cancelar"), "back": ("Retour", "Atrás"),
    "bomb": ("Bombe", "Bomba"), "special": ("Spécial", "Especial"), "special attack": ("Attaque spéciale", "Ataque especial"),
    "special weapon": ("Arme spéciale", "Arma especial"), "use item": ("Utiliser l'objet", "Usar objeto"),
    "item": ("Objet", "Objeto"), "inventory": ("Inventaire", "Inventario"), "map": ("Carte", "Mapa"),
    "accelerate": ("Accélérer", "Acelerar"), "brake": ("Freiner", "Frenar"), "steer": ("Diriger", "Dirigir"),
    "insert coin": ("Insérer une pièce", "Insertar moneda"), "action": ("Action", "Acción"),
    "interact": ("Interagir", "Interactuar"), "talk": ("Parler", "Hablar"), "throw": ("Lancer", "Lanzar"),
    "grab": ("Attraper", "Agarrar"), "swim": ("Nager", "Nadar"), "climb": ("Grimper", "Trepar"),
    "crouch": ("S'accroupir", "Agacharse"), "aim": ("Viser", "Apuntar"), "camera": ("Caméra", "Cámara"),
    "sword": ("Épée", "Espada"), "shield": ("Bouclier", "Escudo"), "select item": ("Choisir l'objet", "Elegir objeto"),
    "switch weapon": ("Changer d'arme", "Cambiar de arma"), "morph ball": ("Boule morphing", "Morfosfera"),
}


def _glossary(text: str) -> tuple[str, str] | None:
    """Traduction par le glossaire, aussi pour « Jump / Fire » si chaque partie y est ; None sinon."""
    hit = GLOSSARY.get(text.strip().lower())
    if hit:
        return hit
    parts = [GLOSSARY.get(x.strip().lower()) for x in text.split("/")]
    if len(parts) > 1 and all(parts):
        return " / ".join(p[0] for p in parts), " / ".join(p[1] for p in parts)  # type: ignore[index]
    return None


TRANSLATE_SYSTEM = """Translate short video game texts from English into French (as written in France) and Spanish
(as written in Spain). Keep game-specific names (characters, items, moves) as the official versions of the game
would, or unchanged if unsure. Keep it short; return one item per input text, in the same order."""
TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "properties": {"en": {"type": "string"}, "fr": {"type": "string"}, "es": {"type": "string"}},
        "required": ["en", "fr", "es"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def translate(llm: LLM | None, data: dict) -> dict:
    """Actions et astuces en fr / en / es : glossaire d'abord, puis une petite demande au modèle pour le reste.
    Sans réponse utilisable : le texte anglais, dans les trois langues."""
    texts = [c["en"] for c in data["controls"]] + ([data["notes"]] if data["notes"] else [])
    done = {t: _glossary(t) for t in texts}
    missing = [t for t, v in done.items() if v is None]
    if missing and llm is not None:
        reasoning = "none" if llm.provider.id == "local" else None
        try:
            out = llm.complete_json(TRANSLATE_SYSTEM, "\n".join(f"- {t}" for t in missing), TRANSLATE_SCHEMA,
                                    max_tokens=2000, name="translation", reasoning=reasoning) or {}
        except Exception:  # noqa: BLE001 — traduction facultative : l'anglais reste
            out = {}
        items = [i for i in out.get("items", []) if isinstance(i, dict)]
        by_en = {i.get("en", "").strip(): i for i in items}
        for k, t in enumerate(missing):
            i = by_en.get(t) or (items[k] if k < len(items) else None)
            if i and isinstance(i.get("fr"), str) and isinstance(i.get("es"), str) and i["fr"].strip():
                done[t] = (i["fr"].strip(), i["es"].strip() or t)
    tr = lambda t: done.get(t) or (t, t)  # noqa: E731
    controls = [{"button": c["button"], "en": c["en"], "fr": tr(c["en"])[0], "es": tr(c["en"])[1]}
                for c in data["controls"]]
    notes = ({"en": data["notes"], "fr": tr(data["notes"])[0], "es": tr(data["notes"])[1]} if data["notes"]
             else {lang: "" for lang in LANGS})
    return {**data, "controls": controls, "notes": notes}


def clean(data: dict | None) -> dict | None:
    """Garde les touches connues de la console, avec les trois langues ; None si aucune commande utilisable."""
    if not data:
        return None
    controls = [c for c in data.get("controls", []) if isinstance(c, dict) and c.get("button") in BUTTONS
                and all(isinstance(c.get(lang), str) for lang in LANGS)]
    return {**data, "controls": controls} if controls else None


def params_for(f: RemoteFile, model: str = MODEL, passages: list[dict] | None = None) -> dict:
    """Paramètres de la demande au format Anthropic (aussi ce que reçoivent les autres fournisseurs)."""
    return {"model": model, "max_tokens": MAX_TOKENS, "system": SYSTEM,
            "output_config": {"effort": EFFORT, "format": {"type": "json_schema",
                                                            "schema": schema_for(layout_for(f.platform.directory))}},
            "messages": [{"role": "user", "content": prompt_for(f, passages)}]}


def generate(llm: LLM, f: RemoteFile, passages: list[dict] | None = None) -> dict | None:
    """Boutons d'origine par le modèle (anglais), conversion par la table, traduction par le glossaire."""
    layout = layout_for(f.platform.directory)
    # Modèle local à raisonnement (Gemma 4, Qwen 3…) : sans « reasoning_effort: none », LM Studio peut réfléchir
    # plusieurs minutes et épuiser les jetons sans rien répondre (comme pour l'assistant, api/assistant.py).
    reasoning = "none" if llm.provider.id == "local" else None
    raw = llm.complete_json(SYSTEM, prompt_for(f, passages), schema_for(layout), max_tokens=MAX_TOKENS,
                            effort=EFFORT, name="controls", reasoning=reasoning)
    data = convert(raw, layout)
    return clean(translate(llm, data)) if data else None


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
