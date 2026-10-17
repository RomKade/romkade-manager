import io
import zipfile

import httpx
import pytest

from app.api.saves import hotkeys
from app.services.saves import classify, is_save_path
from tests.test_catalog import sync
from tests.test_play import FakeConsole

BASE, ROMS = "/mnt/mmc", "/mnt/mmc/Roms"


@pytest.mark.parametrize("name,expected", [
    ("Super Mario World (USA).srm", ("sram", None, "Super Mario World (USA)")),
    ("Super Mario World (USA).state", ("state", "0", "Super Mario World (USA)")),
    ("Super Mario World (USA).state3", ("state", "3", "Super Mario World (USA)")),
    ("Super Mario World (USA).state.auto", ("state", "auto", "Super Mario World (USA)")),
    ("Asterix (Europe).sms.st1", ("state", "1", "Asterix (Europe).sms")),
    ("rumblef2.zip.nvmem", ("sram", None, "rumblef2")),
    ("Doom.save.zip", ("sram", None, "Doom")),
    ("Zelda_2.dss", ("state", "2", "Zelda")),
    ("Earthworm Jim (USA).md.mds.gz", ("state", "0", "Earthworm Jim (USA).md")),
    ("Castle of Illusion (USA).md.1.mds.gz", ("state", "1", "Castle of Illusion (USA).md")),
    ("Asterix (Europe).sms.st0pic", None),
    ("Super Mario World (USA).state1.png", None),
    ("readme.txt", None),
])
def test_classify(name, expected):
    assert classify(name) == expected


def test_save_path_guard():
    assert is_save_path("/mnt/mmc/saves_RA/Roms/SFC/Snes9x/Mario.srm", BASE, ROMS)
    assert is_save_path("/mnt/mmc/Roms/GBA/Metroid (USA).sav", BASE, ROMS)
    assert not is_save_path("/mnt/mmc/Roms/GBA/Metroid (USA).gba", BASE, ROMS)  # une ROM
    assert not is_save_path("/mnt/mmc/saves_RA/Roms/../../etc/passwd.srm", BASE, ROMS)
    assert not is_save_path("/mnt/mmc/saves_RA/Roms/SFC/notes.txt", BASE, ROMS)
    assert not is_save_path("/etc/shadow", BASE, ROMS)


def test_hotkeys_from_config():
    ra = 'input_enable_hotkey_btn = "8"\ninput_save_state_btn = "5"\ninput_load_state_btn = "4"\n' \
         'input_exit_emulator_btn = "7"\ninput_state_slot_increase_btn = "h0right"\ninput_menu_toggle_btn = "nul"\n'
    pad = 'input_r_btn = "5"\ninput_l_btn = "4"\ninput_start_btn = "7"\ninput_right_btn = "h0right"\n'
    keys = {h.action: h.combo for h in hotkeys(ra, pad)}
    assert keys == {"save_state": ["Menu", "R1"], "load_state": ["Menu", "L1"], "quit": ["Menu", "Start"],
                    "slot_next": ["Menu", "→"]}


def make(app_factory, console=None):
    app = app_factory()
    app.state.device_runner = console or FakeConsole()
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_list_and_match_saves(app_factory, ssh_server):
    _, c = make(app_factory)
    async with c:
        await sync(c)
        saves = (await c.get("/api/saves")).json()["saves"]
        by = {(s["platform"], s["kind"], s["slot"]): s for s in saves}
        mario_sram = by[("SFC", "sram", None)]
        assert mario_sram["game"]["title"] == "Super Mario World" and mario_sram["source"] == "retroarch"
        assert by[("SFC", "state", "1")]["game"]["title"] == "Super Mario World"
        assert by[("SFC", "state", "auto")]["size"] == 4
        stock = next(s for s in saves if s["source"] == "stock")
        assert stock["game"]["title"] == "Sonic The Hedgehog" and stock["slot"] == "0"
        unknown = next(s for s in saves if s["name"] == "Unknown Game (USA)")
        assert unknown["game"] is None
        assert not any(s["path"].endswith((".png", "st0pic")) for s in saves)  # miniatures ignorées

        mario_id = mario_sram["game"]["id"]
        assert len((await c.get(f"/api/games/{mario_id}/saves")).json()) == 3
        r = await c.get("/api/saves/file", params={"path": mario_sram["path"]})
        assert r.status_code == 200 and r.content == b"SRAM-MARIO"
        r = await c.get("/api/saves/file", params={"path": "/mnt/mmc/Roms/SFC/Super Mario World (USA).smc"})
        assert r.status_code == 400  # une ROM n'est pas une sauvegarde
    assert ssh_server["sftp"].write_attempts == []


