from app.device import sound
from app.device import volume as vol
from tests.test_bluetooth import FakeBtConsole, client_for


class SoundConsole(FakeBtConsole):
    """Console sur une TV (câble HDMI), enceinte Bose connectée ; `rc` : /.asoundrc qui garde les haut-parleurs."""

    def __init__(self, hdmi=True, rc="", busy=False):
        super().__init__()
        self.hdmi, self.rc, self.busy = hdmi, rc, busy

    async def __call__(self, client, command, timeout=20):
        if command == sound.STATUS_COMMAND:
            self.commands.append(command)
            return 0, f"@@HDMI\nHDMI={int(self.hdmi)}\n@@RC\n{self.rc}"
        if "agm-sound-test" in command:
            self.commands.append(command)
            return 0, "@@RESULT in_use\n" if self.busy else "@@RESULT absent\n" if not self.hdmi and "ahubhdmi" in command else "@@RESULT played\n"
        return await super().__call__(client, command, timeout)


def test_parse():
    st = sound.parse("@@HDMI\nHDMI=1\n@@RC\n", {"audio_output": None, "devices": []})
    assert (st["output"], st["hdmi"]) == ("tv", True)
    assert sound.parse("@@HDMI\n@@RC\nspeakers\n", {"audio_output": None, "devices": []})["output"] == "speakers"
    # Haut-parleurs même TV branchée : « playback_hdmi » redirigé ; TV : /.asoundrc d'origine
    assert "pcm.!playback_hdmi agm_vol" in vol.asoundrc(tv=False) and "playback_hdmi" not in vol.asoundrc()
    cmd = vol.install_command()
    assert cmd.index("grep -q agm_bt") < cmd.index("grep -q playback_hdmi")  # l'enceinte redéfinit aussi playback_hdmi


async def test_sound_api(app_factory):
    console = SoundConsole()
    async with client_for(app_factory, console) as c:
        st = (await c.get("/api/sound")).json()
        assert (st["output"], st["address"], st["hdmi"]) == ("bluetooth", "00:0C:8A:76:CE:E3", True)
        assert [d["name"] for d in st["devices"]] == ["Bose SoundLink Mobile speaker II"]  # pas la manette
        await c.put("/api/sound", json={"output": "speakers"})
        sent = next(cmd for cmd in console.commands if cmd.startswith("rm -f /etc/alsa/conf.d/60-agm-bluetooth.conf;"))
        assert "pcm.!playback_hdmi agm_vol" in sent and 'slave.pcm "agm_speakers"' in sent and "> /.asoundrc" in sent
        console.commands.clear()
        await c.put("/api/sound", json={"output": "tv"})
        assert "playback_hdmi" not in next(cmd for cmd in console.commands if cmd.startswith("rm -f"))
        console.commands.clear()
        assert (await c.put("/api/sound", json={"output": "bluetooth", "address": "00:0C:8A:76:CE:E3"})).status_code == 200
        assert not any("echo 'connect" in cmd for cmd in console.commands)  # déjà connectée
        assert any('defaults.bluealsa.device "00:0C:8A:76:CE:E3"' in cmd for cmd in console.commands)
        r = await c.put("/api/sound", json={"output": "bluetooth", "address": "E4:17:D8:01:02:03"})
        assert r.status_code == 502 and any("connect E4:17:D8:01:02:03" in cmd for cmd in console.commands)  # connectée d'abord
        assert (await c.put("/api/sound", json={"output": "bluetooth"})).status_code == 422
        assert (await c.put("/api/sound", json={"output": "hdmi"})).status_code == 422


async def test_sound_test_api(app_factory):
    console = SoundConsole(hdmi=False)
    async with client_for(app_factory, console) as c:
        assert (await c.post("/api/sound/test", json={"output": "speakers"})).json() == {"result": "played"}
        sent = console.commands[-1]
        assert "-D agm_speakers" in sent and "LC_ALL=C" in sent and vol.VERSION in sent  # /.asoundrc installé avant
        r = await c.post("/api/sound/test", json={"output": "tv"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "sound_no_tv"
        console.busy = True
        assert (await c.post("/api/sound/test", json={"output": "speakers"})).json() == {"result": "in_use"}
    assert "pidof retroarch" in sound.test_command("tv") and "@@RESULT menu" in sound.test_command("tv")

