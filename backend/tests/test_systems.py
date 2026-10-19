"""Profils de firmware : noms de dossiers, détection, lancement par EmulationStation, fonctions indisponibles."""

import httpx
import pytest

from app.device import launcher
from app.device.systems import DETECT_COMMAND, PROFILES, parse_detection, suggested_root
from app.platforms import canonical, lookup
from app.services import saves as sv
from tests.test_catalog import games, sync


@pytest.mark.parametrize("directory,code", [
    ("SFC", "SFC"), ("snes", "SFC"), ("Super Nintendo Entertainment System (SFC)", "SFC"), ("psx", "PS"),
    ("megadrive", "MD"), ("genesis", "MD"), ("Sony PlayStation", "PS"), ("Game Boy Advance", "GBA"),
    ("gba", "GBA"), ("nes", "FC"), ("arcade", "MAME"), ("MS", "SMS"), ("mastersystem", "SMS"), ("tg16", "PCE"),
    ("Neo Geo", "NEOGEO"), ("n64", "N64"), ("ports", "PORTS"), ("Inconnu", "INCONNU"),
])
def test_folder_aliases(directory, code):
    assert canonical(directory) == code


def test_lookup_uses_aliases():
    assert lookup("snes").label == "Super Nintendo" and lookup("psx").kind == "emulated"


@pytest.mark.parametrize("out,profile", [
    ("m=stockmod\nm=anbernic\nroot=/mnt/mmc/Roms\n", "anbernic-stock-mod"),
    ("m=anbernic\nroot=/mnt/mmc/Roms\n", "anbernic-stock"),
    ('os.NAME="KNULLI"\nm=batocera\nm=knulli\nm=eshttp\nroot=/userdata/roms\n', "knulli"),
    ("m=batocera\nroot=/userdata/roms\n", "batocera"),
    ('os.NAME="ROCKNIX"\nos.ID=rocknix\nroot=/storage/roms\n', "rocknix"),
    ('os.NAME="JELOS"\nroot=/storage/roms\n', "rocknix"),
    ('os.OS_NAME="ROCKNIX"\nm=bash\nm=eshttp\nroot=/storage/roms\n', "rocknix"),  # /etc/os-release réel
    ("m=muos\nroot=/mnt/mmc/ROMS\n", "muos"),
    ("m=arkos\nroot=/roms\n", "arkos"),
    ("m=onion\nroot=/mnt/SDCARD/Roms\n", "onion"),
    ("m=spruce\nroot=/mnt/SDCARD/Roms\n", "spruce"),
    ("m=minui\nroot=/mnt/SDCARD/Roms\n", "minui"),
    ("os.NAME=Ubuntu\n", "generic"),
    ("m=bash\nm=android\nos.NAME=Android 13 (Retroid Pocket 5)\nroot=/storage/emulated/0/ROMs\n", "android"),
])
def test_detection(out, profile):
    d = parse_detection(out)
    assert d.profile == profile
    if d.roms_roots:
        assert suggested_root(PROFILES[profile], d.roms_roots) == d.roms_roots[0]


def test_detection_is_read_only():
    for forbidden in ("rm ", "mv ", "> /", "mkdir", "chmod", "/launch", "emukill"):
        assert forbidden not in DETECT_COMMAND


def test_capabilities():
    assert PROFILES["anbernic-stock-mod"].capabilities()["launch"]
    assert PROFILES["anbernic-stock-mod"].capabilities()["bluetooth_audio"]
    knulli = PROFILES["knulli"]
    assert not knulli.capabilities(es_http=False)["launch"] and knulli.capabilities(es_http=True)["launch"]
    assert not knulli.capabilities(True)["resume_slot"] and not knulli.capabilities(True)["bluetooth_audio"]
    muos = PROFILES["muos"].capabilities()
    assert not muos["launch"] and not muos["bluetooth"] and muos["quit"]
    assert {p.id for p in PROFILES.values() if p.status == "tested"} == {"anbernic-stock-mod", "onion"}  # essayés sur une vraie console


def test_es_status_parsing():
    playing = launcher.parse_status('@@ES\n{"path":"\\/userdata\\/roms\\/snes\\/Zelda.zip"}\n@@PROC\n')
    assert playing["playing"] and playing["rom_path"] == "/userdata/roms/snes/Zelda.zip"
    idle = launcher.parse_status('@@ES\n{"msg":"NO GAME RUNNING"}\n@@PROC\nmenu=1\n')
    assert not idle["playing"] and idle["menu"]


