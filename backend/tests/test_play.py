import shlex

import httpx

from app.device import launcher
from tests.test_catalog import games, sync


class FakeConsole:
    """Remplace SSH : enregistre les commandes et répond comme la console."""

    def __init__(self, mod: bool = True, playing: str | None = None):
        self.commands: list[str] = []
        self.mod, self.playing = mod, playing

    async def __call__(self, client, command: str, timeout: float = 20):
        self.commands.append(command)
        if command.startswith("test -x"):
            return (0, "started\n") if self.mod else (7, "no-mod\n")
        if command == launcher.STATUS_COMMAND:
            return 0, (f"proc=retroarch\narg={self.playing}\n" if self.playing else "menu=1\n")
        if command == launcher.QUIT_COMMAND:
            return 0, "quit\n" if self.playing else "none\n"
        return 1, ""


def make(app_factory, console):
    app = app_factory()
    app.state.device_runner = console
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_launch_command_quotes_paths():
    cmd = launcher.launch_command("SFC", "/mnt/mmc/Roms/SFC/Mario's World (USA).smc")
    args = shlex.split(cmd.split("setsid nohup ", 1)[1])[:6]
    assert args[:2] == ["bash", "-c"] and args[2] == launcher.LAUNCH_SCRIPT
    assert args[3:] == ["agm-launch", "SFC", "/mnt/mmc/Roms/SFC/Mario's World (USA).smc"]


async def test_launch_game_on_console(app_factory, ssh_server):
    console = FakeConsole()
    async with make(app_factory, console) as c:
        await sync(c)
        mario = (await games(c, q="mario"))["items"][0]
        r = await c.post(f"/api/games/{mario['id']}/launch")
        assert r.status_code == 202, r.text
        assert r.json()["rom_path"] == "/mnt/mmc/Roms/SFC/Super Mario World (USA).smc"
        assert "'/mnt/mmc/Roms/SFC/Super Mario World (USA).smc'" in console.commands[-1]
    assert ssh_server["sftp"].write_attempts == []


async def test_launch_refused_without_mod(app_factory):
    async with make(app_factory, FakeConsole(mod=False)) as c:
        await sync(c)
        mario = (await games(c, q="mario"))["items"][0]
        r = await c.post(f"/api/games/{mario['id']}/launch")
        assert r.status_code == 409 and r.json()["error"]["code"] == "launch_unsupported"


async def test_programs_are_not_launchable(app_factory):
    async with make(app_factory, FakeConsole()) as c:
        await sync(c)
        prog = (await games(c, role="program"))["items"][0]
        r = await c.post(f"/api/games/{prog['id']}/launch")
        assert r.status_code == 409 and r.json()["error"]["code"] == "not_launchable"


async def test_now_playing_and_quit(app_factory):
    console = FakeConsole(playing="/mnt/mmc/Roms/SFC/Super Mario World (USA).smc")
    async with make(app_factory, console) as c:
        await sync(c)
        now = (await c.get("/api/device/now-playing")).json()
        assert now["playing"] and now["process"] == "retroarch" and now["game"]["title"] == "Super Mario World"
        assert (await c.post("/api/device/quit-game")).json() == {"result": "quit"}
        console.playing = None
        now = (await c.get("/api/device/now-playing")).json()
        assert not now["playing"] and now["menu"] and now["game"] is None


def test_standalone_emulator_from_console_menu():
    """Le menu de la console lance la PlayStation avec l'émulateur autonome « pcsx », pas RetroArch."""
    from app.device import launcher
    assert "pcsx" in launcher.STATUS_COMMAND
    st = launcher.parse_status("proc=pcsx\narg=/mnt/mmc/Roms/PS/Crash Bandicoot N. Sane Trilogy.PBP\n")
    assert st["playing"] and st["process"] == "pcsx" and st["rom_path"].endswith("Trilogy.PBP")


def test_launch_closes_leftover_standalone_emulators():
    """Un émulateur autonome resté ouvert (DS…) garde la sortie audio : le jeu suivant serait muet. launch.sh reçoit
    la liste des émulateurs à fermer avant de lancer."""
    from app.device import launcher

    cmd = launcher.launch_command("PS", "/mnt/mmc/Roms/PS/Future Cop - L.A.P.D. (USA).chd")
    games = cmd.split("AGM_GAMES=", 1)[1].split("'")[1].split()
    assert "drastic" in games and "PPSSPPSDL" in games and "retroarch" not in games
    assert 'for name in $AGM_GAMES' in launcher.LAUNCH_SCRIPT


def test_launch_waits_for_the_previous_launch_script():
    """Le script du jeu précédent relâche le menu en finissant : le nouveau l'attend avant de mettre le menu en pause,
    sinon le menu repart derrière le nouveau jeu (console ralentie)."""
    from app.device import launcher

    script = launcher.LAUNCH_SCRIPT
    assert script.index("previous_launches") < script.index('kill -STOP "$LOOP"')
    assert "grep -qx agm-launch" in script and '"$start" -lt "$MY_START"' in script
    # Le mot ne doit jamais être seul sur une ligne du script (sinon chaque sous-shell serait pris pour un ancien).
    assert all(line.strip() != "agm-launch" for line in script.splitlines())
