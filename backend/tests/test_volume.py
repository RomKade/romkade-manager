import httpx

from app.device import launcher
from app.device import volume as vol


def sample(raw=None, on=True, game="", agm=False, hw=63, saved=""):
    soft = (f"numid=15,iface=MIXER,name='Game Manager Playback Volume'\n"
            f"  ; type=INTEGER,access=rw---RW-,values=2,min=0,max=84,step=0\n  : values={raw},{raw}\n"
            f"@@SW\nnumid=11,iface=MIXER,name='Game Manager Playback Switch'\n  ; type=BOOLEAN,access=rw------,values=2\n"
            f"  : values={'on' if on else 'off'},{'on' if on else 'off'}\n") if raw is not None else "@@SW\n"
    hwmix = f"numid=2,iface=MIXER,name='digital volume'\n  ; type=INTEGER,access=rw---R--,values=1,min=0,max=63,step=0\n  : values={hw}\n"
    return f"@@VOL\n{soft}@@HW\n{hwmix}@@SAVED\n{saved}\n@@GAME\n{game}\n{'agm' if agm else ''}\n"


def test_parse_status():
    st = vol.parse_status(sample(42, game="retroarch", agm=True))
    assert (st["mode"], st["adjustable"], st["percent"], st["muted"], st["game_running"]) == ("game_manager", True, 50, False, True)
    assert vol.parse_status(sample(42, on=False, game="retroarch", agm=True))["muted"]
    st = vol.parse_status(sample(42, game="retroarch"))  # RetroArch lancé depuis le menu : seule la coupure
    assert (st["mode"], st["adjustable"]) == ("retroarch", False)
    st = vol.parse_status(sample(42, game="pcsx", hw=63))  # émulateur autonome : mixeur de la console
    assert (st["mode"], st["percent"], st["max"]) == ("console", 100, 63)
    assert vol.parse_status(sample(42))["mode"] == "game_manager"  # sans jeu : notre volume, pour le prochain


def test_asoundrc():
    rc = vol.asoundrc()
    assert "pcm.!default agm_vol" in rc and 'slave.pcm "agm_speakers"' in rc and vol.VERSION in rc
    assert 'slave.pcm "hw:audiocodec"' in rc and "format S16_LE" in rc and '"SPK Switch" preserve true lock true value 1' in rc
    assert 'slave.pcm "agm_bt"' in vol.asoundrc("agm_bt")
    cmd = launcher.launch_command("SFC", "/mnt/mmc/Roms/SFC/x.smc")
    assert cmd.index(f"grep -q {vol.VERSION} /.asoundrc") < cmd.index("setsid nohup")
    assert "AGM_VOLKEYS=" in cmd and "KEY_VOLUMEUP" in cmd  # touches Vol+ / Vol- pendant le jeu
    assert "AGM_LAUNCH=1" in launcher.LAUNCH_SCRIPT and "pcsx" in vol._status_command()


class FakeConsole:
    def __init__(self, raw=42, game="retroarch", agm=True):
        self.commands, self.raw, self.on, self.game, self.agm, self.hw, self.saved = [], raw, True, game, agm, 63, ""

    async def __call__(self, client, command, timeout=20):
        self.commands.append(command)
        if command.startswith("echo @@VOL"):
            return 0, sample(self.raw, self.on, self.game, self.agm, self.hw, self.saved)
        for part in command.replace(" && ", "; ").split("; "):
            if part.startswith(f"amixer -q -c 0 cset {vol.VOLUME_ELEM} "):
                self.raw = int(part.rsplit(" ", 1)[1].split(",")[0])
            elif part.startswith(f"amixer -q -c 0 cset {vol.SWITCH_ELEM} "):
                self.on = part.endswith("on,on")
            elif part.startswith(f"amixer -q -c 0 cset {vol.HW_ELEM} "):
                self.hw = int(part.rsplit(" ", 1)[1])
            elif part.startswith("echo ") and vol.HW_SAVED in part:
                self.saved = part.split()[1]
            elif part == f"rm -f {vol.HW_SAVED}":
                self.saved = ""
        return 0, ""


def client_for(app_factory, console):
    app = app_factory()
    app.state.device_runner = console
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_volume_game_manager(app_factory):
    console = FakeConsole()
    async with client_for(app_factory, console) as c:
        assert (await c.get("/api/volume")).json()["percent"] == 50
        r = (await c.put("/api/volume", json={"percent": 100})).json()
        assert console.commands[-2] == ("amixer -q -c 0 cset name='Game Manager Playback Volume' 84,84 && "
                                        "amixer -q -c 0 cset name='Game Manager Playback Switch' on,on")
        assert r["percent"] == 100
        r = (await c.put("/api/volume", json={"muted": True})).json()
        assert r["muted"] and r["percent"] == 100
        assert not (await c.put("/api/volume", json={"muted": False})).json()["muted"]
        assert (await c.put("/api/volume", json={"percent": 150})).status_code == 422


async def test_volume_standalone_emulator(app_factory):
    console = FakeConsole(game="pcsx", agm=False)
    async with client_for(app_factory, console) as c:
        r = (await c.put("/api/volume", json={"percent": 50})).json()
        assert r["mode"] == "console" and console.hw == 32 and r["percent"] == 51
        r = (await c.put("/api/volume", json={"muted": True})).json()
        assert r["muted"] and console.hw == 0 and console.saved == "32"
        r = (await c.put("/api/volume", json={"muted": False})).json()
        assert not r["muted"] and console.hw == 32


async def test_volume_retroarch_from_console_menu(app_factory):
    console = FakeConsole(game="retroarch", agm=False)
    async with client_for(app_factory, console) as c:
        r = await c.put("/api/volume", json={"muted": True})
        assert r.status_code == 200 and r.json()["muted"] and "MUTE" in console.commands[-2]
        r = await c.put("/api/volume", json={"percent": 50})
        assert r.status_code == 409 and r.json()["error"]["code"] == "volume_not_ready"
