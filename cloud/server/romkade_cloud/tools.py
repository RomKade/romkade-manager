"""Outils MCP de ROMKADE : ce que ChatGPT, Claude… peuvent faire avec la console et son catalogue.

Le catalogue, les favoris et les cheats sont lus dans le cloud (marchent console éteinte) ; jouer, quitter, le son,
la sauvegarde et la liste des sauvegardes d'un jeu passent par le relais jusqu'à l'agent de la console (console
allumée, en Wi-Fi).

Chaque outil est relié à l'interface ROMKADE (MCP Apps, ui://romkade/app.html, voir ui/app.html) : l'assistant
affiche la vue indiquée par le champ « view » du résultat (jeux, fiche, en cours, bibliothèque, cheats, consoles).
Un client sans MCP Apps reçoit les mêmes données en texte. Les messages d'erreur sont écrits pour être relayés à
l'utilisateur par l'assistant, dans sa langue : écrits en anglais (relecteurs des annuaires, modèle), avec un code
(`error`) que l'interface traduit (fr, en, es).
"""

import asyncio
import base64
import functools
import inspect
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.apps import Apps, ResourceCsp
from mcp.server.mcpserver import Context, Icon
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from app.platforms import PLATFORMS, canonical
from app.services import boxart
from app.services import cheats as cheat_db
from app.services.classify import normalize_title, stem_of
from app.services.genres import GENRES

from .relay import CommandFailed, CommandTimeout, ConsoleOffline, Relay
from .store import MAX_CONSOLES, Console, Store

UI = "ui://romkade/app.html"
UI_FILE = Path(__file__).parent / "ui" / "app.html"
STATIC = Path(__file__).parent / "static"
VERSION = "0.2.0"

INSTRUCTIONS = """ROMKADE connects the user's retro handheld console (Anbernic…) to this conversation.
- The library lives in the cloud: searching games, counting them, favorites, cheat codes work even if the console
  is off. Favorites (favorite_games) are the games the user starred in ROMKADE Manager.
- game_details also tells whether the user has saves for the game on the console (in-game save, save states, with
  their date); it can only check them while the console is on.
- Playing (launch_game), quitting, volume and save states need the console switched on and on Wi-Fi.
- If no console is paired yet, ask the user to open the ROMKADE app on the console (APPS menu): it shows a
  6-character code, then call pair_console with it.
- Before launch_game, find the game with search_games and use its game_id. Prefer the user's region when several
  versions exist.
- Each result is already displayed to the user by the ROMKADE interface (covers, game sheet, buttons to play,
  save, quit, volume, cheats). Do not rebuild it: no lists, cards, tables, buttons or images of your own. Answer in
  one or two short sentences, at most.
- Cheat codes: mention a few relevant ones (at most 6) unless the user asks for more.
- Only the games already on the user's console are known here. Never help find or download ROMs.
Reply in the user's language."""

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
ACT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
SETTING = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

# Erreurs de l'agent (messages en français, venus des modules du Manager) : texte anglais par code.
AGENT_ERRORS = {
    "not_on_card": "This game is no longer on the console's SD card.",
    "no_retroarch_game": "No RetroArch game is running on the console.",
    "save_state_unsupported": ("Remote save states are not possible with this console's firmware: use the "
                               "console's own shortcut."),
    "bad_path": "Invalid game.",
    "device_command_timeout": "The console did not answer in time.",
    "unknown_action": "The ROMKADE app on the console is too old for this: update it from ROMKADE Manager.",
}
MAX_PAIR_FAILURES = 10  # par compte et par heure : le code d'appairage ne se devine pas à l'aveugle
CONSOLE_ART = {p.stem for p in (STATIC / "consoles").glob("*.webp")}


HEAVY = {"cover", "cover_large", "platform_art", "art", "description", "capabilities"}


