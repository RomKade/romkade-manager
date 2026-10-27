"""Bout en bout : vrai serveur (uvicorn), vrai client MCP, faux agent de console qui répond aux ordres."""

import asyncio
import json
import os
import socket
import zipfile

import httpx
import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

os.environ["ROMKADE_FETCH_CHEATS"] = "0"

from romkade_cloud.app import create_app  # noqa: E402
from romkade_cloud.relay import Relay  # noqa: E402
from romkade_cloud.store import Store  # noqa: E402

FILES = [
    ["MD", "Sonic The Hedgehog (USA, Europe).md", 524288],
    ["MD", "Sonic The Hedgehog 2 (World).md", 1048576],
    ["MD", "Imgs/Sonic The Hedgehog (USA, Europe).png", 2000],
    ["SFC", "Super Mario World (USA).sfc", 524288],
    ["SFC", "Super Mario World (USA).srm", 8192],
    ["PS", "Final Fantasy VII (Europe).m3u", 100],
    ["PS", "Final Fantasy VII (Europe) (Disc 1).chd", 1],
    ["APPS", "Horloge.sh", 100],
    ["FBNEO", "atetris.zip", 50000],
]

CHT = """cheats = 2
cheat0_desc = "Infinite Lives"
cheat0_code = "ACJT-AA3G"
cheat0_enable = false
cheat1_desc = "Invincibility"
cheat1_code = "AB2T-AA4E"
cheat1_enable = false
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ROMKADE_DATA_DIR", str(tmp_path))
    with zipfile.ZipFile(tmp_path / "cheats.zip", "w") as z:
        z.writestr("Sega - Mega Drive - Genesis/Sonic The Hedgehog (USA, Europe) (Game Genie).cht", CHT)
    store = Store(tmp_path / "cloud.sqlite3")
    _, token = store.create_account("test")
    return store, token


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def serving(store: Store, relay: Relay):
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    app = create_app(store, relay, public_url=base)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return base, server, task


class FakeAgent:
    """Fait ce que fait romkade_agent.py, côté réseau ; les ordres reçus sont notés dans `received`."""

    def __init__(self, base: str):
        self.http = httpx.AsyncClient(base_url=base, timeout=30)
        self.secret = None
        self.received: list[dict] = []
        self.playing = None
        self.saves: list[dict] | None = []  # None : agent d'avant l'ordre « saves »

    async def hello(self) -> dict:
        headers = {"Authorization": f"Bearer {self.secret}"} if self.secret else {}
        r = (await self.http.post("/agent/hello", json={"model": "RG35xxPRO", "firmware": "Anbernic",
                                                         "profile": "anbernic-stock-mod"}, headers=headers)).json()
        self.secret = r.get("secret") or self.secret
        return r

    @property
    def auth(self) -> dict:
        return {"Authorization": f"Bearer {self.secret}"}

    async def upload(self, files) -> dict:
        return (await self.http.post("/agent/catalog", json={"files": files}, headers=self.auth)).json()

    async def favorites(self, favs) -> dict:
        return (await self.http.post("/agent/favorites", json={"favorites": favs}, headers=self.auth)).json()

    async def serve(self) -> None:
        while True:
            r = (await self.http.get("/agent/poll", params={"wait": 1}, headers=self.auth)).json()
            cmd = r.get("command")
            if not cmd:
                continue
            self.received.append(cmd)
            if cmd["action"] == "launch":
                self.playing = cmd["params"]
                reply = {"ok": True, "result": {"launching": "x"}}
            elif cmd["action"] == "status":
                p = self.playing or {}
                reply = {"ok": True, "result": {"playing": bool(p), "menu": not p, "volume": {"percent": 40},
                                                "platform_dir": p.get("platform_dir"),
                                                "relative_path": p.get("relative_path")}}
            elif cmd["action"] == "saves":
                names = set(cmd["params"]["names"])
                reply = ({"ok": False, "error": {"code": "unknown_action", "message": "Action inconnue : saves"}}
                         if self.saves is None else
                         {"ok": True, "result": {"saves": [x for x in self.saves if x["name"].lower() in names]}})
            elif cmd["action"] == "save_state":
                reply = {"ok": False, "error": {"code": "no_retroarch_game", "message": "Aucun jeu RetroArch en cours"}}
            else:
                reply = {"ok": True, "result": {"result": "quit"}}
            await self.http.post("/agent/result", json={"id": cmd["id"], **reply}, headers=self.auth)


def data(result) -> dict:
    """Données pour l'interface (structuredContent : sans lui, ChatGPT n'a rien à afficher)."""
    assert not result.is_error, result.content
    assert result.structured_content is not None
    text = json.loads(result.content[0].text)  # ce que lit le modèle : sans images ni résumés
    assert "cover" not in result.content[0].text and "description" not in text.get("game", {})
    return result.structured_content


def error_text(result) -> str:
    assert result.is_error
    return result.content[0].text


def error_code(result) -> str:
    """Code de l'erreur (traduit par l'interface) ; pour une erreur de la console, celui de l'agent."""
    assert result.is_error and result.content[0].text.isascii()  # message en anglais
    err = result.structured_content
    return err["reason"] if err["error"] == "console_failed" else err["error"]


