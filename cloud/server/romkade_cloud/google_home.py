"""Google Home : « Hey Google, ouvre Zelda sur la RG35XX ». © 2026 ROMKADE, tous droits réservés.

Intégration « cloud-to-cloud » de Google Home (developers.home.google.com/cloud-to-cloud) : chaque console reliée
au compte ROMKADE devient un appareil de type console de jeux (GAME_CONSOLE) dans l'app Google Home. Ses jeux sont
les « applications » de l'appareil (trait AppSelector) : favoris, puis jeux joués récemment, puis jeux connus ; un nom prononcé qui
n'est pas dans la liste est cherché dans tout le catalogue. On/Off et Stop quittent le jeu, Volume règle le son.
En français, Google transmet aussi un nom de jeu hors de la liste (« ouvre Tetris sur la console ») : il est cherché
dans tout le catalogue, la bibliothèque entière est donc jouable à la voix.
Les ordres passent par le même relais que ChatGPT et Claude (relay.py) jusqu'à l'app ROMKADE de la console.

Connexion du compte (« account linking » OAuth de Google) : Google ne fait pas de PKCE, que Supabase exige. Le
serveur sert donc de petit relais d'autorisation : /google/authorize renvoie vers Supabase (avec PKCE, page de
connexion et de consentement de romkade.com/authentification), /google/callback rend à Google un code à usage
unique, /google/token l'échange auprès de Supabase. Les jetons d'accès sont ceux de Supabase, vérifiés comme pour
le MCP. Google présente l'identifiant et le secret de ROMKADE (ROMKADE_GOOGLE_CLIENT_ID / _SECRET) ; côté Supabase,
le relais est un client public (ROMKADE_GOOGLE_SUPABASE_CLIENT_ID, redirection vers /google/callback). La connexion
en cours est gardée en base (store.oauth_put) : un redémarrage du serveur ne la casse pas.

Mises à jour sans « synchronise mes appareils » (homegraph.py) : favoris ou jeux récents changés -> Request Sync ;
console allumée, jeu lancé ou quitté -> Report State. Seulement pour les comptes reliés à Google (SYNC reçu).
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
import time
from urllib.parse import parse_qsl, urlencode

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.services.classify import normalize_title

from .auth import SupabaseAuth, account_id
from .homegraph import HomeGraph
from .relay import CommandFailed, CommandTimeout, ConsoleOffline, Relay
from .store import Console, Store

log = logging.getLogger(__name__)

GOOGLE_REDIRECTS = ("https://oauth-redirect.googleusercontent.com/r/",
                    "https://oauth-redirect-sandbox.googleusercontent.com/r/")
CODE_TTL = 600            # secondes : connexion en cours, puis code rendu à Google
MAX_APPS = 120            # titres déclarés (favoris d'abord, un seul par titre) ; au-delà, Google tronque la liste
                          # et refuse les autres jeux, alors qu'un nom hors liste court lui est transmis tel quel
TRAITS = ["action.devices.traits.AppSelector", "action.devices.traits.MediaState", "action.devices.traits.OnOff",
          "action.devices.traits.TransportControl", "action.devices.traits.Volume"]
LANGS = ("fr", "en")      # langues des noms déclarés (les titres de jeux ne se traduisent pas)
SYNC_DELAY = 20           # secondes : plusieurs changements de liste rapprochés -> une seule demande à Google
ONLINE_REPORT_EVERY = 600 # secondes : état « en ligne » redit à Google au plus toutes les 10 minutes


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def synonyms(title: str) -> list[str]:
    """Façons de dire un jeu : « Legend of Zelda, The » -> « The Legend of Zelda », « Legend of Zelda », « Zelda » ;
    sans sous-titre (« Sonic The Hedgehog 2 - … ») ; le premier nom est celui que Google répète."""
    base = title
    for article in (", The", ", A", ", An"):
        if base.endswith(article):
            base = f"{article[2:]} {base[:-len(article)]}"
    names = [base]
    short = base.split(" ", 1)[1] if base.lower().startswith(("the ", "a ", "an ")) else base
    for sep in (" - ", ": "):
        short = short.split(sep)[0]
    names.append(short.strip())
    if short.lower().startswith("legend of "):
        names.append(short[10:].strip())
    return list(dict.fromkeys(n for n in names if n))


class GoogleHome:
    def __init__(self, store: Store, relay: Relay, auth: SupabaseAuth | None, public_url: str, client_id: str,
                 client_secret: str, supabase_client_id: str, transport: httpx.AsyncBaseTransport | None = None,
                 homegraph: HomeGraph | None = None):
        self.store, self.relay, self.auth, self.public_url = store, relay, auth, public_url.rstrip("/")
        self.client_id, self.client_secret, self.supabase_client_id = client_id, client_secret, supabase_client_id
        self.transport = transport
        self.homegraph = homegraph or HomeGraph()
        self._syncs: dict[str, asyncio.Task] = {}     # demande de synchronisation en attente, par compte
        self._reported: dict[str, float] = {}         # dernier « en ligne » dit à Google, par console
        self._tasks: set[asyncio.Task] = set()

    @property
    def ready(self) -> bool:
        return bool(self.auth and self.client_id and self.client_secret and self.supabase_client_id)

    @property
    def callback(self) -> str:
        return f"{self.public_url}/google/callback"

    # ---------- connexion du compte (OAuth) ----------
    async def authorize(self, request: Request) -> Response:
        if not self.ready:
            return JSONResponse({"error": "google_home_disabled"}, 503)
        q = request.query_params
        redirect = q.get("redirect_uri", "")
        if q.get("client_id") != self.client_id or not redirect.startswith(GOOGLE_REDIRECTS):
            return JSONResponse({"error": "invalid_client"}, 400)
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(24)
        self.store.oauth_put(state, "state", {"redirect": redirect, "state": q.get("state", ""), "verifier": verifier})
        params = {"response_type": "code", "client_id": self.supabase_client_id, "redirect_uri": self.callback,
                  "state": state, "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
                  "code_challenge_method": "S256"}
        return RedirectResponse(f"{self.auth.issuer}/oauth/authorize?{urlencode(params)}", 302)

    async def oauth_callback(self, request: Request) -> Response:
        q = request.query_params
        p = self.store.oauth_pop(q.get("state", ""), "state", CODE_TTL)
        if p is None:
            return JSONResponse({"error": "expired", "error_description": "Connexion expirée : recommence depuis Google Home."}, 400)
        if not q.get("code"):
            return RedirectResponse(f"{p['redirect']}?{urlencode({'error': 'access_denied', 'state': p['state']})}", 302)
        code = secrets.token_urlsafe(32)
        self.store.oauth_put(code, "code", {"code": q["code"], "verifier": p["verifier"]})
        return RedirectResponse(f"{p['redirect']}?{urlencode({'code': code, 'state': p['state']})}", 302)

    def _client_ok(self, request: Request, form) -> bool:
        cid, secret = form.get("client_id", ""), form.get("client_secret", "")
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                cid, _, secret = base64.b64decode(header[6:]).decode().partition(":")
            except ValueError:
                return False
        return hmac.compare_digest(cid, self.client_id) and hmac.compare_digest(secret, self.client_secret)

    async def token(self, request: Request) -> Response:
        if not self.ready:
            return JSONResponse({"error": "google_home_disabled"}, 503)
        form = dict(parse_qsl((await request.body()).decode("utf-8", "replace")))  # formulaire OAuth (urlencoded)
        if not self._client_ok(request, form):
            return JSONResponse({"error": "invalid_client"}, 401)
        grant = form.get("grant_type")
        if grant == "authorization_code":
            c = self.store.oauth_pop(form.get("code", ""), "code", CODE_TTL)
            if c is None:
                return JSONResponse({"error": "invalid_grant"}, 400)
            body = {"grant_type": "authorization_code", "code": c["code"], "redirect_uri": self.callback,
                    "client_id": self.supabase_client_id, "code_verifier": c["verifier"]}
        elif grant == "refresh_token":
            body = {"grant_type": "refresh_token", "refresh_token": form.get("refresh_token", ""),
                    "client_id": self.supabase_client_id}
        else:
            return JSONResponse({"error": "unsupported_grant_type"}, 400)
        try:
            async with httpx.AsyncClient(timeout=15, transport=self.transport) as http:
                r = await http.post(f"{self.auth.issuer}/oauth/token", data=body,
                                    headers={"apikey": self.auth.publishable_key} if self.auth.publishable_key else {})
        except httpx.HTTPError:
            return JSONResponse({"error": "temporarily_unavailable"}, 503)
        if r.status_code >= 400:
            log.info("Google Home : échange de jeton refusé par Supabase (%s) %s", r.status_code, r.text[:200])
            return JSONResponse({"error": "invalid_grant"}, 400)
        t = r.json()
        out = {"token_type": "Bearer", "access_token": t["access_token"], "expires_in": t.get("expires_in", 3600)}
        if t.get("refresh_token"):
            out["refresh_token"] = t["refresh_token"]
        return JSONResponse(out)

    # ---------- appareils et commandes ----------
    def apps(self, c: Console) -> list[dict]:
        """Jeux déclarés à Google : favoris, jeux joués récemment, puis la bibliothèque (jeux connus d'abord), un seul par titre
        (« 1942 » en quatre versions : une entrée). Google ne lance que ce qu'il reconnaît dans cette liste."""
        favorites, _ = self.store.favorites(c.id, MAX_APPS)
        recent, _ = self.store.recent(c.id, MAX_APPS)
        library, _ = self.store.search([c.id], [], None, 100_000)
        out, seen = [], set()
        # Jeux connus (avec une fiche) avant les autres, au cas où la liste serait tronquée.
        for r in [*favorites, *recent, *sorted(library, key=lambda r: (not (r["description"] or r["year"]), r["title"].lower()))]:
            key = normalize_title(r["title"])
            if not key or key in seen:
                continue
            seen.add(key)
            names = synonyms(r["title"])
            # « le jeu Alien 3 » : sans ce mot, Google prend parfois le titre pour un film (Prime Video, YouTube…).
            game = {"fr": "jeu", "en": "game"}
            out.append({"key": f"g{r['id']}", "names": [
                {"lang": lang, "name_synonym": list(dict.fromkeys([*names, f"{game[lang]} {names[-1]}"] if lang == "fr"
                                                                   else [*names, f"{names[-1]} {game[lang]}"]))}
                for lang in LANGS]})
            if len(out) >= MAX_APPS:
                break
        return out

    def device(self, c: Console) -> dict:
        info = c.info
        return {
            "id": c.id, "type": "action.devices.types.GAME_CONSOLE", "traits": TRAITS,
            # Nom facile à dire et bien reconnu (« ouvre Zelda sur la console ») ; « jeu » pour « arrête le jeu » ; le nom ROMKADE de la console reste un surnom.
            "name": {"name": "Console", "defaultNames": ["Console ROMKADE"],
                     "nicknames": list(dict.fromkeys(["Console", "ma console", "jeu", "le jeu", "jeu vidéo",
                                                     "console rétro", "retro console", c.label]))},
            "willReportState": False,
            "deviceInfo": {"manufacturer": "ROMKADE", "model": info.get("model") or "console",
                           "swVersion": str(info.get("agent_version") or "")},
            "attributes": {"availableApplications": self.apps(c), "transportControlSupportedCommands": ["STOP"],
                           "supportActivityState": False, "supportPlaybackState": False,
                           "volumeMaxLevel": 100, "volumeCanMuteAndUnmute": True, "levelStepSize": 10},
        }

    # ---------- Home Graph : prévenir Google ----------
    def _spawn(self, coro) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:  # appelé hors boucle (tests synchrones) : rien à prévenir
            coro.close()
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def lists_changed(self, c: Console) -> None:
        """Favoris ou jeux récents changés : Google redemande la liste (une fois pour plusieurs changements)."""
        account = c.account_id
        if not account or not self.homegraph.ready or not self.store.google_linked(account):
            return
        if (t := self._syncs.get(account)) and not t.done():
            return

        async def later():
            await asyncio.sleep(SYNC_DELAY)
            self._syncs.pop(account, None)
            await self.homegraph.request_sync(account)

        try:
            self._syncs[account] = asyncio.get_running_loop().create_task(later())
        except RuntimeError:
            pass

    def report(self, c: Console, states: dict) -> None:
        if c.account_id and self.homegraph.ready and self.store.google_linked(c.account_id):
            self._spawn(self.homegraph.report_state(c.account_id, {c.id: states}))

    def console_seen(self, c: Console) -> None:
        """L'app ROMKADE s'est (re)connectée : « en ligne », dit à Google au plus toutes les 10 minutes."""
        if time.time() - self._reported.get(c.id, 0) > ONLINE_REPORT_EVERY:
            self._reported[c.id] = time.time()
            self.report(c, {"online": True, "on": True})

    def _game(self, c: Console, params: dict):
        key = str(params.get("newApplication") or "")
        if key.startswith("g") and key[1:].isdigit():
            row = self.store.game(int(key[1:]), c.account_id)
            if row is not None and row["console_id"] == c.id:
                return row
        name = params.get("newApplicationName") or key
        words = normalize_title(str(name)).split()
        rows, _ = self.store.search([c.id], words, None, 1) if words else ([], 0)
        return rows[0] if rows else None

    async def _execute_one(self, c: Console, command: str, params: dict) -> dict:
        name = command.rsplit(".", 1)[-1]
        if name in ("appSelect", "appSearch", "appInstall"):
            row = self._game(c, params)
            if row is None:
                return {"status": "ERROR", "errorCode": "noAvailableApp"}
            await self.relay.call(c.id, "launch", {"platform_dir": row["platform_dir"],
                                                   "relative_path": row["relative_path"], "slot": None}, 60)
            return {"status": "SUCCESS", "states": {"online": True, "on": True, "currentApplication": f"g{row['id']}"}}
        if name == "OnOff":
            if not params.get("on"):
                await self.relay.call(c.id, "quit", None, 45)
            return {"status": "SUCCESS", "states": {"online": True, "on": bool(params.get("on"))}}
        if name == "mediaStop":
            await self.relay.call(c.id, "quit", None, 45)
            return {"status": "SUCCESS", "states": {"online": True}}
        if name in ("setVolume", "volumeRelative", "mute"):
            if name == "mute":
                p = {"percent": None, "muted": bool(params.get("mute"))}
            elif name == "setVolume":
                p = {"percent": max(0, min(100, int(params.get("volumeLevel", 50)))), "muted": False}
            else:
                st = await self.relay.call(c.id, "status", None, 20)
                now = (st.get("volume") or {}).get("percent") or 50
                p = {"percent": max(0, min(100, now + 10 * int(params.get("relativeSteps", 1)))), "muted": False}
            await self.relay.call(c.id, "volume", p, 30)
            states = {"online": True, "isMuted": bool(p["muted"])}
            if p["percent"] is not None:
                states["currentVolume"] = p["percent"]
            return {"status": "SUCCESS", "states": states}
        return {"status": "ERROR", "errorCode": "functionNotSupported"}

    async def execute(self, c: Console, command: str, params: dict) -> dict:
        try:
            r = await self._execute_one(c, command, params)
            if r.get("status") == "SUCCESS" and r.get("states"):
                self.report(c, r["states"])
            return r
        except ConsoleOffline:
            return {"status": "OFFLINE", "errorCode": "deviceOffline"}
        except CommandTimeout:
            return {"status": "ERROR", "errorCode": "deviceTurnedOff"}
        except CommandFailed as exc:
            log.info("Google Home : %s refusé par la console : %s", command, exc.message)
            return {"status": "ERROR", "errorCode": "appLaunchFailed" if "app" in command.lower() else "hardError"}

    async def fulfillment(self, request: Request) -> Response:
        header = request.headers.get("authorization", "")
        claims = (await asyncio.to_thread(self.auth.verify, header[7:].strip())
                  if self.auth and header.lower().startswith("bearer ") else None)
        if claims is None:
            return JSONResponse({"error": "invalid_token"}, 401)
        account = self.store.ensure_account(account_id(claims), claims.get("email"))
        body = await request.json()
        request_id = body.get("requestId", "")
        mine = {c.id: c for c in self.store.consoles_of(account)}
        for item in body.get("inputs", []):
            intent = item.get("intent")
            payload = item.get("payload") or {}
            cmds = [ex.get("command", "").rsplit(".", 1)[-1] + str(ex.get("params") or {})
                    for cmd in payload.get("commands", []) for ex in cmd.get("execution", [])]
            log.warning("Google Home %s %s", (intent or "").rsplit(".", 1)[-1], " ".join(cmds))
            if intent == "action.devices.SYNC":
                self.store.set_google_link(account, True)
                return JSONResponse({"requestId": request_id, "payload": {
                    "agentUserId": account,
                    "devices": [self.device(c) for c in mine.values()]}})
            if intent == "action.devices.QUERY":
                devices = {}
                for d in payload.get("devices", []):
                    c = mine.get(d.get("id"))
                    if c is None:
                        devices[d.get("id")] = {"status": "ERROR", "errorCode": "deviceNotFound"}
                        continue
                    online = self.relay.online(c.id)
                    devices[c.id] = {"status": "SUCCESS", "online": online, "on": online, "isMuted": False,
                                     "currentApplication": ""}
                return JSONResponse({"requestId": request_id, "payload": {"devices": devices}})
            if intent == "action.devices.EXECUTE":
                results = []
                for cmd in payload.get("commands", []):
                    for d in cmd.get("devices", []):
                        c = mine.get(d.get("id"))
                        for ex in cmd.get("execution", []):
                            r = (await self.execute(c, ex.get("command", ""), ex.get("params") or {}) if c
                                 else {"status": "ERROR", "errorCode": "deviceNotFound"})
                            results.append({"ids": [d.get("id")], **r})
                return JSONResponse({"requestId": request_id, "payload": {"commands": results}})
            if intent == "action.devices.DISCONNECT":
                self.store.set_google_link(account, False)
                return JSONResponse({})
        return JSONResponse({"requestId": request_id, "payload": {"errorCode": "notSupported"}}, 400)
