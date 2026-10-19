import base64

import httpx

from app.device import screen
from tests.test_catalog import sync
from tests.test_play import FakeConsole, make

PNG = screen.PNG_MAGIC + b"fake image"
MARIO = "/mnt/mmc/Roms/SFC/Super Mario World (USA).smc"


class ScreenConsole(FakeConsole):
    """Console qui sait aussi lire son écran (ou pas : `broken`)."""

    def __init__(self, playing=None, broken=False):
        super().__init__(playing=playing)
        self.broken = broken

    async def __call__(self, client, command, timeout=20):
        if command == screen.COMMAND:
            self.commands.append(command)
            if self.broken:
                return 0, "PermissionError: [Errno 13] /dev/fb0\n"
            return 0, "@@PNG " + base64.b64encode(PNG).decode() + "\n"
        return await super().__call__(client, command, timeout)


async def test_take_list_get_delete(app_factory):
    console = ScreenConsole(playing=MARIO)
    async with make(app_factory, console) as c:
        await sync(c)
        r = await c.post("/api/device/screenshot")
        assert r.status_code == 200, r.text
        taken = r.json()
        assert taken["title"] == "Super Mario World" and taken["shot"]["url"].startswith(f"/api/screenshots/{taken['game_id']}/")
        await c.post("/api/device/screenshot")  # même seconde : un second nom
        shots = (await c.get(f"/api/games/{taken['game_id']}/screenshots")).json()
        assert len(shots) == 2 and len({s["name"] for s in shots}) == 2
        img = await c.get(shots[0]["url"])
        assert img.status_code == 200 and img.content == PNG and img.headers["content-type"] == "image/png"
        everything = (await c.get("/api/screenshots")).json()
        assert [(g["title"], g["platform_code"], len(g["shots"])) for g in everything] == [("Super Mario World", "SFC", 2)]
        for s in shots:
            assert (await c.delete(s["url"])).status_code == 204
        assert (await c.get("/api/screenshots")).json() == []
        assert (await c.get(shots[0]["url"])).status_code == 404
        # Rien n'est écrit sur la carte : la commande lit l'écran et renvoie l'image
        assert "/dev/fb0" in screen.COMMAND and ">" not in screen.COMMAND.split("2>&1")[-1]


async def test_refused_without_game_or_on_failure(app_factory):
    console = ScreenConsole()
    async with make(app_factory, console) as c:
        tracker = c._transport.app.state.tracker  # état « jeu en cours » gardé quelques secondes : on l'oublie
        await sync(c)
        r = await c.post("/api/device/screenshot")
        assert r.status_code == 409 and r.json()["error"]["code"] == "no_game_running"
        console.playing = "/mnt/mmc/Roms/SFC/Inconnu.smc"
        tracker.invalidate()
        r = await c.post("/api/device/screenshot")
        assert r.status_code == 409 and r.json()["error"]["code"] == "screenshot_game_unknown"
        console.playing, console.broken = MARIO, True
        tracker.invalidate()
        r = await c.post("/api/device/screenshot")
        assert r.status_code == 502 and "Errno 13" in r.json()["error"]["details"]["detail"]
        assert (await c.get("/api/screenshots")).json() == []


async def test_bad_names_are_refused(app_factory):
    async with make(app_factory, ScreenConsole()) as c:
        assert (await c.get("/api/screenshots/1/..%2F..%2Fsettings.json")).status_code == 404
        assert (await c.get("/api/screenshots/1/game.json")).status_code == 404
        assert (await c.delete("/api/screenshots/1/20261019-120000.png")).status_code == 404


async def test_unsupported_system(app_factory):
    app = app_factory(system="muos")
    app.state.device_runner = ScreenConsole(playing=MARIO)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/device/screenshot")
        assert r.status_code == 409 and r.json()["error"]["code"] == "screenshot_unsupported"
        assert (await c.get("/api/device/system")).json()["capabilities"]["screenshot"] is False