def test_pairing_catalog_cheats_and_play(env):
    store, token = env

    async def scenario():
        base, server, task = await serving(store, Relay())
        agent = FakeAgent(base)
        try:
            first = await agent.hello()
            assert first["paired"] is False and len(first["pairing_code"]) == 6 and agent.secret
            assert (await agent.upload(FILES))["games"] == 5  # ni image, ni sauvegarde, ni piste du .m3u, ni app
            loop = asyncio.create_task(agent.serve())

            async with Client(f"{base}/{token}") as mcp:
                assert mcp.server_info.title == "ROMKADE"
                tools = (await mcp.list_tools()).tools
                assert {"pair_console", "search_games", "game_details", "launch_game", "get_cheats",
                        "set_volume"} <= {t.name for t in tools}
                # Chaque outil affiche l'interface ROMKADE (MCP Apps).
                assert all((t.meta or {}).get("ui", {}).get("resourceUri") == "ui://romkade/app.html" for t in tools)
                ui = (await mcp.read_resource("ui://romkade/app.html")).contents[0]
                assert ui.mime_type == "text/html;profile=mcp-app" and "ui/initialize" in ui.text
                assert "__ROMKADE_BASE__" not in ui.text and "Tous droits réservés" in ui.text

                # Annuaires d'apps : chaque outil a un titre et les trois indicateurs explicites (exigés par ChatGPT).
                for tool in (await mcp.list_tools()).tools:
                    a = tool.annotations
                    assert tool.title and tool.title.isascii() and len(tool.name) <= 64
                    assert all(isinstance(h, bool) for h in (a.read_only_hint, a.destructive_hint, a.open_world_hint))
                    assert not (a.read_only_hint and a.destructive_hint)
                none = await mcp.call_tool("search_games", {"query": "sonic"})
                # Pas de console : l'utilisateur repart avec le guide et le téléchargement du Manager.
                assert error_code(none) == "no_console" and none.structured_content["help"].startswith("https://romkade.com/")
                assert none.structured_content["download"] in none.content[0].text
                assert error_code(await mcp.call_tool("pair_console", {"code": "ZZZZZZ"})) == "bad_code"
                paired = data(await mcp.call_tool("pair_console", {"code": first["pairing_code"].lower(),
                                                                    "name": "Ma RG35XX"}))
                mine = paired["consoles"][0]
                assert paired["view"] == "consoles" and mine["console"] == "Ma RG35XX" and mine["games"] == 5

                found = data(await mcp.call_tool("search_games", {"query": "Sonic", "platform": "Mega Drive"}))
                assert found["view"] == "games" and found["total"] == 2
                assert found["games"][0]["title"] == "Sonic The Hedgehog"
                assert found["games"][0]["cover"].startswith(base + "/art/")
                # Arcade : vrai titre (et toujours trouvé par le nom du fichier), genre, année.
                tetris = data(await mcp.call_tool("search_games", {"query": "atetris"}))["games"][0]
                assert tetris["title"] == "Tetris" and tetris["year"] == 1988 and tetris["genre"] == "reflexion"
                assert data(await mcp.call_tool("search_games", {"genre": "puzzle"}))["total"] == 1
                sheet = data(await mcp.call_tool("game_details", {"game_id": tetris["game_id"]}))
                assert sheet["view"] == "game" and sheet["game"]["developer"] == "Atari Games"
                sonic = found["games"][0]["game_id"]
                assert data(await mcp.call_tool("search_games", {"platform": "snes"}))["total"] == 1

                overview = data(await mcp.call_tool("library_overview", {}))
                assert {s["platform"] for s in overview["systems"]} >= {"Mega Drive / Genesis", "Super Nintendo"}

                cheats = data(await mcp.call_tool("get_cheats", {"game_id": sonic, "search": "lives"}))
                assert cheats["cheats"] == [{"description": "Infinite Lives", "code": "ACJT-AA3G"}]

                launched = data(await mcp.call_tool("launch_game", {"game_id": sonic, "resume": True}))
                assert launched["game"]["title"] == "Sonic The Hedgehog"
                assert agent.received[-1]["params"] == {"platform_dir": "MD", "slot": "auto",
                                                        "relative_path": "Sonic The Hedgehog (USA, Europe).md"}
                assert launched["view"] == "now" and launched["launching"]
                st = data(await mcp.call_tool("console_status", {}))
                assert st["playing"] and st["game"]["title"] == "Sonic The Hedgehog" and st["volume"]["percent"] == 40

                r = await mcp.call_tool("save_state", {})
                assert "RetroArch" in error_text(r) and r.structured_content["error"] == "console_failed"
                assert data(await mcp.call_tool("quit_game", {}))["result"] == "quit"
                lib = data(await mcp.call_tool("library_overview", {}))
                assert lib["view"] == "library" and lib["games"] == 5

            # Le jeton d'un autre compte ne voit rien ; une adresse sans jeton valide n'existe pas.
            _, other = store.create_account("autre")
            async with Client(f"{base}/mcp/{other}") as mcp:
                assert data(await mcp.call_tool("list_consoles", {}))["consoles"] == []
                assert error_code(await mcp.call_tool("launch_game", {"game_id": sonic})) == "unknown_game"
            async with httpx.AsyncClient() as h:
                font = await h.get(f"{base}/fonts/archivo.woff2")
                assert font.status_code == 200 and font.headers["access-control-allow-origin"] == "*"
                assert (await h.get(f"{base}/consoles/MD.webp")).status_code == 200
                assert (await h.get(f"{base}/romkade-logo.webp")).status_code == 200
                assert (await h.get(f"{base}/app.py")).status_code == 404
                assert (await h.post(f"{base}/mcp/{'x' * 30}", json={})).status_code == 404
                assert (await h.post(f"{base}/mcp", json={})).status_code == 404
                assert (await h.post(f"{base}/{'y' * 43}", json={})).status_code == 404
                assert (await h.get(f"{base}/agent/poll", headers={"Authorization": "Bearer nope"})).status_code == 401

            # Une fois appairée, la console ne reçoit plus de code.
            assert "pairing_code" not in await agent.hello()
            loop.cancel()
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())


