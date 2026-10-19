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
    server = uvicorn.Server(uvicorn.Config(create_app(store, relay), host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return f"http://127.0.0.1:{port}", server, task


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
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


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
            assert (await agent.upload(FILES))["games"] == 4  # ni image, ni sauvegarde, ni piste du .m3u, ni app
            loop = asyncio.create_task(agent.serve())

            async with Client(f"{base}/mcp/{token}") as mcp:
                assert mcp.server_info.title == "ROMKADE"
                names = {t.name for t in (await mcp.list_tools()).tools}
                assert {"pair_console", "search_games", "launch_game", "get_cheats", "set_volume"} <= names

                assert "Aucune console" in error_text(await mcp.call_tool("search_games", {"query": "sonic"}))
                assert "Code inconnu" in error_text(await mcp.call_tool("pair_console", {"code": "ZZZZZZ"}))
                paired = data(await mcp.call_tool("pair_console", {"code": first["pairing_code"].lower(),
                                                                    "name": "Ma RG35XX"}))
                assert paired["console"] == "Ma RG35XX" and paired["online"] and paired["games"] == 4

                found = data(await mcp.call_tool("search_games", {"query": "Sonic", "platform": "Mega Drive"}))
                assert found["total"] == 2 and found["games"][0]["title"] == "Sonic The Hedgehog"
                sonic = found["games"][0]["game_id"]
                assert data(await mcp.call_tool("search_games", {"platform": "snes"}))["total"] == 1

                overview = data(await mcp.call_tool("library_overview", {}))
                assert {s["platform"] for s in overview["systems"]} >= {"Mega Drive / Genesis", "Super Nintendo"}

                cheats = data(await mcp.call_tool("get_cheats", {"game_id": sonic, "search": "lives"}))
                assert cheats["cheats"] == [{"description": "Infinite Lives", "code": "ACJT-AA3G"}]

                launched = data(await mcp.call_tool("launch_game", {"game_id": sonic, "resume": True}))
                assert launched["launched"] == "Sonic The Hedgehog"
                assert agent.received[-1]["params"] == {"platform_dir": "MD", "slot": "auto",
                                                        "relative_path": "Sonic The Hedgehog (USA, Europe).md"}
                st = data(await mcp.call_tool("console_status", {}))
                assert st["playing"] and st["game"]["title"] == "Sonic The Hedgehog"

                assert "RetroArch" in error_text(await mcp.call_tool("save_state", {}))
                assert data(await mcp.call_tool("quit_game", {}))["result"] == "quit"

            # Le jeton d'un autre compte ne voit rien ; une adresse sans jeton valide n'existe pas.
            _, other = store.create_account("autre")
            async with Client(f"{base}/mcp/{other}") as mcp:
                assert data(await mcp.call_tool("list_consoles", {}))["consoles"] == []
                assert "introuvable" in error_text(await mcp.call_tool("launch_game", {"game_id": sonic}))
            async with httpx.AsyncClient() as h:
                assert (await h.post(f"{base}/mcp/{'x' * 30}", json={})).status_code == 404
                assert (await h.post(f"{base}/mcp", json={})).status_code == 404
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
            async with Client(f"{base}/mcp/{token}") as mcp:
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
