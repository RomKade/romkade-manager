"""Manettes de l'ordinateur lues par le Manager : le relais vit dans le serveur, sans onglet (app.services.pc_pads)."""

import asyncio
import json
import sys

import httpx
import pytest

from app.services import pc_pads


def pads(*items) -> str:
    return json.dumps({"pads": [{"id": i, "name": n, "b": b, "a": [0, 0, 0, 0]} for i, n, b in items]})


B0 = [0.0] * 17
A_DOWN = [1.0] + [0.0] * 16
B_DOWN = [0.0, 1.0] + [0.0] * 15

# Faux lecteur : la manette apparaît, A est appuyé, la manette s'éteint, puis revient (nouvel identifiant SDL) avec B.
SCRIPT = "\n".join([
    "import sys, time",
    f"print({json.dumps(json.dumps({'ready': True}))}, flush=True)",
    f"print({json.dumps(pads((1, 'Xbox Wireless Controller', B0)))}, flush=True)",
    "time.sleep(0.6)",
    f"print({json.dumps(pads((1, 'Xbox Wireless Controller', A_DOWN)))}, flush=True)",
    "time.sleep(0.3)",
    f"print({json.dumps(pads())}, flush=True)",
    "time.sleep(0.3)",
    f"print({json.dumps(pads((7, 'Xbox Wireless Controller', B_DOWN)))}, flush=True)",
    "sys.stdin.read()",
])


class FakeRelay:
    created: list["FakeRelay"] = []

    def __init__(self, client, token):
        self.token, self.sent, self.closed = token, [], False
        FakeRelay.created.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True

    def send(self, b, a):
        self.sent.append(("send", list(b)))

    def release(self):
        self.sent.append(("release", None))


@pytest.fixture
async def client(app_factory, monkeypatch):
    FakeRelay.created = []
    monkeypatch.setattr(pc_pads, "Relay", FakeRelay)
    app = app_factory()
    app.state.pc_pads = pc_pads.PcPads(lambda: None, in_docker=False, worker_cmd=[sys.executable, "-c", SCRIPT])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as c:
        yield app, c
    await app.state.pc_pads.stop()


async def test_relay_lives_in_the_server_and_follows_the_pad(client):
    app, c = client
    r = await c.get("/api/pc-pads")
    body = r.json()
    assert body["available"] and body["pads"] == [{"id": 1, "name": "Xbox Wireless Controller", "relayed": False}]

    r = await c.post("/api/pc-pads/relays", json={"pad": 1}, headers={"Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 201 and r.json()["status"] == "live" and r.json()["token"].startswith("pc")
    token = r.json()["token"]

    await asyncio.sleep(1.6)  # A appuyé, manette éteinte, puis revenue avec un autre identifiant
    sent = FakeRelay.created[0].sent
    assert ("send", A_DOWN) in sent                        # appui relayé, sans navigateur
    assert ("release", None) in sent                       # manette éteinte : tout relâché sur la console
    assert sent[-1] == ("send", B_DOWN)                    # rallumée : le même relais la reprend
    snap = (await c.get("/api/pc-pads")).json()
    assert snap["relays"][0]["pad"] == 7 and snap["pads"][0]["relayed"]

    r = await c.delete(f"/api/pc-pads/relays/{token}", headers={"Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 204 and FakeRelay.created[0].closed
    assert (await c.get("/api/pc-pads")).json()["relays"] == []


async def test_unknown_pad_and_docker(client):
    app, c = client
    await c.get("/api/pc-pads")
    r = await c.post("/api/pc-pads/relays", json={"pad": 99}, headers={"Origin": "http://127.0.0.1:8765"})
    assert r.json()["error"]["code"] == "pc_pad_missing"
    docker = pc_pads.PcPads(lambda: None, in_docker=True)
    assert docker.snapshot()["available"] is False and docker.reason == "docker"