def test_console_offline_is_reported_as_asleep(env):
    store, token = env

    async def scenario():
        relay = Relay()
        base, server, task = await serving(store, relay)
        agent = FakeAgent(base)
        try:
            code = (await agent.hello())["pairing_code"]
            await agent.upload(FILES)
            async with Client(f"{base}/{token}") as mcp:
                data(await mcp.call_tool("pair_console", {"code": code}))
                # Jamais venue chercher d'ordre : hors ligne. Le catalogue reste consultable.
                assert error_code(await mcp.call_tool("console_status", {})) == "console_asleep"
                assert data(await mcp.call_tool("search_games", {"query": "mario"}))["total"] == 1
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())


def test_relay_ignores_results_from_another_console():
    async def scenario():
        relay = Relay()
        relay._last_poll["a"] = relay._last_poll["b"] = 1e12
        call = asyncio.create_task(relay.call("a", "status", timeout=2))
        cmd = await relay.poll("a", wait=1)
        assert relay.result("b", cmd["id"], {"ok": True}) is False
        assert relay.result("a", cmd["id"], {"ok": True, "result": {"x": 1}}) is True
        assert await call == {"x": 1}

    asyncio.run(scenario())


class FakeAuth:
    """Supabase Auth simulé : « bon-jeton » est valide (utilisateur u-123), le reste refusé."""

    url = "https://projet.supabase.co"
    issuer = "https://projet.supabase.co/auth/v1"
    publishable_key = "sb_publishable_test"
    metadata_url = issuer + "/.well-known/oauth-authorization-server"

    def verify(self, token):
        return {"sub": "u-123", "email": "joueur@example.com", "role": "authenticated"} if token == "bon-jeton" else None


def test_openai_domain_challenge(env, monkeypatch):
    store, _ = env

    async def scenario():
        base, server, task = await serving(store, Relay())
        try:
            async with httpx.AsyncClient() as h:
                assert (await h.get(f"{base}/.well-known/openai-apps-challenge")).status_code == 404
                monkeypatch.setenv("ROMKADE_OPENAI_CHALLENGE", "tok-123\n")
                r = await h.get(f"{base}/.well-known/openai-apps-challenge")
                assert r.status_code == 200 and r.text == "tok-123"
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())


