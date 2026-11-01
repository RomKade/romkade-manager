"""Console de démonstration : vue par le cloud comme une vraie console (catalogue, ordres, jeux récents)."""

import asyncio
import os

import httpx

os.environ["ROMKADE_FETCH_CHEATS"] = "0"

from romkade_cloud import demo_console  # noqa: E402
from romkade_cloud.app import create_app  # noqa: E402
from romkade_cloud.relay import CommandFailed, Relay  # noqa: E402
from romkade_cloud.store import Store  # noqa: E402


def test_demo_console_answers_like_a_real_one(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_console, "POLL_WAIT", 1)
    store, relay = Store(tmp_path / "c.sqlite3"), Relay()
    store.ensure_account("sb:demo")
    c, secret = store.register_console_for("sb:demo", {}, "Console de démo")
    app = create_app(store, relay, "https://mcp.romkade.com")
    demo = demo_console.DemoConsole("http://test", secret, httpx.ASGITransport(app=app))

    async def scenario():
        async with httpx.AsyncClient(transport=demo.transport) as http:
            task = asyncio.create_task(demo.run_once(http))
            for _ in range(50):
                if relay.online(c.id) and store.search([c.id], [], None, 1)[1]:
                    break
                await asyncio.sleep(0.05)
            assert store.search([c.id], [], None, 100)[1] == len(demo_console.GAMES)
            assert store.favorites(c.id, 10)[1] == len(demo_console.FAVORITES)
            assert (await relay.call(c.id, "status", None, 5))["playing"] is False
            await relay.call(c.id, "launch", {"platform_dir": "NES", "relative_path": "Alter Ego (World).nes"}, 5)
            st = await relay.call(c.id, "status", None, 5)
            assert st["playing"] and st["relative_path"] == "Alter Ego (World).nes"
            assert (await relay.call(c.id, "volume", {"percent": 30, "muted": None}, 5))["percent"] == 30
            assert (await relay.call(c.id, "quit", None, 5))["result"] == "quit"
            try:
                await relay.call(c.id, "launch", {"platform_dir": "NES", "relative_path": "Inconnu.nes"}, 5)
                raise AssertionError("jeu inconnu accepté")
            except CommandFailed:
                pass
            await asyncio.sleep(0.2)
            assert store.recent(c.id, 5)[0][0]["relative_path"] == "Alter Ego (World).nes"
            task.cancel()

    asyncio.run(scenario())


def test_demo_console_screen():
    """Écran simulé : une vraie image PNG, avec le jeu en cours ou le menu (look_at_screen pour les relecteurs)."""
    import base64
    import io

    from PIL import Image

    from romkade_cloud.demo_console import GAMES, DemoConsole

    demo = DemoConsole("http://x", "s")
    assert demo.info()["capabilities"]["screenshot"]
    menu = base64.b64decode(demo.handle("screenshot", {})["png"])
    demo.handle("launch", {"platform_dir": GAMES[0][0], "relative_path": GAMES[0][1]})
    game = base64.b64decode(demo.handle("screenshot", {})["png"])
    assert Image.open(io.BytesIO(game)).size == (640, 480) and menu != game
