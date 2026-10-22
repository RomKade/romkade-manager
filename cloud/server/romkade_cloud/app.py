"""Serveur cloud ROMKADE : MCP pour les assistants (ChatGPT, Claude…) et relais pour les agents des consoles.

    /                        MCP (Streamable HTTP) avec OAuth : jeton d'accès Supabase (comptes ROMKADE) ; sans
                             jeton, 401 et adresse des métadonnées (RFC 9728) pour que ChatGPT, Claude… connectent
                             l'utilisateur
    /<jeton du compte>       MCP avec le jeton dans l'adresse (comptes du prototype, le temps de la bascule) ;
                             la V1 passera à OAuth (comptes ROMKADE), exigé par les annuaires d'apps.
    /agent/hello             l'agent se présente (et reçoit son secret et un code d'appairage la première fois)
    /agent/catalog           l'agent envoie la liste des fichiers de son dossier de ROMs
    /agent/favorites         l'agent envoie les favoris de la console (posés sur la carte par le Manager)
    /agent/poll, /result     ordres pour la console et leurs résultats (voir relay.py)
    /.well-known/oauth-protected-resource   serveur d'autorisation de ce serveur MCP (Supabase Auth)
    /api/me/…                API du compte pour ROMKADE Manager (jeton de session Supabase) : consoles reliées,
                             liaison d'une console sans code, suppression du compte
    /oauth/consent           ancienne adresse de la page de connexion -> https://romkade.com/authentification/
    /icon.png, /romkade-logo.webp, /fonts/…, /consoles/…   logo, polices et illustrations de l'interface
    /art/<clé>.webp          jaquette d'un jeu (libretro-thumbnails, mise en cache)

Variables : ROMKADE_CLOUD_DB (base SQLite), ROMKADE_DATA_DIR (paquet de cheats), ROMKADE_PUBLIC_URL (adresse
publique), ROMKADE_ALLOWED_HOSTS (noms d'hôte acceptés par le MCP, séparés par des virgules), ROMKADE_SUPABASE_URL
et ROMKADE_SUPABASE_PUBLISHABLE_KEY (comptes ROMKADE ; sans elles, pas d'OAuth).
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
from .analytics import Analytics
from .art import Art
from .auth import SupabaseAuth, account_id
from .relay import Relay
from .store import MAX_CONSOLES, Store
from .tools import build

log = logging.getLogger("romkade.cloud")
STATIC = Path(__file__).parent / "static"
LOCAL_ORIGIN = re.compile(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$")  # ROMKADE Manager, chez l'utilisateur
LOGIN_PAGE = "https://romkade.com/authentification/"  # page de connexion ROMKADE (site romkade.com, OAuth Supabase)
PUBLIC_FILES = {"icon.png", "icon-192.webp", "romkade-logo.webp", "romkade-logo.png"}  # .png : e-mails
MAX_BODY = 8 * 1024 * 1024
MAX_FAVORITES = 500
# Jeton du compte à la racine (/<jeton>) ; /mcp/<jeton>, forme des premiers connecteurs, reste acceptée.
TOKEN_PATH = re.compile(r"^/(?:mcp/)?([A-Za-z0-9_-]{32,})/?$")
WEB_CLIENTS = ["https://claude.ai", "https://chatgpt.com", "https://chat.openai.com", "https://www.perplexity.ai",
               "https://playground.ai.cloudflare.com"]
AGENT_FIELDS = ("agent_version", "hostname", "model", "firmware", "profile", "os_name", "roms_root", "capabilities")


def _is_mcp_call(scope) -> bool:
    """Requête d'un client MCP sur « / » (et non un navigateur qui ouvre la page d'accueil)."""
    headers = dict(scope.get("headers") or [])
    accept = headers.get(b"accept", b"").decode("latin-1")
    return (scope["method"] in ("POST", "DELETE") or b"authorization" in headers
            or "text/event-stream" in accept or "application/json" in accept)


class AccountPath:
    """Trouve le compte ROMKADE d'une requête MCP et la passe au point d'entrée MCP interne (/mcp), avec le compte
    dans la requête (« romkade.account »), jamais fourni par le client :
    - « / » + jeton OAuth (Authorization: Bearer, émis par Supabase Auth) : compte « sb:<id> » ; sans jeton valide,
      401 avec l'adresse des métadonnées, d'où ChatGPT, Claude… lancent la connexion ;
    - « /<jeton> » (comptes du prototype) : jeton inconnu, ou /mcp appelé directement : 404, sans dire pourquoi."""

    def __init__(self, app, store: Store, auth: SupabaseAuth | None = None, public_url: str = ""):
        self.app, self.store, self.auth, self.public_url = app, store, auth, public_url

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope.pop("romkade.account", None)
            path = scope["path"]
            m = TOKEN_PATH.match(path)
            if path in ("/", "/mcp", "/mcp/") and self.auth is not None and _is_mcp_call(scope):
                account = await self._oauth_account(scope)
                if account is None:
                    meta = f"{self.public_url}/.well-known/oauth-protected-resource"
                    await JSONResponse({"error": "invalid_token", "error_description": "Connexion ROMKADE requise"},
                                       401, headers={"WWW-Authenticate": f'Bearer resource_metadata="{meta}"'}
                                       )(scope, receive, send)
                    return
                scope = {**scope, "path": "/mcp", "raw_path": b"/mcp", "romkade.account": account}
            elif m or path == "/mcp" or path.startswith("/mcp/"):
                account = self.store.account_for_token(m.group(1)) if m else None
                if account is None:
                    await JSONResponse({"error": "not_found"}, 404)(scope, receive, send)
                    return
                scope = {**scope, "path": "/mcp", "raw_path": b"/mcp", "romkade.account": account}
        await self.app(scope, receive, send)

    async def _oauth_account(self, scope) -> str | None:
        header = dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin-1")
        if not header.lower().startswith("bearer "):
            return None
        claims = await asyncio.to_thread(self.auth.verify, header[7:].strip())
        if claims is None:
            return None
        return self.store.ensure_account(account_id(claims), claims.get("email"))


def create_app(store: Store | None = None, relay: Relay | None = None, public_url: str | None = None,
               auth: SupabaseAuth | None = None):
    store = store or Store(os.environ.get("ROMKADE_CLOUD_DB", "data/cloud.sqlite3"))
    relay = relay or Relay()
    public_url = (public_url or os.environ.get("ROMKADE_PUBLIC_URL", "")).rstrip("/")
    supabase_url = os.environ.get("ROMKADE_SUPABASE_URL", "")
    publishable_key = os.environ.get("ROMKADE_SUPABASE_PUBLISHABLE_KEY", "")
    if auth is None and supabase_url:
        auth = SupabaseAuth(supabase_url, publishable_key)
    mcp = build(store, relay, public_url)
    analytics = Analytics(mcp)  # statistiques d'usage, sans le contenu des appels (analytics.py)
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

    async def upload_favorites(request: Request) -> Response:
        c = console_of(request)
        if c is None:
            return JSONResponse({"error": "unauthorized"}, 401)
        try:
            payload = await body_json(request)
            favs = [[str(f[0])[:255], str(f[1])[:1024]] for f in payload.get("favorites") or []
                    if isinstance(f, list) and len(f) == 2][:MAX_FAVORITES]
        except (ValueError, AttributeError):
            return JSONResponse({"error": "bad_request"}, 400)
        return JSONResponse({"favorites": await asyncio.to_thread(store.replace_favorites, c.id, favs)})

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

    # ---------- comptes ROMKADE (OAuth) ----------
    async def protected_resource(_: Request) -> Response:
        """RFC 9728 : quel serveur d'autorisation délivre les jetons de ce serveur MCP."""
        if auth is None:
            return JSONResponse({"error": "not_found"}, 404)
        return JSONResponse({"resource": public_url, "authorization_servers": [auth.issuer],
                             "bearer_methods_supported": ["header"], "resource_name": "ROMKADE",
                             "resource_documentation": "https://romkade.com", "resource_logo_uri": f"{public_url}/icon.png"},
                            headers={"Cache-Control": "public, max-age=3600"})

    authorization_metadata: dict = {}

    async def authorization_server(_: Request) -> Response:
        """Métadonnées de Supabase Auth, servies aussi ici pour les clients qui les cherchent sur le serveur MCP."""
        if auth is None:
            return JSONResponse({"error": "not_found"}, 404)
        if not authorization_metadata or authorization_metadata.get("_at", 0) < time.time() - 3600:
            import httpx
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.get(auth.metadata_url)
            if r.status_code != 200:
                return JSONResponse({"error": "unavailable"}, 503)
            authorization_metadata.clear()
            authorization_metadata.update(r.json(), _at=time.time())
        return JSONResponse({k: v for k, v in authorization_metadata.items() if k != "_at"},
                            headers={"Cache-Control": "public, max-age=3600"})

    async def consent(request: Request) -> Response:
        """Ancienne adresse de la page de connexion : elle est maintenant sur le site (romkade.com/authentification/)."""
        query = f"?{request.url.query}" if request.url.query else ""
        return Response(status_code=302, headers={"Location": f"{LOGIN_PAGE}{query}", "Cache-Control": "no-store"})

    # ---------- API du compte (ROMKADE Manager, jeton de session Supabase) ----------
    supabase_secret = os.environ.get("ROMKADE_SUPABASE_SECRET_KEY", "")

    async def me(request: Request) -> tuple[str, dict] | None:
        header = request.headers.get("authorization", "")
        if auth is None or not header.lower().startswith("bearer "):
            return None
        claims = await asyncio.to_thread(auth.verify, header[7:].strip())
        if claims is None:
            return None
        return store.ensure_account(account_id(claims), claims.get("email")), claims

    def console_json(c) -> dict:
        return {"id": c.id, "name": c.label, "model": c.info.get("model"), "firmware": c.info.get("firmware"),
                "online": relay.online(c.id), "games": store.search([c.id], [], None, 0)[1],
                "last_seen": relay.last_poll(c.id) or c.last_seen}

    async def my_consoles(request: Request) -> Response:
        who = await me(request)
        if who is None:
            return JSONResponse({"error": "unauthorized"}, 401)
        account, _ = who
        if request.method == "POST":  # nouvelle console reliée par le Manager : secret remis à son agent
            try:
                body = await body_json(request)
            except ValueError:
                return JSONResponse({"error": "bad_request"}, 400)
            info = {k: body.get(k) for k in AGENT_FIELDS if body.get(k) is not None}
            name = (str(body.get("name") or "").strip()[:40]) or None
            # Agent déjà installé sur la console : on reprend la même console (catalogue gardé) si elle n'est à
            # personne ou déjà à ce compte ; sinon (console d'un autre compte), nouvelle console.
            existing = store.console_for_secret(str(body.get("secret") or "")) if body.get("secret") else None
            if existing is not None and existing.account_id in (None, account):
                store.claim(existing.id, account, name)
                return JSONResponse({"console": console_json(store.console(existing.id)), "secret": body["secret"],
                                     "server": public_url, "reused": True})
            if len(store.consoles_of(account)) >= MAX_CONSOLES:
                return JSONResponse({"error": "console_limit", "max": MAX_CONSOLES}, 409)
            c, secret = store.register_console_for(account, info, name)
            return JSONResponse({"console": console_json(c), "secret": secret, "server": public_url}, 201)
        return JSONResponse({"consoles": [console_json(c) for c in store.consoles_of(account)]})

    async def my_console(request: Request) -> Response:
        who = await me(request)
        if who is None:
            return JSONResponse({"error": "unauthorized"}, 401)
        account, _ = who
        c = store.console(request.path_params["console_id"])
        if c is None or c.account_id != account:
            return JSONResponse({"error": "not_found"}, 404)
        if request.method == "DELETE":
            store.unpair(c.id)
            return JSONResponse({"deleted": c.id})
        try:
            body = await body_json(request)
        except ValueError:
            return JSONResponse({"error": "bad_request"}, 400)
        if body.get("name"):
            store.rename(c.id, str(body["name"]).strip()[:40])
        return JSONResponse({"console": console_json(store.console(c.id))})

    async def delete_me(request: Request) -> Response:
        """Suppression du compte : données ROMKADE Cloud, puis l'utilisateur Supabase (clé d'administration)."""
        who = await me(request)
        if who is None:
            return JSONResponse({"error": "unauthorized"}, 401)
        account, claims = who
        if not supabase_secret:
            return JSONResponse({"error": "unavailable"}, 503)
        import httpx
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.delete(f"{auth.url}/auth/v1/admin/users/{claims['sub']}",
                                  headers={"apikey": supabase_secret, "Authorization": f"Bearer {supabase_secret}"})
        if r.status_code not in (200, 204, 404):
            log.warning("suppression Supabase refusée : %s", r.status_code)
            return JSONResponse({"error": "delete_failed"}, 502)
        consoles = store.delete_account(account)
        log.info("compte supprimé (%s console(s))", consoles)
        return JSONResponse({"deleted": True, "consoles": consoles})

    async def home(_: Request) -> Response:
        return Response(status_code=302, headers={"Location": "https://romkade.com"})

    app.router.routes.extend([
        Route("/agent/hello", hello, methods=["POST"]),
        Route("/agent/catalog", upload_catalog, methods=["POST"]),
        Route("/agent/favorites", upload_favorites, methods=["POST"]),
        Route("/agent/poll", poll, methods=["GET"]),
        Route("/agent/result", result, methods=["POST"]),
        Route("/art/{key}.webp", cover),
        Route("/healthz", health),
        Route("/.well-known/oauth-protected-resource", protected_resource),
        Route("/.well-known/oauth-protected-resource/mcp", protected_resource),
        Route("/.well-known/oauth-authorization-server", authorization_server),
        Route("/oauth/consent", consent),
        Route("/api/me/consoles", my_consoles, methods=["GET", "POST"]),
        Route("/api/me/consoles/{console_id}", my_console, methods=["PATCH", "DELETE"]),
        Route("/api/me", delete_me, methods=["DELETE"]),
        Route("/", home),
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
        try:
            async with inner_lifespan(a) as state:
                yield state
        finally:
            await analytics.close()

    app.router.lifespan_context = lifespan
    app.state.store, app.state.relay = store, relay
    return AccountPath(CrossOrigin(app), store, auth, public_url)


class CrossOrigin:
    """Polices et images de l'interface : chargées depuis le cadre isolé de l'assistant (autre origine)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith(("/mcp", "/agent")):
            await self.app(scope, receive, send)
            return
        if scope["path"].startswith("/api/"):  # API du compte, appelée par ROMKADE Manager (navigateur, en local)
            headers = dict(scope.get("headers") or [])
            origin = headers.get(b"origin", b"").decode("latin-1")
            allowed = bool(LOCAL_ORIGIN.match(origin))
            if scope["method"] == "OPTIONS":
                await Response(status_code=204 if allowed else 403, headers={
                    "access-control-allow-origin": origin, "access-control-allow-methods": "GET, POST, PATCH, DELETE",
                    "access-control-allow-headers": "authorization, content-type", "access-control-max-age": "600",
                    "vary": "Origin"} if allowed else {})(scope, receive, send)
                return

            async def send_api(message):
                if message["type"] == "http.response.start" and allowed:
                    message.setdefault("headers", []).extend([(b"access-control-allow-origin", origin.encode()),
                                                              (b"vary", b"Origin")])
                await send(message)

            await self.app(scope, receive, send_api)
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
