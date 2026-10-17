import io
import urllib.parse

import httpx
from PIL import Image

from app.services.boxart import url_for
from tests.test_catalog import games, sync


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 90), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_url_replaces_forbidden_characters():
    assert url_for("MAME", "Street Fighter II: The World Warrior (World 910522)") == (
        "https://thumbnails.libretro.com/MAME/Named_Boxarts/Street%20Fighter%20II_%20The%20World%20Warrior%20%28World%20910522%29.png")


async def test_boxart_downloaded_once_then_cached(app_factory, ssh_server):
    asked = []

    def libretro(request: httpx.Request) -> httpx.Response:
        name = urllib.parse.unquote(request.url.path)
        asked.append(name)
        if name == "/Nintendo - Super Nintendo Entertainment System/Named_Boxarts/Super Mario World (USA).png":
            return httpx.Response(200, content=png(), headers={"content-type": "image/png"})
        return httpx.Response(404, text="not found", headers={"content-type": "text/html"})

    app = app_factory()
    app.state.boxart.transport = httpx.MockTransport(libretro)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        by_title = {g["title"]: g for g in (await games(c))["items"]}
        mario, sonic = by_title["Super Mario World"], by_title["Sonic The Hedgehog"]
        assert mario["boxart_url"] == f"/api/games/{mario['id']}/boxart"
        assert by_title["mystery"]["boxart_url"] is None  # dossier inconnu : pas de banque

        r = await c.get(mario["boxart_url"])
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
        assert (await c.get(mario["boxart_url"], params={"size": "full"})).headers["content-type"] == "image/png"
        n = len(asked)
        await c.get(mario["boxart_url"])
        assert len(asked) == n  # servi depuis le cache

        r = await c.get(sonic["boxart_url"])
        assert r.status_code == 404 and r.json()["error"]["code"] == "boxart_not_found"
        n = len(asked)
        await c.get(sonic["boxart_url"])
        assert len(asked) == n  # introuvable : noté, pas redemandé
    assert ssh_server["sftp"].write_attempts == []


async def test_boxart_network_down_is_not_remembered(app_factory):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    app = app_factory()
    app.state.boxart.transport = httpx.MockTransport(down)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        mario = next(g for g in (await games(c, q="mario"))["items"])
        r = await c.get(mario["boxart_url"])
        assert r.status_code == 502 and r.json()["error"]["code"] == "boxart_unreachable"
        assert not list(app.state.boxart.root.rglob("*.missing"))