def test_oauth_accounts(env):
    store, token = env

    async def scenario():
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(create_app(store, Relay(), public_url=base, auth=FakeAuth()),
                                               host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)
        try:
            async with httpx.AsyncClient() as h:
                # Sans jeton : 401 et adresse des métadonnées (RFC 9728) pour lancer la connexion.
                r = await h.post(f"{base}/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                 headers={"accept": "application/json, text/event-stream"})
                assert r.status_code == 401
                assert f'resource_metadata="{base}/.well-known/oauth-protected-resource"' in r.headers["www-authenticate"]
                assert (await h.post(f"{base}/", json={}, headers={"authorization": "Bearer faux"})).status_code == 401
                # Avec OAuth, les adresses à jeton du prototype sont coupées (exigence des annuaires d'apps).
                assert (await h.post(f"{base}/{token}", json={})).status_code == 404
                meta = (await h.get(f"{base}/.well-known/oauth-protected-resource")).json()
                assert meta["resource"] == base and meta["authorization_servers"] == [FakeAuth.issuer]
                page = await h.get(f"{base}/oauth/consent?authorization_id=abc")  # page déplacée sur le site
                assert page.headers["location"] == "https://romkade.com/authentification/?authorization_id=abc"
                assert (await h.get(f"{base}/")).status_code == 302  # navigateur : vers romkade.com
            # Avec un jeton valide : compte « sb:u-123 » créé, sans console pour l'instant.
            transport = streamable_http_client(f"{base}/", http_client=httpx2.AsyncClient(
                headers={"authorization": "Bearer bon-jeton"}))
            async with Client(transport) as mcp:
                assert error_code(await mcp.call_tool("library_overview", {})) == "no_console"
            assert any(a["id"] == "sb:u-123" and a["label"] == "joueur@example.com" for a in store.accounts())
            # Les consoles d'un compte à jeton passent au compte ROMKADE.
            old = store.create_account("ancien")[0]
            c, _ = store.register_console({})
            store.pair(store.pairing_code(c.id), old)
            assert store.move_consoles(old, "sb:u-123") == 1 and store.consoles_of("sb:u-123")[0].id == c.id
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())


def test_mcp_analytics_never_sends_call_content(env, monkeypatch):
    """Statistiques PostHog : mêmes outils qu'avant (aucun paramètre ajouté), ni arguments ni réponses envoyés."""
    import posthog

    store, token = env
    sent = []
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
    monkeypatch.setattr(posthog.Posthog, "capture", lambda self, event, **kw: sent.append({"event": event, **kw}))

    async def scenario():
        base, server, task = await serving(store, Relay())
        try:
            async with Client(f"{base}/{token}") as mcp:
                tools = (await mcp.list_tools()).tools
                assert all("context" not in (t.input_schema.get("properties") or {}) for t in tools)
                await mcp.call_tool("search_games", {"query": "Sonic"})
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())
    calls = [e for e in sent if e["event"] == "$mcp_tool_call"]
    assert calls and calls[0]["properties"]["$mcp_tool_name"] == "search_games"
    assert "Sonic" not in json.dumps(sent, default=str)
    assert not {"$mcp_parameters", "$mcp_response", "$mcp_intent"} & {k for e in sent for k in e.get("properties", {})}


def test_account_api_for_the_manager(env):
    store, _ = env

    async def scenario():
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(create_app(store, Relay(), public_url=base, auth=FakeAuth()),
                                               host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)
        try:
            ok = {"authorization": "Bearer bon-jeton", "origin": "http://127.0.0.1:8765"}
            async with httpx.AsyncClient(base_url=base) as h:
                assert (await h.get("/api/me/consoles")).status_code == 401
                pre = await h.options("/api/me/consoles", headers={"origin": "http://127.0.0.1:5173",
                                                                   "access-control-request-method": "POST"})
                assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
                assert (await h.options("/api/me/consoles", headers={"origin": "https://evil.example"})).status_code == 403
                # Liaison sans code : console déjà rattachée au compte, secret remis pour son agent.
                r = await h.post("/api/me/consoles", headers=ok, json={"name": "Ma RG", "model": "RG35xxPRO"})
                assert r.status_code == 201 and r.headers["access-control-allow-origin"] == "http://127.0.0.1:8765"
                linked = r.json()
                assert linked["console"]["name"] == "Ma RG" and linked["secret"] and linked["server"] == base
                assert store.console_for_secret(linked["secret"]).account_id == "sb:u-123"
                again = (await h.post("/api/me/consoles", headers=ok, json={"secret": linked["secret"]})).json()
                assert again["reused"] and again["console"]["id"] == linked["console"]["id"]  # pas de doublon
                limit = await h.post("/api/me/consoles", headers=ok, json={"model": "RG40XXV"})
                assert limit.status_code == 409 and limit.json()["error"] == "console_limit"  # une console par compte
                listed = (await h.get("/api/me/consoles", headers=ok)).json()["consoles"]
                assert [c["name"] for c in listed] == ["Ma RG"]
                cid = listed[0]["id"]
                assert (await h.patch(f"/api/me/consoles/{cid}", headers=ok, json={"name": "Salon"})).json()["console"]["name"] == "Salon"
                other = store.register_console({})[0]
                assert (await h.delete(f"/api/me/consoles/{other.id}", headers=ok)).status_code == 404  # pas à moi
                assert (await h.delete(f"/api/me/consoles/{cid}", headers=ok)).json() == {"deleted": cid}
                assert (await h.delete("/api/me", headers=ok)).status_code == 503  # sans clé d'administration
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())


