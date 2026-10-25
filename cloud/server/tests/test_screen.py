"""Écran de l'app ROMKADE de la console (agent/screen.py) : chaque état se dessine (en anglais)."""

import importlib.util
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("screen", Path(__file__).parents[2] / "agent" / "screen.py")
screen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen)


@pytest.mark.parametrize("state", [
    {"status": "code", "code": "X52A4H", "code_until": time.time() + 600},
    {"status": "paired", "name": "My RG35XX", "games": 4838},
    {"status": "updated", "name": "My RG35XX"},
    {"status": "connecting"},
    {"status": "offline"},
])
def test_every_screen_renders(state):
    for size in ((640, 480), (720, 720), (720, 480)):
        img = screen.render(state, size)
        assert img.size == size
        assert img.getbbox() is not None


def test_state_from_agent_status(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    monkeypatch.setattr(screen, "STATUS", status)
    started = time.time()
    assert screen.current_state(started)["status"] == "connecting"
    status.write_text('{"online": true, "paired": false, "code": "AB3CD9", "at": %f}' % time.time())
    assert screen.current_state(started)["status"] == "code"
    status.write_text('{"online": true, "paired": true, "at": %f}' % time.time())
    assert screen.current_state(started)["status"] == "paired"
