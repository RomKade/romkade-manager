"""Bout en bout : vrai serveur (uvicorn), vrai client MCP, faux agent de console qui répond aux ordres."""

import asyncio
import json
import os
import socket
import zipfile

import httpx
import pytest
import uvicorn
from mcp import Client

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

                assert "Aucune console" in error_text(await mcp.call_tool("search_games", {"query": "sonic"}))
                assert "Code inconnu" in error_text(await mcp.call_tool("pair_console", {"code": "ZZZZZZ"}))
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

                assert "RetroArch" in error_text(await mcp.call_tool("save_state", {}))
                assert data(await mcp.call_tool("quit_game", {}))["result"] == "quit"
                lib = data(await mcp.call_tool("library_overview", {}))
                assert lib["view"] == "library" and lib["games"] == 5

            # Le jeton d'un autre compte ne voit rien ; une adresse sans jeton valide n'existe pas.
            _, other = store.create_account("autre")
            async with Client(f"{base}/mcp/{other}") as mcp:
                assert data(await mcp.call_tool("list_consoles", {}))["consoles"] == []
                assert "introuvable" in error_text(await mcp.call_tool("launch_game", {"game_id": sonic}))
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
                assert "veille" in error_text(await mcp.call_tool("console_status", {}))
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
