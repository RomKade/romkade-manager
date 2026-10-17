from datetime import UTC, datetime, timedelta

import httpx

from app.services import playtime as pt
from tests.test_catalog import sync

MARIO = "/mnt/mmc/Roms/SFC/Super Mario World (USA).smc"
SONIC = "/mnt/mmc/Roms/MD/Sonic The Hedgehog (Europe).md"
T0 = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)

RA_OUT = """@@LRTL /mnt/vendor/deep/retro/playlists/logs/Snes9x/Super Mario World (USA).lrtl
{
  "version": "1.0",
  "runtime": "2:30:00",
  "last_played": "2022-09-01 02:35:45"
}
@@LRTL /mnt/vendor/deep/retro/playlists/logs/Genesis Plus GX/Jeu Inconnu (USA).lrtl
{"runtime": "0:10:00", "last_played": "2022-08-30 10:00:00"}
@@HISTORY
      "path": "/mnt/mmc/Roms/SFC/Super Mario World (USA).smc",
"""


class FakeConsole:
    def __init__(self):
        self.commands = []

    async def __call__(self, client, command, timeout=20):
        self.commands.append(command)
        if "@@LRTL" in command:
            return 0, RA_OUT
        return 0, "menu=1\n"


def playing(rom):
    return {"playing": True, "process": "retroarch", "rom_path": rom, "menu": False}


IDLE = {"playing": False, "process": None, "rom_path": None, "menu": True}


def test_runtime_parsing():
    assert pt.parse_runtime("2:30:05") == 9005 and pt.parse_runtime("") == 0
    entries, history = pt.parse_retroarch(RA_OUT)
    assert [(e["stem"], e["core"], e["seconds"]) for e in entries] == [
        ("Super Mario World (USA)", "Snes9x", 9000), ("Jeu Inconnu (USA)", "Genesis Plus GX", 600)]
    assert history == [MARIO]


async def test_sessions_alerts_and_stats(app_factory):
    console = FakeConsole()
    app = app_factory()
    app.state.device_runner = console
    tr = app.state.tracker
    app.state.play_settings.save(pt.PlaySettings(alert_enabled=True, alert_minutes=60, alert_scope="session",
                                                 repeat_minutes=30, console_message=True))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        # Mario de 8 h à 9 h 30 (une observation toutes les 30 s), puis Sonic 20 min après une coupure réseau
        t = T0
        while t <= T0 + timedelta(minutes=90):
            await tr.observe(playing(MARIO), t)
            t += timedelta(seconds=30)
        alerts = tr.pending_alerts()
        assert [a["minutes"] for a in alerts] == [60, 90]  # à 1 h, puis rappel 30 min plus tard
        assert alerts[0]["game_title"] == "Super Mario World"
        assert sum("SHOW_MSG" in cmd for cmd in console.commands) == 2
        await tr.observe(None, t + timedelta(minutes=1))   # console injoignable : la partie continue
        assert tr.current is not None
        for i in range(0, 41):  # Sonic : 20 min, relevé toutes les 30 s
            await tr.observe(playing(SONIC), t + timedelta(minutes=2, seconds=30 * i))
        await tr.observe(IDLE, t + timedelta(minutes=23))
        assert tr.current is None

        state = (await c.get("/api/play/state")).json()
        assert not state["playing"] and len(state["alerts"]) == 2
        assert (await c.post(f"/api/play/alerts/{alerts[0]['id']}/ack")).status_code == 204
        assert len((await c.get("/api/play/state")).json()["alerts"]) == 1

        stats = (await c.get("/api/play/stats", params={"days": 3})).json()
        games = {g["title"]: g for g in stats["games"]}
        assert games["Super Mario World"]["seconds"] == 9000          # RetroArch (2 h 30) > suivi (1 h 30)
        assert games["Super Mario World"]["sessions"] == 1
        assert games["Sonic The Hedgehog"]["seconds"] == 20 * 60
        assert games["Jeu Inconnu (USA)"]["game"] is None
        assert [s["title"] for s in stats["sessions"]] == ["Sonic The Hedgehog", "Super Mario World"]
        assert stats["retroarch_available"] and len(stats["days"]) == 3

        r = await c.put("/api/play/settings", json={"alert_enabled": True, "alert_minutes": 240, "alert_scope": "day",
                                                    "repeat_minutes": 0, "console_message": False})
        assert r.status_code == 200 and (await c.get("/api/play/settings")).json()["alert_minutes"] == 240
        assert (await c.put("/api/play/settings", json={"alert_minutes": 1})).status_code == 422


async def test_day_scope_counts_all_sessions(app_factory):
    app = app_factory()
    app.state.device_runner = FakeConsole()
    tr = app.state.tracker
    app.state.play_settings.save(pt.PlaySettings(alert_enabled=True, alert_minutes=30, alert_scope="day",
                                                 repeat_minutes=0, console_message=False))
    for i in range(0, 21):  # 20 min de Mario
        await tr.observe(playing(MARIO), T0 + timedelta(minutes=i))
    await tr.observe(IDLE, T0 + timedelta(minutes=21))
    assert tr.pending_alerts() == []
    for i in range(0, 15):  # puis 14 min de Sonic : 34 min dans la journée
        await tr.observe(playing(SONIC), T0 + timedelta(minutes=30 + i))
    assert [a["scope"] for a in tr.pending_alerts()] == ["day"]


async def test_recent_games_merge_console_history_and_sessions(app_factory):
    class Console(FakeConsole):
        async def __call__(self, client, command, timeout=20):
            if "content_history" in command:
                return 0, f'      "path": "{SONIC}",\n      "path": "/mnt/mmc/Roms/XX/Jeu disparu.bin",\n'
            return await super().__call__(client, command, timeout)

    app = app_factory()
    app.state.device_runner = Console()
    tr = app.state.tracker
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        for i in range(0, 11):  # 5 min de Mario, suivi par Game Manager (absent de l'historique RetroArch)
            await tr.observe(playing(MARIO), T0 + timedelta(seconds=30 * i))
        await tr.observe(IDLE, T0 + timedelta(minutes=6))
        recent = (await c.get("/api/play/recent")).json()
        assert [r["title"] for r in recent] == ["Sonic The Hedgehog", "Jeu disparu", "Super Mario World"]
        assert recent[0]["game"]["platform"]["directory"] == "MD" and recent[1]["game"] is None
        assert recent[2]["seconds"] == 300 and recent[2]["last_played"]
