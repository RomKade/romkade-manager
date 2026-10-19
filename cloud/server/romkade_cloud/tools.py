"""Outils MCP de ROMKADE : ce que ChatGPT, Claude… peuvent faire avec la console et son catalogue.

Le catalogue et les cheats sont lus dans le cloud (marchent console éteinte) ; jouer, quitter, le son et la
sauvegarde passent par le relais jusqu'à l'agent de la console (console allumée, en Wi-Fi).
Les messages d'erreur sont écrits pour être relayés à l'utilisateur par l'assistant, dans sa langue.
"""

import asyncio
import time

from mcp.server import MCPServer
from mcp.server.mcpserver import Context, Icon
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from app.platforms import PLATFORMS, canonical
from app.services import cheats as cheat_db
from app.services.classify import normalize_title

from .relay import CommandFailed, CommandTimeout, ConsoleOffline, Relay
from .store import Console, Store

INSTRUCTIONS = """ROMKADE connects the user's retro handheld console (Anbernic…) to this conversation.
- The library lives in the cloud: searching games, counting them, cheat codes work even if the console is off.
- Playing (launch_game), quitting, volume and save states need the console switched on and on Wi-Fi.
- If no console is paired yet, ask the user to open the ROMKADE app on the console (APPS menu): it shows a
  6-character code, then call pair_console with it.
- Before launch_game, find the game with search_games and use its id. Prefer the user's region when several
  versions exist.
- Cheat codes: show a few relevant ones (at most 6) unless the user asks for more.
- Only the games already on the user's console are known here. Never help find or download ROMs.
Reply in the user's language."""

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
ACT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

SLEEP_HINT = ("La console {name} ne répond pas : elle est sans doute éteinte ou en veille (le Wi-Fi se coupe en "
              "veille). Demande à l'utilisateur de la réveiller, puis réessaie.")
MAX_PAIR_FAILURES = 10  # par compte et par heure : le code d'appairage ne se devine pas à l'aveugle


class UserError(ToolError):
    """Erreur à relayer telle quelle à l'utilisateur (le SDK transmet le message d'un ToolError)."""


def account_of(ctx: Context) -> str:
    # Mis dans la requête par le serveur (app.AccountPath), d'après le jeton du chemin : jamais par le client.
    request = ctx.request_context.request
    account = getattr(request, "scope", {}).get("romkade.account")
    if not account:
        raise UserError("Compte ROMKADE inconnu : vérifie l'adresse du connecteur.")
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
        raise UserError(f"Console « {name} » inconnue. Exemples : Super Nintendo, Mega Drive, Game Boy Advance, "
                        "PlayStation, Arcade.")
    return found


