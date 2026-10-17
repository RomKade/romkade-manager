import httpx
import pytest

from app import errors
from app.device import bluetooth as bt
from app.device import launcher
from tests.test_catalog import games, sync

SAMPLE = """@@SHOW
Controller 68:8F:C9:99:5A:77 (public)
	Name: ANBERNIC
	Alias: ANBERNIC
	Powered: yes
	Discovering: no
@@DEV 00:0C:8A:76:CE:E3
Device 00:0C:8A:76:CE:E3 (public)
	Name: Bose SoundLink Mobile speaker II
	Icon: audio-card
	Paired: yes
	Trusted: yes
	Connected: yes
	UUID: Audio Sink                (0000110b-0000-1000-8000-00805f9b34fb)
@@DEV E4:17:D8:01:02:03
Device E4:17:D8:01:02:03 (public)
	Name: 8BitDo Pro 2
	Icon: input-gaming
	Paired: no
	Connected: no
	RSSI: 0xffffffc4 (-60)
	UUID: Human Interface Device... (00001124-0000-1000-8000-00805f9b34fb)
@@BLUEALSA
4890
@@AUDIO
defaults.bluealsa.device "00:0C:8A:76:CE:E3"
"""


def test_parse_status():
    st = bt.parse_status(SAMPLE)
    assert st["adapter"] == {"present": True, "powered": True, "discovering": False, "name": "ANBERNIC"}
    bose, pad = st["devices"]
    assert (bose["kind"], bose["connected"], bose["paired"]) == ("audio", True, True)
    assert (pad["kind"], pad["paired"], pad["rssi"]) == ("controller", False, -60)
    assert st["bluealsa"] and st["audio_output"] == "00:0C:8A:76:CE:E3"


def test_bad_address_never_reaches_the_shell():
    with pytest.raises(errors.AppError):
        bt.check_mac("00:11:22:33:44:55; reboot")
    assert bt.check_mac("e4:17:d8:01:02:03") == "E4:17:D8:01:02:03"


class FakeBtConsole:
    def __init__(self, playing=False):
        self.commands, self.playing = [], playing

    async def __call__(self, client, command, timeout=20):
        self.commands.append(command)
        if command == launcher.STATUS_COMMAND:
            return 0, ("proc=retroarch\narg=/mnt/mmc/Roms/SFC/x.smc\n" if self.playing else "menu=1\n")
        if command.startswith("test -x"):
            return 0, "started\n"
        if "connect E4:17" in command:
            return 0, "@@RESULT absent\nFailed to connect: org.bluez.Error.Failed\n"
        if "connect 40:8E" in command:
            return 0, "@@RESULT paired\n"
        if "connect 00:0C" in command:
            return 0, "@@RESULT connected\n"
        return 0, SAMPLE


def client_for(app_factory, console):
    app = app_factory()
    app.state.device_runner = console
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_bluetooth_api(app_factory):
    console = FakeBtConsole()
    async with client_for(app_factory, console) as c:
        st = (await c.get("/api/bluetooth")).json()
        assert [d["name"] for d in st["devices"]] == ["Bose SoundLink Mobile speaker II", "8BitDo Pro 2"]
        r = await c.post("/api/bluetooth/connect", json={"address": "E4:17:D8:01:02:03"})
        assert r.status_code == 502 and r.json()["error"]["details"]["detail"].startswith("Failed to connect")
        sent = next(cmd for cmd in console.commands if "connect E4:17:D8:01:02:03" in cmd)
        assert "bluealsa -p a2dp-source" in sent and "echo 'scan on'" in sent and "echo 'pair E4:17:D8:01:02:03'" in sent
        r = await c.post("/api/bluetooth/connect", json={"address": "40:8E:2C:5E:AC:1C"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "bt_paired_not_connected"
        assert (await c.post("/api/bluetooth/connect", json={"address": "00:0C:8A:76:CE:E3"})).status_code == 200
        assert (await c.post("/api/bluetooth/connect", json={"address": "nope"})).status_code == 422
        r = await c.post("/api/bluetooth/audio-output", json={"address": "00:0C:8A:76:CE:E3"})
        assert r.status_code == 200
        sent = next(cmd for cmd in console.commands if "printf %s" in cmd)
        assert 'defaults.bluealsa.device "00:0C:8A:76:CE:E3"' in sent and "> /etc/alsa/conf.d/60-agm-bluetooth.conf" in sent
        assert "|env -u LD_LIBRARY_PATH aplay" in sent and "exec cat > /dev/null" in sent
        assert "|| env -u LD_LIBRARY_PATH aplay -q -t raw -f S16_LE -r 48000 -c 2 -D agm_speakers -" in sent  # enceinte absente
        assert 'slave.pcm "agm_bt"' in sent and "pcm.!default agm_vol" in sent and "> /.asoundrc" in sent
        assert 'slave.pcm "plughw:ahubhdmi"' in sent  # horloge temps réel : la sortie HDMI, muette sans câble
        await c.post("/api/bluetooth/audio-output", json={"address": None})
        back = next(cmd for cmd in console.commands if cmd.startswith("rm -f /etc/alsa/conf.d/60-agm-bluetooth.conf;"))
        assert 'slave.pcm "agm_speakers"' in back and "> /.asoundrc" in back


async def test_launch_with_slot(app_factory):
    console = FakeBtConsole()
    async with client_for(app_factory, console) as c:
        await sync(c)
        mario = (await games(c, q="mario"))["items"][0]
        r = await c.post(f"/api/games/{mario['id']}/launch", json={"slot": "2"})
        assert r.status_code == 202 and r.json()["slot"] == "2"
        assert console.commands[-1].rstrip().endswith("'/mnt/mmc/Roms/SFC/Super Mario World (USA).smc' 2 > /tmp/agm-launch.log 2>&1 < /dev/null & echo started")
        r = await c.post(f"/api/games/{mario['id']}/launch", json={"slot": "1; reboot"})
        assert r.status_code == 422
