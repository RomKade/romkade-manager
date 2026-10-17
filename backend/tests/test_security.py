"""Le serveur local refuse les requêtes venues d'autres sites et le DNS rebinding."""

import httpx
import pytest


@pytest.fixture
async def local(app_factory):
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as c:
        yield c


async def test_localhost_allowed(local):
    assert (await local.get("/api/health")).status_code == 200
    r = await local.post("/api/catalog/sync", headers={"Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 202
    r = await local.post("/api/transfers/plan", headers={"Origin": "http://localhost:5173"}, json={"items": [{"upload_id": "0" * 32}]})
    assert r.json()["error"]["code"] == "upload_not_found"  # passe le filtre, échoue plus loin


@pytest.mark.parametrize("method,path", [("POST", "/api/catalog/sync"), ("PUT", "/api/uploads?filename=a.smc"),
                                         ("POST", "/api/transfers"), ("PUT", "/api/settings/password")])
async def test_foreign_origin_cannot_change_anything(local, ssh_server, method, path):
    r = await local.request(method, path, headers={"Origin": "https://evil.example"}, content=b"{}")
    assert r.status_code == 403 and r.json()["error"]["code"] == "origin_not_allowed"
    r = await local.request(method, path, headers={"Origin": "null"}, content=b"{}")
    assert r.status_code == 403
    assert ssh_server["sftp"].write_attempts == []


async def test_dns_rebinding_blocked(app_factory):
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://evil.example:8765") as c:
        r = await c.get("/api/settings")
    assert r.status_code == 403 and r.json()["error"]["code"] == "host_not_allowed"


async def test_foreign_origin_can_not_read_either_via_cors(local):
    # Lecture GET autorisée côté serveur, mais aucun en-tête CORS : le navigateur la cache au site étranger.
    r = await local.get("/api/settings", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}
