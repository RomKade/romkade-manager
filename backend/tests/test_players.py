import httpx

from app.device import players as pl

DEVICES = """I: Bus=0000 Vendor=0000 Product=0000 Version=0000
N: Name="axp2202-pek"
P: Phys=m1kbd/input2
H: Handlers=kbd event0 

I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="ANBERNIC-keys"
P: Phys=gpio-keys-polled/input0
H: Handlers=kbd js0 event1 

I: Bus=0005 Vendor=045e Product=0b13 Version=0509
N: Name="Xbox Wireless Controller"
P: Phys=68:8f:c9:99:5a:77
H: Handlers=event3 js1 
"""
SAMPLE = f"""@@INPUT
{DEVICES}
@@CFG
input_player1_joypad_index = "2"
input_player2_joypad_index = "1"
input_player3_joypad_index = "0"
input_player4_joypad_index = "3"
@@WANT
@@RA
"""


def test_parse_status():
    st = pl.parse_status(SAMPLE)
    assert st["controllers"] == [{"index": 0, "name": "ANBERNIC-keys", "builtin": True, "usb_id": "0001:0001"},
                                 {"index": 1, "name": "Xbox Wireless Controller", "builtin": False, "usb_id": "045e:0b13"}]
    assert st["players"] == [2, 1, 0, 3] and st["applied"] and not st["game_running"]


def test_wanted_while_playing():
    out = SAMPLE.replace("@@WANT\n", "@@WANT\n" + pl.file_text([0, 1, 2, 3])).replace("@@RA\n", "@@RA\n4000\n")
    st = pl.parse_status(out)
    assert st["players"] == [0, 1, 2, 3] and not st["applied"] and st["game_running"]


class FakeConsole:
    def __init__(self):
        self.commands = []

    async def __call__(self, client, command, timeout=20):
        self.commands.append(command)
        return 0, SAMPLE


async def test_players_api(app_factory):
    console = FakeConsole()
    app = app_factory()
    app.state.device_runner = console
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/api/players")).json()["players"] == [2, 1, 0, 3]
        assert (await c.put("/api/players", json={"players": [0, 0, 1, 2]})).status_code == 422
        assert (await c.put("/api/players", json={"players": [0, 1, 2]})).status_code == 422
        assert (await c.put("/api/players", json={"players": [0, 1, 2, 3]})).status_code == 200
        sent = console.commands[-2]
        assert 'input_player1_joypad_index = "0"' in sent and "> /.config/agm-players" in sent
        # Sans jeu en cours : players_apply.sh traduit les numéros pour RetroArch et réserve les manettes
        assert "pidof retroarch >/dev/null ||" in sent and "reserved_device" in sent and "sort -n" in sent



def test_applied_copy_decides_pending():
    """La config de RetroArch porte des numéros traduits : « appliqué » se lit dans la copie de players_apply.sh."""
    want = pl.file_text([1, 0, 2, 3])
    out = SAMPLE.replace("@@WANT\n", "@@WANT\n" + want).replace("@@RA\n", "@@APPLIED\n" + want + "@@RA\n")
    st = pl.parse_status(out)
    assert st["players"] == [1, 0, 2, 3] and st["applied"]  # CFG dit 2 1 0 3, mais c'est la traduction
    st = pl.parse_status(out.replace("@@APPLIED\n" + want, "@@APPLIED\n" + pl.file_text([0, 1, 2, 3])))
    assert not st["applied"]


def test_launch_command_carries_players_script():
    from app.device import launcher

    cmd = launcher.launch_command("SMS", "/mnt/mmc/Roms/SMS/California Games.sms")
    assert "AGM_PLAYERS=" in cmd and "reservation_type" in cmd