def test_favorites_and_saves(env):
    """Favoris posés par le Manager (envoyés par l'agent) et sauvegardes d'un jeu lues sur la console."""
    store, token = env

    async def scenario():
        base, server, task = await serving(store, Relay())
        agent = FakeAgent(base)
        try:
            code = (await agent.hello())["pairing_code"]
            await agent.upload(FILES)
            assert (await agent.favorites([["SFC", "Super Mario World (USA).sfc"], ["MD", "Sonic The Hedgehog 2 (World).md"],
                                           ["GBA", "Plus sur la carte.gba"]]))["favorites"] == 3
            async with Client(f"{base}/{token}") as mcp:
                data(await mcp.call_tool("pair_console", {"code": code}))
                # Console éteinte : les favoris restent consultables, les sauvegardes ne sont pas vérifiées.
                favs = data(await mcp.call_tool("favorite_games", {}))
                assert favs["view"] == "games" and favs["favorites"] and favs["total"] == 2
                assert [g["title"] for g in favs["games"]] == ["Super Mario World", "Sonic The Hedgehog 2"]
                mario = favs["games"][0]["game_id"]
                sheet = data(await mcp.call_tool("game_details", {"game_id": mario}))
                assert sheet["game"]["favorite"] and sheet["saves"] == {"checked": False, "reason": "console_offline"}
                assert data(await mcp.call_tool("library_overview", {}))["favorites"] == 2

                loop = asyncio.create_task(agent.serve())
                await asyncio.sleep(0.2)
                agent.saves = [
                    {"platform": "SFC", "name": "Super Mario World (USA)", "kind": "sram", "slot": None, "modified": 1760000000},
                    {"platform": "SFC", "name": "Super Mario World (USA)", "kind": "state", "slot": "auto", "modified": 1760100000},
                    {"platform": "MD", "name": "Super Mario World (USA)", "kind": "state", "slot": "0", "modified": 1760200000},
                ]
                saves = data(await mcp.call_tool("game_details", {"game_id": mario}))["saves"]
                assert saves["checked"] and saves["has_save"] and saves["in_game_save"]["saved_at"].startswith("2025-10-09")
                assert [x["slot"] for x in saves["save_states"]] == ["auto"]          # pas celle d'une autre console
                assert saves["last_saved_at"].startswith("2025-10-10")
                assert agent.received[-1]["params"]["names"] == ["super mario world (usa)", "super mario world (usa).sfc"]
                sonic = data(await mcp.call_tool("search_games", {"query": "Sonic The Hedgehog"}))["games"][0]["game_id"]
                other = data(await mcp.call_tool("game_details", {"game_id": sonic}))
                assert not other["game"]["favorite"] and other["saves"]["checked"] and not other["saves"]["has_save"]

                agent.saves = None  # app ROMKADE de la console pas encore mise à jour
                assert data(await mcp.call_tool("game_details", {"game_id": mario}))["saves"]["reason"] == "app_update_needed"

                # Le Manager retire un favori : l'agent renvoie la liste.
                await agent.favorites([["MD", "Sonic The Hedgehog 2 (World).md"]])
                assert [g["title"] for g in data(await mcp.call_tool("favorite_games", {}))["games"]] == ["Sonic The Hedgehog 2"]
                loop.cancel()
            async with httpx.AsyncClient() as h:
                assert (await h.post(f"{base}/agent/favorites", json={"favorites": []},
                                     headers={"Authorization": "Bearer nope"})).status_code == 401
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())

