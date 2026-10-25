"""Recherche de la console sur le réseau local (app/device/discover.py), sans réseau : résolutions et bannières simulées."""

import pytest

from app.device import discover

CONSOLE = "SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.7"
MAC = "SSH-2.0-OpenSSH_10.2"


@pytest.fixture
def lan(monkeypatch):
    """Une box en 192.168.86 : la console (nommée « anbernic » par la box ou non) et un Mac, SSH ouvert tous les deux."""
    state = {"dns": {"anbernic": "192.168.86.242", "anbernic.lan": "192.168.86.242"},
             "ssh": {"192.168.86.242": CONSOLE, "192.168.86.240": MAC},
             "rdns": {"192.168.86.242": "anbernic.lan", "192.168.86.240": "mac.lan"}, "probed": []}

    async def resolve(name):
        return state["dns"].get(name)

    async def banner(host, timeout=0):
        state["probed"].append(host)
        return state["ssh"].get(host)

    async def name_of(ip):
        return state["rdns"].get(ip)

    monkeypatch.setattr(discover, "_resolve", resolve)
    monkeypatch.setattr(discover, "_banner", banner)
    monkeypatch.setattr(discover, "_name_of", name_of)
    monkeypatch.setattr(discover, "_own_subnets", lambda: [])
    monkeypatch.setattr(discover, "COMMON", ("192.168.86",))
    return state


async def test_found_by_name_without_scanning(lan):
    out = await discover.discover()
    assert out == {"consoles": [{"host": "192.168.86.242", "name": "anbernic", "banner": CONSOLE, "likely": True}],
                   "scanned": False}
    assert lan["probed"] == ["192.168.86.242"]


async def test_scan_when_no_name_console_first(lan):
    lan["dns"] = {}
    out = await discover.discover()
    assert out["scanned"] is True
    assert [(c["host"], c["name"], c["likely"]) for c in out["consoles"]] == [
        ("192.168.86.242", "anbernic.lan", True), ("192.168.86.240", "mac.lan", False)]


async def test_unknown_firmware_still_proposed(lan):
    """Ni nom ni bannière reconnus : l'adresse est proposée quand même, l'utilisateur choisit."""
    lan["dns"], lan["rdns"] = {}, {}
    lan["ssh"] = {"192.168.86.30": "SSH-2.0-dropbear_2022.83"}
    out = await discover.discover()
    assert out["consoles"] == [{"host": "192.168.86.30", "name": None, "banner": "SSH-2.0-dropbear_2022.83", "likely": False}]


async def test_forced_scan_adds_other_hosts(lan):
    out = await discover.discover(scan=True)
    assert [c["host"] for c in out["consoles"]] == ["192.168.86.242", "192.168.86.240"]


async def test_route(client, monkeypatch):
    async def fake(scan=False):
        return {"consoles": [{"host": "192.168.1.20", "name": "knulli", "banner": "SSH-2.0-x", "likely": True}], "scanned": scan}
    monkeypatch.setattr(discover, "discover", fake)
    r = await client.post("/api/device/discover", params={"scan": "true"})
    assert r.status_code == 200 and r.json()["scanned"] is True and r.json()["consoles"][0]["host"] == "192.168.1.20"