def test_directions_read_from_config_then_wanted():
    """Ce qui dirige chaque joueur : la config de RetroArch tant que rien n'a été choisi (firmware : stick droit)."""
    cfg = '@@CFG\ninput_player1_analog_dpad_mode = "2"\ninput_player2_analog_dpad_mode = "4"\n'
    out = SAMPLE.replace("@@CFG\n", cfg)
    st = pl.parse_status(out)
    assert st["directions"] == [2, 2, None, None] and st["applied"]  # 4 = stick droit forcé, lu comme 2
    want = pl.file_text([2, 1, 0, 3], [1, 0, 0, 0])
    st = pl.parse_status(out.replace("@@WANT\n", "@@WANT\n" + want))
    assert st["directions"] == [1, 0, 0, 0] and not st["applied"]
    st = pl.parse_status(out.replace("@@WANT\n", "@@WANT\n" + want).replace("@@RA\n", "@@APPLIED\n" + want + "@@RA\n"))
    assert st["applied"]


async def test_directions_api_keeps_players(app_factory):
    console = FakeConsole()
    app = app_factory()
    app.state.device_runner = console
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.put("/api/players", json={"directions": [3, 0, 0, 0]})).status_code == 422
        assert (await c.put("/api/players", json={"directions": [1, 0, 0]})).status_code == 422
        assert (await c.put("/api/players", json={"directions": [1, 0, 0, 0]})).status_code == 200
        sent = console.commands[-2]
        # Les manettes ne changent pas (lues sur la console : 2 1 0 3), seule la direction est choisie
        assert 'input_player1_joypad_index = "2"' in sent and 'input_player1_analog_dpad_mode = "1"' in sent
        assert "analog_dpad_mode" in sent.split("bash -c", 1)[1]  # players_apply.sh les recopie


def test_apply_script_writes_directions(tmp_path):
    """players_apply.sh sur une fausse console : numéros traduits, directions recopiées, le reste intact."""
    import subprocess

    root = tmp_path
    (root / "proc").mkdir()
    (root / "proc/devices").write_text(DEVICES.replace("H: Handlers=kbd js0", "S: Sysfs=/b\nH: Handlers=kbd js0")
                                       .replace("H: Handlers=event3 js1", "S: Sysfs=/a\nH: Handlers=event3 js1"))
    cfg = root / "retroarch.cfg"
    cfg.write_text('video_smooth = "false"\ninput_player1_analog_dpad_mode = "2"\ninput_player1_joypad_index = "0"\n')
    players = root / "agm-players"
    players.write_text(pl.file_text([0, 1, 2, 3], [0, 1, 0, 0]))
    script = (pl.APPLY_SCRIPT.replace("/proc/bus/input/devices", str(root / "proc/devices"))
              .replace("/.config/retroarch/retroarch.cfg", str(cfg)).replace("/.config/agm-players", str(players)))
    subprocess.run(["bash", "-c", script], check=True, capture_output=True)
    text = cfg.read_text()
    assert 'video_smooth = "false"' in text
    assert text.count("analog_dpad_mode") == 4 and 'input_player1_analog_dpad_mode = "0"' in text
    assert 'input_player2_analog_dpad_mode = "1"' in text
    assert 'input_player1_joypad_index = "1"' in text  # console : 2e par chemin sysfs (/a avant /b)
    assert (root / "agm-players.applied").read_text() == players.read_text()


def test_apply_script_without_directions_keeps_config(tmp_path):
    """Ancien fichier sans directions : la config de RetroArch garde les siennes."""
    import subprocess

    (tmp_path / "devices").write_text(DEVICES)
    cfg = tmp_path / "retroarch.cfg"
    cfg.write_text('input_player1_analog_dpad_mode = "2"\n')
    players = tmp_path / "agm-players"
    players.write_text(pl.file_text([0, 1, 2, 3]))
    script = (pl.APPLY_SCRIPT.replace("/proc/bus/input/devices", str(tmp_path / "devices"))
              .replace("/.config/retroarch/retroarch.cfg", str(cfg)).replace("/.config/agm-players", str(players)))
    subprocess.run(["bash", "-c", script], check=True, capture_output=True)
    assert 'input_player1_analog_dpad_mode = "2"' in cfg.read_text()
