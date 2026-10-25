"""Le Manager sur le téléphone : QR code à usage unique, seuls les téléphones associés passent (app.services.phone)."""

import socket

import httpx
import pytest

from app.services import phone

LAN = "http://192.168.1.20:8765"


@pytest.fixture
async def setup(app_factory, monkeypatch):
    app = app_factory()
    access = app.state.phone
    access.in_docker = False
    monkeypatch.setattr(phone, "lan_ip", lambda: "192.168.1.20")

    async def listen(ip, port):  # le serveur du réseau local est essayé à part (test_real_listener)
        access.bound = (ip, port)

    monkeypatch.setattr(access, "listen", listen)
    async with (httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as local,
                httpx.AsyncClient(transport=httpx.ASGITransport(app=phone.PhoneGate(app, access)), base_url=LAN) as tel):
        yield app, local, tel


async def pair(local) -> str:
    r = await local.post("/api/phone/pair", headers={"Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"].startswith(f"{LAN}/telephone/") and body["qr"].startswith("data:image/svg+xml")
    return body["url"][len(LAN):]


async def test_phone_needs_the_qr_code(setup):
    _, local, tel = setup
    assert (await tel.get("/api/health")).status_code == 403
    assert (await tel.get("/telephone/n-importe-quoi")).status_code == 403
    path = await pair(local)
    r = await tel.get(path)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert tel.cookies.get(phone.DEVICE_COOKIE) == "phone"
    assert (await tel.get("/api/health")).status_code == 200
    assert (await local.get("/api/phone")).json()["devices"] == 1

    # Le jeton ne sert qu'une fois, même pour un autre téléphone.
    async with httpx.AsyncClient(transport=tel._transport, base_url=LAN) as other:
        assert (await other.get(path)).status_code == 403
        assert (await other.get("/api/health")).status_code == 403


async def test_phone_origin_and_rights(setup):
    _, local, tel = setup
    await tel.get(await pair(local))
    r = await tel.post("/api/catalog/sync", headers={"Origin": LAN})
    assert r.status_code == 202
    r = await tel.post("/api/catalog/sync", headers={"Origin": "https://evil.example"})
    assert r.json()["error"]["code"] == "origin_not_allowed"
    # Associer ou déconnecter : depuis l'ordinateur seulement.
    r = await tel.post("/api/phone/pair", headers={"Origin": LAN})
    assert r.json()["error"]["code"] == "phone_forbidden"


async def test_disconnect(setup):
    _, local, tel = setup
    await tel.get(await pair(local))
    r = await local.delete("/api/phone", headers={"Origin": "http://127.0.0.1:8765"})
    assert r.json()["devices"] == 0
    assert (await tel.get("/api/health")).status_code == 403


async def test_lan_address_never_reaches_the_local_server_directly(setup):
    app, local, tel = setup
    await tel.get(await pair(local))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=LAN, cookies=tel.cookies) as c:
        r = await c.get("/api/settings")
    assert r.json()["error"]["code"] == "host_not_allowed"


async def test_expired_token(setup, monkeypatch):
    _, local, tel = setup
    path = await pair(local)
    monkeypatch.setattr(phone.time, "time", lambda: 10**12)
    assert (await tel.get(path)).status_code == 403


async def test_docker(setup):
    app, local, _ = setup
    app.state.phone.in_docker = True
    r = await local.post("/api/phone/pair", headers={"Origin": "http://127.0.0.1:8765"})
    assert r.json()["error"]["code"] == "phone_docker"


async def test_real_listener(app_factory, tmp_path):
    """Second serveur uvicorn dans la même boucle : il répond, puis se ferme."""
    app = app_factory()
    access = app.state.phone
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    await access.listen("127.0.0.1", port)
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"http://127.0.0.1:{port}/api/health")
        assert r.status_code == 403 and "QR code" in r.text
        with pytest.raises(Exception):  # port déjà pris : erreur propre, pas de sortie du processus
            other = phone.PhoneAccess(tmp_path / "p.json", in_docker=False)
            other.app = app
            await other.listen("127.0.0.1", port)
    finally:
        await access.stop()
    async with httpx.AsyncClient() as c:
        with pytest.raises(httpx.ConnectError):
            await c.get(f"http://127.0.0.1:{port}/api/health")