def build(store: Store, relay: Relay, icon_url: str | None = None) -> MCPServer:
    icons = [Icon(src=icon_url, mime_type="image/png", sizes=["512x512"])] if icon_url else None
    mcp = MCPServer("romkade", title="ROMKADE", instructions=INSTRUCTIONS, website_url="https://romkade.com",
                    icons=icons, version="0.1.0")
    pair_failures: dict[str, list[float]] = {}

    def consoles(account: str) -> list[Console]:
        return store.consoles_of(account)

    def pick(account: str, console: str | None) -> Console:
        mine = consoles(account)
        if not mine:
            raise UserError("Aucune console appairée. Sur la console, ouvre l'app ROMKADE (menu APPS) : elle "
                            "affiche un code à 6 caractères à donner ici (pair_console).")
        if not console:
            if len(mine) == 1:
                return mine[0]
            raise UserError("Plusieurs consoles : précise laquelle (" + ", ".join(c.label for c in mine) + ").")
        key = console.strip().lower()
        for c in mine:
            if key in (c.id, c.label.lower()):
                return c
        raise UserError(f"Console « {console} » introuvable. Consoles : " + ", ".join(c.label for c in mine))

    async def device(c: Console, action: str, params: dict | None = None, timeout: float = 45) -> dict:
        try:
            return await relay.call(c.id, action, params, timeout)
        except ConsoleOffline as exc:
            raise UserError(SLEEP_HINT.format(name=c.label)) from exc
        except CommandTimeout as exc:
            raise UserError(f"La console {c.label} n'a pas répondu à temps. Elle s'est peut-être mise en "
                            "veille : réessaie dans un instant.") from exc
        except CommandFailed as exc:
            raise UserError(exc.message) from exc

    def describe(c: Console) -> dict:
        seen = relay.last_poll(c.id) or c.last_seen
        info = c.info
        return {"console": c.label, "id": c.id, "online": relay.online(c.id), "model": info.get("model"),
                "firmware": info.get("firmware"), "games": store.search([c.id], [], None, 0)[1],
                "last_seen_minutes_ago": round((time.time() - seen) / 60) if seen else None}

    def game_out(row, c: Console | None = None) -> dict:
        out = {"game_id": row["id"], "title": row["title"], "platform": row["platform_label"],
               "region": row["region"], "file": row["relative_path"].rsplit("/", 1)[-1]}
        if c is not None:
            out["console"] = c.label
        return out

    # ---------- appairage et consoles ----------
    @mcp.tool(title="Appairer une console", annotations=ACT)
    def pair_console(code: str, ctx: Context, name: str | None = None) -> dict:
        """Links a console to the user's ROMKADE account with the 6-character code shown by the ROMKADE app on
        the console (APPS menu). `name`: optional nickname for the console."""
        account = account_of(ctx)
        now = time.time()
        recent = [t for t in pair_failures.get(account, []) if now - t < 3600]
        if len(recent) >= MAX_PAIR_FAILURES:
            raise UserError("Trop d'essais de code : réessaie dans une heure.")
        c = store.pair(code, account, (name or "").strip()[:40] or None)
        if c is None:
            pair_failures[account] = [*recent, now]
            raise UserError("Code inconnu ou expiré. Ouvre de nouveau l'app ROMKADE sur la console pour avoir "
                            "un code à jour (valable 15 minutes).")
        return {"paired": True, **describe(c)}

    @mcp.tool(title="Mes consoles", annotations=READ)
    def list_consoles(ctx: Context) -> dict:
        """Lists the user's paired consoles: name, model, firmware, number of games, online now or not."""
        return {"consoles": [describe(c) for c in consoles(account_of(ctx))]}

    @mcp.tool(title="Renommer une console", annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                                                         idempotent_hint=True, open_world_hint=False))
    def rename_console(name: str, ctx: Context, console: str | None = None) -> dict:
        """Gives a console a nickname (e.g. « Ma RG35XX »)."""
        c = pick(account_of(ctx), console)
        store.rename(c.id, name.strip()[:40])
        return describe(store.console(c.id))

    # ---------- catalogue (cloud) ----------
    @mcp.tool(title="Chercher un jeu", annotations=READ)
    def search_games(ctx: Context, query: str = "", platform: str | None = None, console: str | None = None,
                     limit: int = 20) -> dict:
        """Searches the games on the user's console(s) by title words, optionally for one system (« Super
        Nintendo », « GBA », « PlayStation »…). Empty query with a platform lists that system's games.
        Returns game_id values to use with launch_game and get_cheats."""
        account = account_of(ctx)
        mine = consoles(account) if not console else [pick(account, console)]
        if not mine:
            pick(account, None)  # aucune console : explique comment en appairer une
        by_id = {c.id: c for c in mine}
        words = normalize_title(query).split()
        rows, total = store.search(list(by_id), words, platform_codes(platform), max(1, min(limit, 50)))
        return {"total": total, "shown": len(rows),
                "games": [game_out(r, by_id[r["console_id"]] if len(by_id) > 1 else None) for r in rows]}

    @mcp.tool(title="Ma bibliothèque", annotations=READ)
    def library_overview(ctx: Context, console: str | None = None) -> dict:
        """Overview of a console's library: number of games per system."""
        c = pick(account_of(ctx), console)
        systems = [{"platform": r["platform_label"], "games": r["games"]} for r in store.platforms(c.id)]
        return {**describe(c), "systems": systems,
                "catalog_updated_minutes_ago": round((time.time() - c.catalog_at) / 60) if c.catalog_at else None}

    @mcp.tool(title="Codes de triche", annotations=READ)
    async def get_cheats(game_id: int, ctx: Context, search: str | None = None) -> dict:
        """Cheat codes (Game Genie, Action Replay, GameShark…) for a game of the library, from the libretro
        cheat database (CC BY-SA 4.0). `search`: optional words to filter codes (« lives », « invincible »…)."""
        row = store.game(game_id, account_of(ctx))
        if row is None:
            raise UserError("Jeu introuvable dans la bibliothèque (game_id d'après search_games).")
        files = await asyncio.to_thread(cheat_db.for_game, row["platform_dir"], row["relative_path"])
        if not files:
            return {"game": row["title"], "cheats": [], "note": "Aucun code connu pour ce jeu dans la base libretro."}
        best = files[0]
        codes = best["cheats"]
        if search and (words := normalize_title(search).split()):
            codes = [c for c in codes if any(w in normalize_title(c["desc"]) for w in words)] or codes
        return {"game": row["title"], "version": best["label"], "total": best["count"],
                "cheats": [{"description": c["desc"], "code": c["code"]} for c in codes[:40]],
                "other_versions": [f["label"] for f in files[1:4]],
                "source": "libretro-database (CC BY-SA 4.0)", "source_url": cheat_db.SOURCE_URL}

    # ---------- console (par le relais) ----------
    @mcp.tool(title="État de la console", annotations=READ)
    async def console_status(ctx: Context, console: str | None = None) -> dict:
        """Live state of the console: game being played (if any) and volume. Needs the console on."""
        c = pick(account_of(ctx), console)
        st = await device(c, "status")
        game = None
        if st.get("platform_dir") and st.get("relative_path"):
            row = store.game_by_path(c.id, st["platform_dir"], st["relative_path"])
            game = game_out(row) if row else {"file": st["relative_path"]}
        return {"console": c.label, "playing": bool(st.get("playing")), "game": game, "in_menu": st.get("menu"),
                "volume": st.get("volume")}

    @mcp.tool(title="Lancer un jeu", annotations=ACT)
    async def launch_game(game_id: int, ctx: Context, resume: bool = False) -> dict:
        """Starts a game on the console (closes the menu or the game in progress). `resume`: continue from
        the automatic save state when there is one. Get game_id from search_games."""
        account = account_of(ctx)
        row = store.game(game_id, account)
        if row is None:
            raise UserError("Jeu introuvable dans la bibliothèque (game_id d'après search_games).")
        c = store.console(row["console_id"])
        await device(c, "launch", {"platform_dir": row["platform_dir"], "relative_path": row["relative_path"],
                                   "slot": "auto" if resume else None}, timeout=60)
        return {"launched": row["title"], "platform": row["platform_label"], "console": c.label}

    @mcp.tool(title="Quitter le jeu", annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                                                  idempotent_hint=True, open_world_hint=False))
    async def quit_game(ctx: Context, console: str | None = None) -> dict:
        """Quits the game in progress (RetroArch writes the in-game save) and returns to the console menu.
        Progress since the last save point may be lost: suggest save_state first."""
        c = pick(account_of(ctx), console)
        r = await device(c, "quit")
        return {"console": c.label, "result": {"quit": "quit", "none": "no game was running"}.get(r.get("result"),
                                                                                                  r.get("result"))}

    @mcp.tool(title="Sauvegarder la partie", annotations=ACT)
    async def save_state(ctx: Context, console: str | None = None) -> dict:
        """Save state of the RetroArch game in progress, in its current slot."""
        c = pick(account_of(ctx), console)
        await device(c, "save_state")
        return {"console": c.label, "saved": True}

    @mcp.tool(title="Régler le son", annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                                                 idempotent_hint=True, open_world_hint=False))
    async def set_volume(ctx: Context, percent: int | None = None, muted: bool | None = None,
                         console: str | None = None) -> dict:
        """Sets the game volume (0-100 %) or mutes/unmutes. Works best for games launched from ROMKADE."""
        if percent is None and muted is None:
            raise UserError("Indique un volume (0 à 100) ou muted=true/false.")
        if percent is not None and not 0 <= percent <= 100:
            raise UserError("Le volume va de 0 à 100 %.")
        c = pick(account_of(ctx), console)
        st = await device(c, "volume", {"percent": percent, "muted": muted})
        return {"console": c.label, "volume": st}

    return mcp