def _for_model(value):
    """Ce que lit le modèle : les données sans les adresses d'images ni les résumés (l'interface les affiche)."""
    if isinstance(value, dict):
        return {k: _for_model(v) for k, v in value.items() if k not in HEAVY and v is not None}
    if isinstance(value, list):
        return [_for_model(v) for v in value]
    return value


def view(data: dict) -> CallToolResult:
    """Résultat d'un outil : `structuredContent` pour l'interface ROMKADE, texte allégé pour le modèle."""
    text = json.dumps(_for_model(data), ensure_ascii=False, separators=(",", ":"))
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=data)


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


class UserError(ToolError):
    """Erreur à relayer à l'utilisateur : `code` stable (traduit par l'interface), message en anglais, détails."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def result(self) -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text=self.message)],
                              structured_content={"error": self.code, **self.details}, is_error=True)


def user_errors(fn):
    """Une UserError devient un résultat en erreur avec son code (sinon le SDK n'en garde que le texte)."""
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def run(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except UserError as exc:
                return exc.result()
    else:
        @functools.wraps(fn)
        def run(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except UserError as exc:
                return exc.result()
    return run


def account_of(ctx: Context) -> str:
    # Mis dans la requête par le serveur (app.AccountPath), d'après le jeton du chemin : jamais par le client.
    request = ctx.request_context.request
    account = getattr(request, "scope", {}).get("romkade.account")
    if not account:
        raise UserError("no_account", "ROMKADE account not found: sign in to ROMKADE again.")
    return account


def platform_codes(name: str | None) -> list[str] | None:
    """« Super Nintendo », « snes », « SFC »… -> codes canoniques ; None : toutes les consoles."""
    if not name or not name.strip():
        return None
    code = canonical(name)
    if code in PLATFORMS:
        return [code]
    key = normalize_title(name)
    found = [c for c, i in PLATFORMS.items() if i.label and key and key in normalize_title(i.label)]
    if not found:
        raise UserError("unknown_platform", f"Unknown system \"{name}\". Examples: Super Nintendo, Mega Drive, "
                        "Game Boy Advance, PlayStation, Arcade.", name=name)
    return found


def genre_key(name: str | None) -> str | None:
    """« RPG », « jeu de rôle », « shmup »… -> clé de genre du Manager."""
    if not name or not name.strip():
        return None
    key = normalize_title(name)
    for k, label in GENRES.items():
        if key in (k, normalize_title(label)):
            return k
    aliases = {"role playing": "rpg", "jeu de role": "rpg", "fighting": "combat", "racing": "course",
               "platformer": "plateforme", "puzzle": "reflexion", "shooter": "tir", "shoot em up": "shmup",
               "sports": "sport", "strategy": "strategie", "adventure": "aventure", "beat em up": "beat"}
    if k := aliases.get(key):
        return k
    raise UserError("unknown_genre", f"Unknown genre \"{name}\". Genres: " + ", ".join(GENRES), name=name,
                    genres=list(GENRES))


def build(store: Store, relay: Relay, public_url: str = "") -> MCPServer:
    base = public_url.rstrip("/")
    apps = Apps()
    pair_failures: dict[str, list[float]] = {}

    def ui_tool(**kwargs):
        register = apps.tool(resource_uri=UI, **kwargs)
        return lambda fn: register(user_errors(fn))

    # ---------- utilitaires ----------
    def consoles(account: str) -> list[Console]:
        return store.consoles_of(account)

    def pick(account: str, console: str | None) -> Console:
        mine = consoles(account)
        if not mine:
            raise UserError("no_console", "No console is paired yet. On the console, open the ROMKADE app (APPS "
                            "menu): it shows a 6-character code to give here (pair_console).")
        if not console:
            if len(mine) == 1:
                return mine[0]
            names = [c.label for c in mine]
            raise UserError("several_consoles", "Several consoles: say which one (" + ", ".join(names) + ").",
                            consoles=names)
        key = console.strip().lower()
        for c in mine:
            if key in (c.id, c.label.lower()):
                return c
        names = [c.label for c in mine]
        raise UserError("unknown_console", f"Console \"{console}\" not found. Consoles: " + ", ".join(names),
                        name=console, consoles=names)

    async def device(c: Console, action: str, params: dict | None = None, timeout: float = 45) -> CallToolResult:
        try:
            return await relay.call(c.id, action, params, timeout)
        except ConsoleOffline as exc:
            raise UserError("console_asleep", f"The console {c.label} does not answer: it is probably off or "
                            "asleep (Wi-Fi turns off in sleep mode). Ask the user to wake it up, then try again.",
                            console=c.label) from exc
        except CommandTimeout as exc:
            raise UserError("console_timeout", f"The console {c.label} did not answer in time. It may have gone "
                            "to sleep: try again in a moment.", console=c.label) from exc
        except CommandFailed as exc:
            raise UserError("console_failed", AGENT_ERRORS.get(exc.code, exc.message), console=c.label,
                            reason=exc.code) from exc

    def console_art(code: str) -> str | None:
        return f"{base}/consoles/{code}.webp" if base and code in CONSOLE_ART else None

    def describe(c: Console) -> CallToolResult:
        seen = relay.last_poll(c.id) or c.last_seen
        info = c.info
        return {"console": c.label, "id": c.id, "online": relay.online(c.id), "model": info.get("model"),
                "firmware": info.get("firmware"), "games": store.search([c.id], [], None, 0)[1],
                "capabilities": info.get("capabilities") or {},
                "last_seen_minutes_ago": round((time.time() - seen) / 60) if seen else None}

    def saved_at(ts: float | None) -> str | None:
        return datetime.fromtimestamp(ts, UTC).isoformat(timespec="minutes") if ts else None

    async def game_saves(c: Console, row) -> dict:
        """Sauvegardes du jeu sur la carte, lues par l'agent : sauvegarde en jeu, sauvegardes instantanées (de la
        plus récente à la plus ancienne). Console éteinte, ou agent d'avant cet ordre : `checked` à False."""
        if not relay.online(c.id):
            return {"checked": False, "reason": "console_offline"}
        filename = row["relative_path"].rsplit("/", 1)[-1]
        try:
            r = await relay.call(c.id, "saves", {"names": sorted({stem_of(filename).lower(), filename.lower()})},
                                 timeout=12)
        except CommandFailed as exc:
            return {"checked": False, "reason": "app_update_needed" if exc.code == "unknown_action" else "error"}
        except (ConsoleOffline, CommandTimeout):
            return {"checked": False, "reason": "console_offline"}
        code = canonical(row["platform_dir"])
        mine = sorted((x for x in r.get("saves") or [] if x.get("platform") and canonical(x["platform"]) == code),
                      key=lambda x: -(x.get("modified") or 0))
        in_game = next((x for x in mine if x.get("kind") == "sram"), None)
        states = [x for x in mine if x.get("kind") == "state"]
        return {"checked": True, "has_save": bool(mine),
                "in_game_save": {"saved_at": saved_at(in_game.get("modified"))} if in_game else None,
                "save_states": [{"slot": x.get("slot"), "saved_at": saved_at(x.get("modified"))} for x in states[:10]],
                "last_saved_at": saved_at(mine[0].get("modified")) if mine else None}

    def game_out(row, c: Console | None = None, full: bool = False) -> CallToolResult:
        cover = (f"{base}/art/{row['art_key']}.webp" if base and boxart.has_source(row["platform_dir"]) else None)
        out = {"game_id": row["id"], "title": row["title"], "platform": row["platform_label"],
               "platform_code": row["platform_code"], "region": row["region"], "year": row["year"],
               "genre": row["genre"], "cover": cover, "file": row["relative_path"].rsplit("/", 1)[-1]}
        if full:
            out.update(developer=row["developer"], publisher=row["publisher"], description=row["description"],
                       full_title=row["full_title"], cover_large=f"{cover}?size=full" if cover else None,
                       platform_art=console_art(row["platform_code"]))
        if c is not None:
            out["console"] = c.label
        return out

    # ---------- appairage et consoles ----------
    @ui_tool(title="Pair a console", annotations=ACT)
    def pair_console(code: str, ctx: Context, name: str | None = None) -> CallToolResult:
        """Links a console to the user's ROMKADE account with the 6-character code shown by the ROMKADE app on
        the console (APPS menu). `name`: optional nickname for the console."""
        account = account_of(ctx)
        now = time.time()
        recent = [t for t in pair_failures.get(account, []) if now - t < 3600]
        if len(recent) >= MAX_PAIR_FAILURES:
            raise UserError("too_many_codes", "Too many wrong codes: try again in an hour.")
        if len(consoles(account)) >= MAX_CONSOLES:
            raise UserError("console_limit", "One console per account for now: remove the other one in ROMKADE "
                            "Manager (My account > Console) before pairing a new one.")
        c = store.pair(code, account, (name or "").strip()[:40] or None)
        if c is None:
            pair_failures[account] = [*recent, now]
            raise UserError("bad_code", "Unknown or expired code. Open the ROMKADE app on the console again to "
                            "get a fresh code (valid for 15 minutes).")
        return view({"view": "consoles", "paired": True, "consoles": [describe(c)]})

    @ui_tool(title="List my consoles", annotations=READ)
    def list_consoles(ctx: Context) -> CallToolResult:
        """Lists the user's paired consoles: name, model, firmware, number of games, online now or not."""
        return view({"view": "consoles", "consoles": [describe(c) for c in consoles(account_of(ctx))]})

    @ui_tool(title="Rename a console", annotations=SETTING)
    def rename_console(name: str, ctx: Context, console: str | None = None) -> CallToolResult:
        """Gives a console a nickname (e.g. « Ma RG35XX »)."""
        c = pick(account_of(ctx), console)
        store.rename(c.id, name.strip()[:40])
        return view({"view": "consoles", "consoles": [describe(store.console(c.id))]})

    # ---------- catalogue (cloud) ----------
    @ui_tool(title="Search games", annotations=READ)
    def search_games(ctx: Context, query: str = "", platform: str | None = None, genre: str | None = None,
                     console: str | None = None, limit: int = 24) -> CallToolResult:
        """Searches the games on the user's console(s) by title words, optionally for one system (« Super
        Nintendo », « GBA », « PlayStation »…) and/or one genre (« RPG », « combat », « plateforme »…). An empty
        query with a platform or genre lists those games. Shows covers; returns game_id values for launch_game,
        game_details and get_cheats."""
        account = account_of(ctx)
        mine = consoles(account) if not console else [pick(account, console)]
        if not mine:
            pick(account, None)  # aucune console : explique comment en appairer une
        by_id = {c.id: c for c in mine}
        words = normalize_title(query).split()
        rows, total = store.search(list(by_id), words, platform_codes(platform), max(1, min(limit, 60)),
                                   genre_key(genre))
        return view({"view": "games", "query": query, "platform": platform, "genre": genre, "total": total,
                     "shown": len(rows),
                     "games": [game_out(r, by_id[r["console_id"]] if len(by_id) > 1 else None) for r in rows]})

    @ui_tool(title="Game details", annotations=READ)
    async def game_details(game_id: int, ctx: Context) -> CallToolResult:
        """Full sheet of one game: cover, year, genre, developer, publisher, summary, whether it is a favorite,
        and the user's saves for it on the console (in-game save, save states, with dates; checked only while the
        console is on). Use it when the user asks about a game or whether they have a save for it."""
        row = store.game(game_id, account_of(ctx))
        if row is None:
            raise UserError("unknown_game", "Game not found in the library (use a game_id from search_games).")
        c = store.console(row["console_id"])
        game = {**game_out(row, full=True),
                "favorite": store.is_favorite(c.id, row["platform_dir"], row["relative_path"])}
        return view({"view": "game", "game": game, "console": describe(c), "saves": await game_saves(c, row)})

    @ui_tool(title="Favorite games", annotations=READ)
    def favorite_games(ctx: Context, console: str | None = None, limit: int = 24) -> CallToolResult:
        """The user's favorite games on their console (starred in ROMKADE Manager), the most recently added
        first. Shows covers; returns game_id values for launch_game, game_details and get_cheats."""
        c = pick(account_of(ctx), console)
        rows, total = store.favorites(c.id, max(1, min(limit, 60)))
        return view({"view": "games", "favorites": True, "total": total, "shown": len(rows),
                     "games": [game_out(r) for r in rows]})

    @ui_tool(title="Library overview", annotations=READ)
    def library_overview(ctx: Context, console: str | None = None) -> CallToolResult:
        """Overview of a console's library: number of games per system and per genre."""
        c = pick(account_of(ctx), console)
        systems = [{"platform": r["platform_label"], "code": r["platform_code"], "games": r["games"],
                    "art": console_art(r["platform_code"])} for r in store.platforms(c.id)]
        return view({"view": "library", **describe(c), "systems": systems, "favorites": store.favorites(c.id, 0)[1],
                     "genres": [{"genre": r["genre"], "games": r["games"]} for r in store.genres(c.id)],
                     "catalog_updated_minutes_ago": round((time.time() - c.catalog_at) / 60) if c.catalog_at else None})

    @ui_tool(title="Cheat codes", annotations=READ)
    async def get_cheats(game_id: int, ctx: Context, search: str | None = None) -> CallToolResult:
        """Cheat codes (Game Genie, Action Replay, GameShark…) for a game of the library, from the libretro
        cheat database (CC BY-SA 4.0). `search`: optional words to filter codes (« lives », « invincible »…)."""
        row = store.game(game_id, account_of(ctx))
        if row is None:
            raise UserError("unknown_game", "Game not found in the library (use a game_id from search_games).")
        game = game_out(row)
        files = await asyncio.to_thread(cheat_db.for_game, row["platform_dir"], row["relative_path"])
        if not files:
            return view({"view": "cheats", "game": game, "cheats": [], "total": 0,
                         "note": "Aucun code connu pour ce jeu dans la base libretro."})
        best = files[0]
        codes = best["cheats"]
        if search and (words := normalize_title(search).split()):
            codes = [c for c in codes if any(w in normalize_title(c["desc"]) for w in words)] or codes
        return view({"view": "cheats", "game": game, "version": best["label"], "total": best["count"],
                     "cheats": [{"description": c["desc"], "code": c["code"]} for c in codes[:40]],
                     "other_versions": [f["label"] for f in files[1:4]],
                     "source": "libretro-database (CC BY-SA 4.0)", "source_url": cheat_db.SOURCE_URL})

    # ---------- console (par le relais) ----------
    async def now_playing(c: Console) -> dict:
        st = await device(c, "status")
        game = None
        if st.get("platform_dir") and st.get("relative_path"):
            row = store.game_by_path(c.id, st["platform_dir"], st["relative_path"])
            game = game_out(row, full=True) if row else {"title": st["relative_path"].rsplit("/", 1)[-1]}
        return {"view": "now", "console": describe(c), "playing": bool(st.get("playing")), "game": game,
                "in_menu": st.get("menu"), "process": st.get("process"), "volume": st.get("volume")}

    @ui_tool(title="Console status", annotations=READ)
    async def console_status(ctx: Context, console: str | None = None) -> CallToolResult:
        """Live state of the console: game being played (if any), volume, save and quit buttons. Needs the
        console on."""
        return view(await now_playing(pick(account_of(ctx), console)))

    @ui_tool(title="Launch a game", annotations=ACT)
    async def launch_game(game_id: int, ctx: Context, resume: bool = False) -> CallToolResult:
        """Starts a game on the console. A game already running is closed first (RetroArch writes its in-game
        save; progress since the last save point is lost). `resume`: continue from the automatic save state when
        there is one. Get game_id from search_games."""
        row = store.game(game_id, account_of(ctx))
        if row is None:
            raise UserError("unknown_game", "Game not found in the library (use a game_id from search_games).")
        c = store.console(row["console_id"])
        await device(c, "launch", {"platform_dir": row["platform_dir"], "relative_path": row["relative_path"],
                                   "slot": "auto" if resume else None}, timeout=60)
        return view({"view": "now", "launching": True, "console": describe(c), "playing": True,
                     "game": game_out(row, full=True), "volume": None})

    @ui_tool(title="Quit the game", annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                                                 idempotent_hint=True, open_world_hint=False))
    async def quit_game(ctx: Context, console: str | None = None) -> CallToolResult:
        """Quits the game in progress (RetroArch writes the in-game save) and returns to the console menu.
        Progress since the last save point is lost unless a save state was made first (save_state)."""
        c = pick(account_of(ctx), console)
        r = await device(c, "quit")
        return view({"view": "now", "console": describe(c), "playing": False, "game": None, "in_menu": True,
                     "result": {"quit": "quit", "none": "no game was running"}.get(r.get("result"), r.get("result"))})

    @ui_tool(title="Save state", annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                                             idempotent_hint=False, open_world_hint=False))
    async def save_state(ctx: Context, console: str | None = None) -> CallToolResult:
        """Save state of the RetroArch game in progress, in its current slot (replaces the state already in that
        slot)."""
        c = pick(account_of(ctx), console)
        await device(c, "save_state")
        return view({**await now_playing(c), "saved": True})

    @ui_tool(title="Set the volume", annotations=SETTING)
    async def set_volume(ctx: Context, percent: int | None = None, muted: bool | None = None,
                         console: str | None = None) -> CallToolResult:
        """Sets the game volume (0-100 %) or mutes/unmutes. Works best for games launched from ROMKADE."""
        if percent is None and muted is None:
            raise UserError("volume_missing", "Give a volume (0 to 100) or muted=true/false.")
        if percent is not None and not 0 <= percent <= 100:
            raise UserError("volume_range", "The volume goes from 0 to 100 %.")
        c = pick(account_of(ctx), console)
        await device(c, "volume", {"percent": percent, "muted": muted})
        return view(await now_playing(c))

    # Logo et polices intégrés à la page (data:) : ils s'affichent même si le domaine du serveur est filtré
    # (page d'avertissement de ngrok, pare-feu). Jaquettes et illustrations restent servies par le serveur.
    html = UI_FILE.read_text()
    for name, mime in (("fonts/archivo.woff2", "font/woff2"), ("fonts/atkinson.woff2", "font/woff2"),
                       ("romkade-logo.webp", "image/webp"), ("icon-192.webp", "image/webp")):
        html = html.replace(f"__ROMKADE_BASE__/{name}", data_uri(STATIC / name, mime))
    html = html.replace("__ROMKADE_BASE__", base).replace("__ROMKADE_VERSION__", VERSION)
    origin = "/".join(base.split("/")[:3])  # la CSP ne prend que des origines (sans le chemin /romkade)
    csp = ResourceCsp(resource_domains=[origin], connect_domains=[origin]) if base else None
    apps.add_html_resource(UI, html, name="romkade", title="ROMKADE", description="ROMKADE interface", csp=csp,
                           prefers_border=False)

    icons = [Icon(src=f"{base}/icon.png", mime_type="image/png", sizes=["512x512"])] if base else None
    return MCPServer("romkade", title="ROMKADE", instructions=INSTRUCTIONS, website_url="https://romkade.com",
                     icons=icons, version=VERSION, extensions=[apps])
