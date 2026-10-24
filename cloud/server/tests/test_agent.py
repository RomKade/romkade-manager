"""Agent de la console (cloud/agent/romkade_agent.py) : sauvegardes lues sur la carte, favoris posés par le Manager."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))

import romkade_agent  # noqa: E402


def test_saves_of_a_game_read_on_the_card(tmp_path):
    for rel, data in {"Roms/SFC/Super Mario World (USA).sfc": b"R", "Roms/GBA/Metroid (USA).sav": b"S",
                      "saves_RA/Roms/SFC/Snes9x/Super Mario World (USA).srm": b"SRAM",
                      "states_RA/Roms/SFC/Snes9x/Super Mario World (USA).state1": b"ST",
                      "states_RA/Roms/SFC/Snes9x/Super Mario World (USA).state1.png": b"PNG"}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(data)
    os.utime(tmp_path / "saves_RA/Roms/SFC/Snes9x/Super Mario World (USA).srm", (1760000000, 1760000000))
    agent = romkade_agent.Agent({"server": "http://x"})
    agent.client.settings.roms_root = str(tmp_path / "Roms")

    out = asyncio.run(agent.do_saves({"names": ["super mario world (usa)", "super mario world (usa).sfc"]}))
    by = {(x["kind"], x["slot"]): x for x in out["saves"]}
    assert set(by) == {("sram", None), ("state", "1")} and out["total"] == 2   # miniature ignorée
    assert by[("sram", None)]["platform"] == "SFC" and by[("sram", None)]["modified"] == 1760000000
    every = asyncio.run(agent.do_saves({}))["saves"]
    assert {x["name"] for x in every} == {"Super Mario World (USA)", "Metroid (USA)"}


def test_favorites_file(tmp_path, monkeypatch):
    path = tmp_path / "favorites.json"
    monkeypatch.setattr(romkade_agent, "FAVORITES", path)
    assert romkade_agent.read_favorites() == (None, None)
    path.write_text('{"favorites": [["SFC", "Mario.sfc"]')  # en cours d'écriture par le Manager
    sig, favs = romkade_agent.read_favorites()
    assert sig and favs is None
    path.write_text(json.dumps({"favorites": [["SFC", "Mario.sfc"], ["bad"], ["MD", "Sonic.md"]]}))
    assert romkade_agent.read_favorites()[1] == [["SFC", "Mario.sfc"], ["MD", "Sonic.md"]]


def test_recent_games_from_retroarch_history(tmp_path):
    import json

    hist = tmp_path / "content_history.lpl"
    assert romkade_agent.read_recent(str(hist), "/mnt/mmc/Roms") == (None, None)
    hist.write_text(json.dumps({"items": [
        {"path": "/mnt/mmc/Roms/MD/Sonic.md"}, {"path": "/mnt/mmc/Roms/FBNEO/atetris.zip#atetris.bin"},
        {"path": "/mnt/sdcard/Roms/SFC/Ailleurs.sfc"}, {"path": "/mnt/mmc/Roms/MD/Sonic.md"}, {}]}))
    sig, recent = romkade_agent.read_recent(str(hist), "/mnt/mmc/Roms")
    assert sig and recent == [["MD", "Sonic.md"], ["FBNEO", "atetris.zip"]]
    hist.write_text("{ en cours d'écriture")
    assert romkade_agent.read_recent(str(hist), "/mnt/mmc/Roms")[1] is None
