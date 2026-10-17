import httpx

from app.device import clock


def test_parse_status():
    st = clock.parse_status("1662018992\n/usr/share/zoneinfo/Etc/UTC\n+0000\n", now=1792188529)
    assert st["timezone"] == "Etc/UTC" and st["utc_offset"] == "+0000"
    assert st["drift_seconds"] == 1662018992 - 1792188529  # la console a 4 ans de retard


def test_sync_command():
    cmd = clock.sync_command(1792188529, "Europe/Paris")
    assert cmd.startswith("date -u -s @1792188529 >/dev/null && (hwclock -w")
    assert "ln -sf /usr/share/zoneinfo/Europe/Paris /etc/localtime" in cmd
    # le menu ne lit le fuseau qu'à son démarrage : redémarré si le fuseau change et qu'aucun jeu ne tourne
    assert '!= /usr/share/zoneinfo/Europe/Paris ]' in cmd and 'kill -INT "$M"' in cmd and "pidof retroarch pcsx" in cmd


class FakeConsole:
    def __init__(self):
        self.commands = []

    async def __call__(self, client, command, timeout=20):
        self.commands.append(command)
        return 0, "1792188529\n/usr/share/zoneinfo/Europe/Paris\n+0200\n"


async def test_clock_api(app_factory):
    console = FakeConsole()
    app = app_factory()
    app.state.device_runner = console
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = (await c.get("/api/device/clock")).json()
        assert r["timezone"] == "Europe/Paris" and r["utc_offset"] == "+0200"
        assert (await c.post("/api/device/clock/sync", json={"timezone": "Europe/Paris"})).status_code == 200
        assert console.commands[-2].startswith("date -u -s @")
        r = await c.post("/api/device/clock/sync", json={"timezone": "../../etc/passwd"})
        assert r.status_code == 422