async def test_backup_to_mac_and_zip(app_factory, ssh_server):
    _, c = make(app_factory)
    async with c:
        await sync(c)
        snap = (await c.post("/api/saves/backup", json={})).json()
        assert len(snap["files"]) == 5 and not snap["auto"]
        assert {f["game_title"] for f in snap["files"]} >= {"Super Mario World", "Sonic The Hedgehog"}
        assert [b["id"] for b in (await c.get("/api/saves/backups")).json()] == [snap["id"]]
        z = zipfile.ZipFile(io.BytesIO((await c.get(f"/api/saves/backups/{snap['id']}/zip")).content))
        assert "saves_RA/Roms/SFC/Snes9x/Super Mario World (USA).srm" in z.namelist()
        assert z.read("saves_RA/Roms/SFC/Snes9x/Super Mario World (USA).srm") == b"SRAM-MARIO"
        assert (await c.delete(f"/api/saves/backups/{snap['id']}")).status_code == 204
        assert (await c.get("/api/saves/backups/../etc/zip")).status_code == 404
    assert ssh_server["sftp"].write_attempts == []


async def test_restore_and_delete_keep_a_copy(app_factory, ssh_server):
    ssh_server["sftp"].allow_writes = True
    app, c = make(app_factory)
    card = ssh_server["chroot"]
    srm = card / "mnt/mmc/saves_RA/Roms/SFC/Snes9x/Super Mario World (USA).srm"
    async with c:
        await sync(c)
        snap = (await c.post("/api/saves/backup", json={})).json()
        srm.write_bytes(b"PARTIE-RATEE")
        rel = "saves_RA/Roms/SFC/Snes9x/Super Mario World (USA).srm"
        r = await c.post("/api/saves/restore", json={"backup_id": snap["id"], "rel": rel})
        assert r.status_code == 200, r.text
        assert srm.read_bytes() == b"SRAM-MARIO"
        safety = r.json()["previous_copy"]
        assert app.state.save_vault.read(safety, rel) == b"PARTIE-RATEE"  # l'état remplacé est gardé

        r = await c.post("/api/saves/delete", json={"path": "/mnt/mmc/" + rel})
        assert r.status_code == 200 and not srm.exists()
        assert app.state.save_vault.read(r.json()["copy"], rel) == b"SRAM-MARIO"
        r = await c.post("/api/saves/delete", json={"path": "/mnt/mmc/Roms/SFC/Super Mario World (USA).smc"})
        assert r.status_code == 400
        assert not any(".agm-" in p.name for p in srm.parent.iterdir())


async def test_writes_refused_while_playing(app_factory, ssh_server):
    ssh_server["sftp"].allow_writes = True
    console = FakeConsole(playing="/mnt/mmc/Roms/SFC/Super Mario World (USA).smc")
    _, c = make(app_factory, console)
    async with c:
        await sync(c)
        r = await c.post("/api/saves/delete",
                         json={"path": "/mnt/mmc/saves_RA/Roms/SFC/Snes9x/Super Mario World (USA).srm"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "game_running"
        assert (await c.post("/api/device/save-state")).json() == {"result": "saved"}
        assert "SAVE_STATE" in console.commands[-1]
