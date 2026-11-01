"""Soluces (guide.py) : outil MCP game_guide, /api/guide pour le Manager, et l'écran de la console (look_at_screen)."""

import asyncio
import base64
import io
import json

import httpx
import uvicorn
from mcp import Client
from PIL import Image

from app.services.knowledge import Fetched
from romkade_cloud.app import create_app
from romkade_cloud.guide import Guides, pick
from romkade_cloud.relay import Relay
from test_cloud import FILES, FakeAgent, FakeAuth, env, free_port  # noqa: F401 — fixture env

CHUNKS = [
    {"source": "wikipedia", "lang": "en", "page": "Sonic the Hedgehog (1991 video game)", "section": "Gameplay",
     "url": "https://en.wikipedia.org/wiki/Sonic", "text": "Sonic runs through zones and fights Doctor Robotnik as boss."},
    {"source": "strategywiki", "lang": "en", "page": "Sonic the Hedgehog/Marble Zone", "section": "Act 3 boss",
     "url": "https://strategywiki.org/wiki/Sonic/Marble", "text": "Robotnik drops fire: stand on the left block and "
     "jump on the boss when it passes over you."},
    {"source": "strategywiki", "lang": "en", "page": "Sonic the Hedgehog/Controls", "section": "Controls",
     "url": "https://strategywiki.org/wiki/Sonic/Controls", "text": "Press any button to jump; hold down to roll."},
]


class FakeFetcher:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def fetch(self, title, directory):
        self.calls.append((title, directory))
        if "Mario" in title:
            return Fetched("not_found")
        return Fetched("found", "Q1", {"strategywiki": "Sonic_the_Hedgehog"}, [dict(c) for c in CHUNKS])


def test_pick_prefers_guides_and_matching_words():
    assert [c["section"] for c in pick(CHUNKS, "Marble zone boss", "MD", 2)] == ["Act 3 boss", "Gameplay"]
    # Sans recherche : le début de la soluce, StrategyWiki avant l'encyclopédie.
    assert pick(CHUNKS, "", "MD")[0]["source"] == "strategywiki"


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 90)).save(out, "PNG")
    return out.getvalue()


def test_guide_and_screen_tools(env):  # noqa: F811
    store, token = env
    fetcher = FakeFetcher()

    async def scenario():
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        app = create_app(store, Relay(), public_url=base, auth=FakeAuth(), token_urls=True,
                         guides=Guides(store, fetcher))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)
        agent = FakeAgent(base)
        try:
            first = await agent.hello()
            await agent.upload(FILES)
            loop = asyncio.create_task(agent.serve())
            async with Client(f"{base}/{token}") as mcp:
                tools = {t.name: t for t in (await mcp.list_tools()).tools}
                assert tools["game_guide"].annotations.read_only_hint and tools["game_guide"].annotations.open_world_hint
                assert tools["look_at_screen"].annotations.read_only_hint
                await mcp.call_tool("pair_console", {"code": first["pairing_code"]})
                found = (await mcp.call_tool("search_games", {"query": "Sonic The Hedgehog", "platform": "MD"}))
                sonic = found.structured_content["games"][0]["game_id"]

                r = await mcp.call_tool("game_guide", {"game_id": sonic, "query": "marble zone boss"})
                assert not r.is_error
                d = r.structured_content
                assert d["view"] == "guide" and d["status"] == "found"
                assert d["passages"][0]["section"] == "Act 3 boss" and d["passages"][0]["license"] == "CC BY-SA 4.0"
                assert {s["source"] for s in d["sources"]} == {"wikipedia", "strategywiki"}
                assert "jump on the boss" in r.content[0].text  # le modèle lit les passages
                await mcp.call_tool("game_guide", {"game_id": sonic, "query": "controls"})
                assert fetcher.calls == [("Sonic The Hedgehog", "MD")]  # gardée : récupérée une seule fois

                mario = (await mcp.call_tool("search_games", {"query": "mario"})).structured_content["games"][0]
                none = (await mcp.call_tool("game_guide", {"game_id": mario["game_id"]})).structured_content
                assert none["status"] == "not_found" and none["passages"] == [] and none["note"]

                # Écran : agent trop ancien, puis capture renvoyée en image (JPEG) avec le jeu en cours.
                old = await mcp.call_tool("look_at_screen", {})
                assert old.is_error and old.structured_content["reason"] == "unknown_action"
                agent.screen = png()
                await mcp.call_tool("launch_game", {"game_id": sonic})
                shot = await mcp.call_tool("look_at_screen", {})
                assert not shot.is_error
                image, text = shot.content
                assert image.type == "image" and image.mime_type == "image/jpeg"
                assert base64.b64decode(image.data)[:2] == b"\xff\xd8"
                assert "base64" not in text.text and json.loads(text.text)["game"]["title"] == "Sonic The Hedgehog"
                assert shot.structured_content["view"] == "screen"
                assert shot.structured_content["image"].startswith("data:image/jpeg;base64,")

            # API pour l'assistant du Manager : même soluce, par titre et dossier, avec le jeton de session.
            ok = {"authorization": "Bearer bon-jeton"}
            async with httpx.AsyncClient(base_url=base) as h:
                params = {"title": "Sonic The Hedgehog", "platform": "MD", "q": "boss"}
                assert (await h.get("/api/guide", params=params)).status_code == 401
                assert (await h.get("/api/guide", params={**params, "platform": "nope"}, headers=ok)).status_code == 400
                g = (await h.get("/api/guide", params=params, headers=ok)).json()
                assert g["status"] == "found" and g["passages"][0]["section"] == "Act 3 boss"
                assert len(fetcher.calls) == 2  # Mario en plus ; Sonic déjà gardé
            loop.cancel()
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())
