"""Serveur cloud ROMKADE : MCP pour les assistants (ChatGPT, Claude…) et relais pour les agents des consoles.

    /<jeton du compte>       MCP (Streamable HTTP), ex. https://mcp.romkade.com/<jeton>. Prototype : le jeton dans
                             l'adresse tient lieu de connexion ;
                             la V1 passera à OAuth (comptes ROMKADE), exigé par les annuaires d'apps.
    /agent/hello             l'agent se présente (et reçoit son secret et un code d'appairage la première fois)
    /agent/catalog           l'agent envoie la liste des fichiers de son dossier de ROMs
    /agent/poll, /result     ordres pour la console et leurs résultats (voir relay.py)
    /icon.png, /romkade-logo.webp, /fonts/…, /consoles/…   logo, polices et illustrations de l'interface
    /art/<clé>.webp          jaquette d'un jeu (libretro-thumbnails, mise en cache)

Variables : ROMKADE_CLOUD_DB (base SQLite), ROMKADE_DATA_DIR (paquet de cheats), ROMKADE_PUBLIC_URL (adresse
publique, pour le logo), ROMKADE_ALLOWED_HOSTS (noms d'hôte acceptés par le MCP, séparés par des virgules).
"""

import asyncio
import gzip
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.services import cheats as cheat_db

from . import catalog
from .art import Art
from .relay import Relay
from .store import Store
from .tools import build

log = logging.getLogger("romkade.cloud")
STATIC = Path(__file__).parent / "static"
PUBLIC_FILES = {"icon.png", "icon-192.webp", "romkade-logo.webp"}
MAX_BODY = 8 * 1024 * 1024
# Jeton du compte à la racine (/<jeton>) ; /mcp/<jeton>, forme des premiers connecteurs, reste acceptée.
TOKEN_PATH = re.compile(r"^/(?:mcp/)?([A-Za-z0-9_-]{32,})/?$")
WEB_CLIENTS = ["https://claude.ai", "https://chatgpt.com", "https://chat.openai.com", "https://www.perplexity.ai",
               "https://playground.ai.cloudflare.com"]
AGENT_FIELDS = ("agent_version", "hostname", "model", "firmware", "profile", "os_name", "roms_root", "capabilities")


class AccountPath:
    """/<jeton> -> point d'entrée MCP interne (/mcp), avec le compte du jeton dans la requête (« romkade.account »).
    Jeton inconnu, ou /mcp appelé directement : 404, sans dire pourquoi."""

    def __init__(self, app, store: Store):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope.pop("romkade.account", None)
            path = scope["path"]
            m = TOKEN_PATH.match(path)
            if m or path == "/mcp" or path.startswith("/mcp/"):
                account = self.store.account_for_token(m.group(1)) if m else None
                if account is None:
                    await JSONResponse({"error": "not_found"}, 404)(scope, receive, send)
                    return
                scope = {**scope, "path": "/mcp", "raw_path": b"/mcp", "romkade.account": account}
        await self.app(scope, receive, send)