def test_saves_in_rom_folder_states():
    rocknix = PROFILES["rocknix"].save_sources
    assert sv.is_save_path("/storage/roms/savestates/gb/Zelda.state.auto", "/storage", "/storage/roms", rocknix)
    assert not PROFILES["rocknix"].capabilities(True)["save_state"]  # commandes réseau coupées sur ROCKNIX
    assert sv.is_save_path("/storage/roms/snes/Zelda.state1", "/storage", "/storage/roms", (), rom_states=True)
    assert not sv.is_save_path("/storage/roms/snes/Zelda.state1", "/storage", "/storage/roms", (), rom_states=False)
    assert not sv.is_save_path("/storage/roms/snes/Zelda.zip", "/storage", "/storage/roms", (), rom_states=True)
    knulli = PROFILES["knulli"].save_sources
    assert sv.is_save_path("/userdata/saves/snes/Zelda.srm", "/userdata", "/userdata/roms", knulli)
    assert not sv.is_save_path("/userdata/system/batocera.conf", "/userdata", "/userdata/roms", knulli)


class EsConsole:
    """Knulli : EmulationStation répond sur le port 1234."""

    def __init__(self, es: bool = True):
        self.commands: list[str] = []
        self.es = es
        self.playing: str | None = None

    async def __call__(self, client, command: str, timeout: float = 20):
        self.commands.append(command)
        if command == DETECT_COMMAND:
            return 0, "m=batocera\nm=knulli\n" + ("m=eshttp\n" if self.es else "") + "root=/mnt/mmc/Roms\n"
        if "/launch" in command:
            if not self.es:
                return 0, "no-es\n"
            self.playing = command.split("--data-binary ", 1)[1].split(" http", 1)[0].strip("'")
            return 0, "started\n"
        if command == launcher.ES_STATUS_COMMAND:
            es = f'{{"path":"{self.playing}"}}' if self.playing else '{"msg":"NO GAME RUNNING"}'
            return 0, f"@@ES\n{es}\n@@PROC\n"
        if command == launcher.ES_QUIT_COMMAND:
            was, self.playing = self.playing, None
            return 0, "quit\n" if was else "none\n"
        return 1, ""


def make(app_factory, console, **settings):
    app = app_factory(**settings)
    app.state.device_runner = console
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_knulli_launch_status_quit(app_factory):
    console = EsConsole()
    async with make(app_factory, console, system="auto") as c:
        await sync(c)
        info = (await c.get("/api/device/system")).json()
        assert info["profile"]["id"] == "knulli" and info["capabilities"]["launch"]
        assert info["detected"]["es_http"]
        mario = (await games(c, q="mario"))["items"][0]
        r = await c.post(f"/api/games/{mario['id']}/launch")
        assert r.status_code == 202, r.text
        assert console.playing == "/mnt/mmc/Roms/SFC/Super Mario World (USA).smc"
        r = await c.post(f"/api/games/{mario['id']}/launch", json={"slot": "1"})
        assert r.status_code == 409  # reprendre sur une sauvegarde : Stock OS Mod seulement
        c._transport.app.state.tracker.invalidate()
        now = (await c.get("/api/device/now-playing")).json()
        assert now["playing"] and now["game"]["title"] == "Super Mario World"
        assert (await c.post("/api/device/quit-game")).json() == {"result": "quit"}


async def test_knulli_without_web_server(app_factory):
    async with make(app_factory, EsConsole(es=False), system="auto") as c:
        await sync(c)
        assert not (await c.get("/api/device/system")).json()["capabilities"]["launch"]
        mario = (await games(c, q="mario"))["items"][0]
        r = await c.post(f"/api/games/{mario['id']}/launch")
        assert r.status_code == 409 and r.json()["error"]["code"] == "launch_unsupported"


