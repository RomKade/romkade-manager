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
    assert st["controllers"] == [{"index": 0, "name": "ANBERNIC-keys", "builtin": True},
                                 {"index": 1, "name": "Xbox Wireless Controller", "builtin": False}]
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
        assert "pidof retroarch >/dev/null ||" in sent and "cat /.config/agm-players >> /.config/retroarch/retroarch.cfg" in sent