def create_app(store: Store | None = None, relay: Relay | None = None, public_url: str | None = None):
    store = store or Store(os.environ.get("ROMKADE_CLOUD_DB", "data/cloud.sqlite3"))
    relay = relay or Relay()
    public_url = (public_url or os.environ.get("ROMKADE_PUBLIC_URL", "")).rstrip("/")
    mcp = build(store, relay, public_url)
    art = Art(store)

    hosts = [h.strip() for h in os.environ.get("ROMKADE_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if public_url:
        hosts.append(re.sub(r"^https?://", "", public_url).split("/")[0])
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                         allowed_hosts=[*hosts, "127.0.0.1:*", "localhost:*", "testserver"],
                                         # Sans en-tête Origin (appels de serveur à serveur) : toujours accepté.
                                         allowed_origins=[*WEB_CLIENTS, "http://localhost:*", "http://127.0.0.1:*"])
    app = mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True,
                                  transport_security=security)

    # ---------- agent ----------
    def console_of(request: Request):
        auth = request.headers.get("authorization", "")
        return store.console_for_secret(auth[7:]) if auth.lower().startswith("bearer ") else None

    async def body_json(request: Request):
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise ValueError("too_big")
        if request.headers.get("content-encoding") == "gzip":
            raw = gzip.decompress(raw)
            if len(raw) > 8 * MAX_BODY:
                raise ValueError("too_big")
        return json.loads(raw or b"{}")

    async def hello(request: Request) -> Response:
        try:
            payload = await body_json(request)
        except ValueError:
            return JSONResponse({"error": "bad_request"}, 400)
        info = {k: payload.get(k) for k in AGENT_FIELDS if payload.get(k) is not None}
        c = console_of(request)
        secret = None
        if c is None:
            c, secret = store.register_console(info)
            log.info("nouvelle console %s (%s)", c.id, info.get("model"))
        else:
            store.update_info(c.id, info)
        c = store.console(c.id)
        out = {"console_id": c.id, "paired": c.account_id is not None, "name": c.label}
        if secret:
            out["secret"] = secret
        if c.account_id is None:
            out["pairing_code"] = store.pairing_code(c.id)
            out["pairing_expires_in"] = max(0, int((store.console(c.id).pairing_expires or 0) - time.time()))
        return JSONResponse(out)

    async def upload_catalog(request: Request) -> Response:
        c = console_of(request)
        if c is None:
            return JSONResponse({"error": "unauthorized"}, 401)
        try:
            payload = await body_json(request)
        except ValueError:
            return JSONResponse({"error": "bad_request"}, 400)
        files = payload.get("files") or []
        games = await asyncio.to_thread(catalog.build, files)
        count = await asyncio.to_thread(store.replace_catalog, c.id, games, files, catalog.VERSION)
        return JSONResponse({"games": count})

    async def poll(request: Request) -> Response:
        c = console_of(request)
        if c is None:
            return JSONResponse({"error": "unauthorized"}, 401)
        store.touch(c.id)
        command = await relay.poll(c.id, wait=min(float(request.query_params.get("wait", 25)), 25.0))
        if command is None:
            # L'agent s'appuie sur « paired » pour savoir s'il doit encore afficher son code ; « resync » : le cloud
            # n'a pas (ou plus) sa liste de fichiers, il la renvoie.
            return JSONResponse({"paired": store.console(c.id).account_id is not None,
                                 "resync": not store.has_raw_catalog(c.id)})
        return JSONResponse({"command": command})

    async def result(request: Request) -> Response:
        c = console_of(request)
        if c is None:
            return JSONResponse({"error": "unauthorized"}, 401)
        try:
            payload = await body_json(request)
        except ValueError:
            return JSONResponse({"error": "bad_request"}, 400)
        accepted = relay.result(c.id, str(payload.get("id")), payload)
        return JSONResponse({"accepted": accepted})

    async def static_file(request: Request) -> Response:
        name = request.path_params["name"]
        if name not in PUBLIC_FILES:
            return JSONResponse({"error": "not_found"}, 404)
        return FileResponse(STATIC / name, headers={"Cache-Control": "public, max-age=86400"})

    async def cover(request: Request) -> Response:
        key = request.path_params["key"]
        if not re.fullmatch(r"[0-9a-f]{20}", key):
            return JSONResponse({"error": "not_found"}, 404)
        try:
            path = await art.path(key, "full" if request.query_params.get("size") == "full" else "thumb")
        except Exception:  # noqa: BLE001 — banque de jaquettes injoignable : l'interface affiche les initiales
            path = None
        if path is None:
            return JSONResponse({"error": "not_found"}, 404, headers={"Cache-Control": "public, max-age=3600"})
        return FileResponse(path, headers={"Cache-Control": "public, max-age=604800, immutable"})

    async def health(_: Request) -> Response:
        return JSONResponse({"ok": True})

    app.router.routes.extend([
        Route("/agent/hello", hello, methods=["POST"]),
        Route("/agent/catalog", upload_catalog, methods=["POST"]),
        Route("/agent/poll", poll, methods=["GET"]),
        Route("/agent/result", result, methods=["POST"]),
        Route("/art/{key}.webp", cover),
        Route("/healthz", health),
        Mount("/fonts", StaticFiles(directory=STATIC / "fonts")),
        Mount("/consoles", StaticFiles(directory=STATIC / "consoles")),
        Route("/{name}", static_file),
    ])

    # Paquet de cheats libretro : téléchargé une fois au démarrage s'il manque.
    inner_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        await asyncio.to_thread(rebuild_catalogs, store)
        if cheat_db.index() is None and os.environ.get("ROMKADE_FETCH_CHEATS", "1") == "1":
            asyncio.get_running_loop().create_task(_fetch_cheats())
        async with inner_lifespan(a) as state:
            yield state

    app.router.lifespan_context = lifespan
    app.state.store, app.state.relay = store, relay
    return AccountPath(CrossOrigin(app), store)


class CrossOrigin:
    """Polices et images de l'interface : chargées depuis le cadre isolé de l'assistant (autre origine)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith(("/mcp", "/agent")):
            await self.app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS":  # pré-vol du fetch de secours de l'interface (en-tête ngrok)
            await Response(status_code=204, headers={
                "access-control-allow-origin": "*", "access-control-allow-methods": "GET",
                "access-control-allow-headers": "ngrok-skip-browser-warning", "access-control-max-age": "86400",
            })(scope, receive, send)
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"access-control-allow-origin", b"*"))
            await send(message)

        await self.app(scope, receive, send_with_cors)


def rebuild_catalogs(store: Store) -> None:
    """Recalcule les catalogues faits par une version plus ancienne de catalog.build (nouvel enrichissement)."""
    for console_id, files in store.raw_catalogs(older_than=catalog.VERSION):
        games = catalog.build(files)
        store.replace_catalog(console_id, games, version=catalog.VERSION)
        log.info("catalogue recalculé : console %s, %s jeux", console_id, len(games))


async def _fetch_cheats() -> None:
    try:
        await cheat_db.download()
        log.info("paquet de cheats libretro téléchargé")
    except Exception as exc:  # noqa: BLE001 — sans cheats, le reste marche
        log.warning("cheats indisponibles : %s", exc)