async def test_unsupported_features_are_refused(app_factory):
    console = EsConsole()
    async with make(app_factory, console, system="muos") as c:
        await sync(c)
        info = (await c.get("/api/device/system")).json()
        assert info["chosen"] == "muos" and info["profile"]["status"] == "experimental"
        assert DETECT_COMMAND not in console.commands  # profil choisi : pas de détection
        mario = (await games(c, q="mario"))["items"][0]
        r = await c.post(f"/api/games/{mario['id']}/launch")
        assert r.status_code == 409 and "muOS" in r.json()["error"]["message"]
        r = await c.get("/api/bluetooth")
        assert r.status_code == 409 and r.json()["error"]["code"] == "bluetooth_unsupported"


async def test_systems_list_and_settings(app_factory):
    async with make(app_factory, EsConsole(), system="anbernic-stock-mod") as c:
        systems = (await c.get("/api/systems")).json()
        assert {s["id"] for s in systems} >= {"anbernic-stock-mod", "knulli", "rocknix", "muos", "arkos", "onion"}
        s = (await c.get("/api/settings")).json()
        s["system"] = "rocknix"
        r = await c.put("/api/settings", json={k: v for k, v in s.items() if k not in ("has_password", "host_key_trusted")})
        assert r.status_code == 200 and r.json()["system"] == "rocknix"
        s["system"] = "windows"
        r = await c.put("/api/settings", json={k: v for k, v in s.items() if k not in ("has_password", "host_key_trusted")})
        assert r.status_code == 422


async def test_onion_launch():
    from app import errors
    from app.device import launcher
    from app.device.systems import PROFILES

    onion = PROFILES["onion"]
    assert onion.capabilities()["launch"] and not onion.capabilities()["resume_slot"]
    sent = []

    async def run(client, command, timeout=20):
        sent.append(command)
        return 0, "started\n"

    await launcher.launch(run, None, "GBA", "/mnt/SDCARD/Roms/GBA/Golden Sun (USA, Europe).zip", None, onion)
    assert "> /tmp/agm-onion-launch.sh" in sent[0] and "pkill -TERM MainUI" in sent[0]
    assert ".keepServicesAlive_" in sent[0]  # SSH gardé pendant les jeux
    assert sent[0].endswith("sh /tmp/agm-onion-launch.sh '/mnt/SDCARD/Roms/GBA/Golden Sun (USA, Europe).zip'")

    async def no_emu(client, command, timeout=20):
        return 5, "no-emu VECTREX\n"

    with pytest.raises(errors.AppError) as e:
        await launcher.launch(no_emu, None, "VECTREX", "/mnt/SDCARD/Roms/VECTREX/x.vec", None, onion)
    assert "VECTREX" in e.value.message
    with pytest.raises(errors.AppError):
        await launcher.launch(run, None, "GBA", "/mnt/SDCARD/Roms/GBA/x.zip", "auto", onion)


def test_android_profile():
    d = parse_detection("m=android\nos.NAME=Android 13 (Retroid Pocket 5)\nroot=/storage/1A2B-3C4D/ROMs\n")
    assert d.os_name == "Android 13 (Retroid Pocket 5)" and d.roms_roots == ["/storage/1A2B-3C4D/ROMs"]
    caps = PROFILES["android"].capabilities()
    assert caps["launch"] and caps["saves"]
    assert not caps["quit"] and not caps["save_state"] and not caps["now_playing"]  # RetroArch Android : pas de commandes réseau
    assert not caps["resume_slot"] and not caps["bluetooth"] and not caps["volume"] and not caps["clock"]
    assert PROFILES["anbernic-stock-mod"].capabilities()["clock"]


def test_android_launch_command():
    cmd = launcher.android_launch_command("snes", "/storage/emulated/0/ROMs/snes/Super Mario World (USA).sfc")
    assert "snes9x_libretro_android.so" in cmd and "'/storage/emulated/0/ROMs/snes/Super Mario World (USA).sfc'" in cmd
    assert "com.retroarch.aarch64" in cmd and launcher.ANDROID_ACTIVITY in cmd
    assert launcher.android_launch_command("PORTS", "/x/y.sh") is None  # pas de cœur : on ne devine pas


async def test_android_status_is_unknown():
    async def run(*_a, **_k):
        raise AssertionError("aucune commande : l'état ne se lit pas sous Android")

    st = await launcher.status(run, None, PROFILES["android"])
    assert st == {"playing": False, "process": None, "rom_path": None, "menu": False}
    with pytest.raises(Exception, match="impossible"):
        launcher.quit_command(PROFILES["android"])
