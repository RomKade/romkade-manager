"""Manette de l'ordinateur : traduction des appuis du navigateur et WebSocket (sans console : Relay simulé)."""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import gamepad as api
from app.config import DeviceSettings, SettingsStore
from app.credentials import MemoryStore
from app.device.gamepad import Relay, changes, to_events
from app.device.players import parse_controllers
from app.errors import AppError
from app.main import create_app

WS = "ws://127.0.0.1:8765/api/gamepad/ws?token=ab12"  # adresse complète : sinon TestClient prend « testserver » comme hôte
ORIGIN = {"origin": "http://127.0.0.1:8765"}


def test_rest_state_and_buttons():
    rest = to_events([], [])
    assert set(rest.values()) == {0}
    b = [0.0] * 17
    b[0] = b[9] = b[16] = 1.0  # A, Start, Xbox
    b[7] = 0.5  # RT à moitié
    b[12] = b[14] = 1.0  # croix haut + gauche
    s = to_events(b, [1.0, -1.0, 0.0, 2.0])
    assert s[(1, 304)] == s[(1, 315)] == s[(1, 316)] == 1 and s[(1, 305)] == 0
    assert s[(3, 5)] == 128 and s[(3, 2)] == 0
    assert (s[(3, 16)], s[(3, 17)]) == (-1, -1)
    assert (s[(3, 0)], s[(3, 1)], s[(3, 4)]) == (32767, -32767, 32767)  # borné à ±1


def test_changes_only_sends_what_moved():
    rest = to_events([], [])
    pressed = to_events([1.0], [])
    assert changes(rest, pressed) == "1,304,1"
    assert changes(pressed, pressed) == ""
    assert changes(pressed, rest) == "1,304,0"


def test_relay_token_is_checked():
    with pytest.raises(AppError):
        Relay(None, "x; reboot")
    assert Relay(None, "ab12").command.endswith(" ab12")


def test_relayed_controller_is_recognised():
    devices = """I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="ANBERNIC-keys"
P: Phys=gpio-keys-polled/input0
H: Handlers=kbd js0 event1

I: Bus=0003 Vendor=045e Product=028e Version=0114
N: Name="Microsoft X-Box 360 pad"
P: Phys=romkade-relay-ab12
H: Handlers=js1 event4
"""
    c = parse_controllers(devices)
    assert [x["remote"] for x in c] == [None, "ab12"]
    assert c[1]["usb_id"] == "045e:028e" and not c[1]["builtin"]


class FakeRelay:
    sent: list = []

    def __init__(self, client, token):
        FakeRelay.token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        FakeRelay.sent.append("closed")

    def send(self, buttons, axes):
        FakeRelay.sent.append((buttons, axes))

    def release(self):
        FakeRelay.sent.append("release")


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path / "settings.json")
    store.save(DeviceSettings(host="127.0.0.1", port=22, username="root", roms_root="/mnt/mmc/Roms",
                              system="anbernic-stock-mod"))
    app = create_app(store, MemoryStore(), tmp_path / "known_hosts", db_path=tmp_path / "c.sqlite3",
                     cache_dir=tmp_path / "cache", staging_dir=tmp_path / "staging")
    monkeypatch.setattr(api, "Relay", FakeRelay)
    FakeRelay.sent = []
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_ws_relays_state(client):
    with client.websocket_connect(WS, headers=ORIGIN) as ws:
        assert ws.receive_json() == {"ready": True}
        ws.send_text('{"b": [1, 0, true, "x"], "a": [0.5]}')
        ws.send_text("pas du json")
        ws.send_text('{"release": true}')
    assert FakeRelay.token == "ab12"
    assert FakeRelay.sent[0] == ([1.0, 0.0], [0.5])
    assert FakeRelay.sent[1:] == ["release", "closed"]


@pytest.mark.parametrize("headers", [{}, {"origin": "https://evil.example"}, {"origin": "null"}])
def test_ws_refused_from_other_sites(client, headers):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(WS, headers=headers) as ws:
            ws.receive_json()
    assert exc.value.code == 1008
    assert FakeRelay.sent == []
