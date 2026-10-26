import httpx


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_health(client):
    r = await client.get("/api/health")
    assert r.json()["status"] == "ok" and r.json()["writes"] == "transfers_only"


async def test_settings_never_expose_password(client):
    r = await client.get("/api/settings")
    body = r.json()
    assert r.status_code == 200 and body["has_password"] is True and body["host_key_trusted"] is True
    assert "secret" not in r.text and "password" not in {k for k in body if k != "has_password"}


async def test_test_connection(client, ssh_server):
    r = await client.post("/api/device/test-connection")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] and body["sftp"] and body["roms_root_exists"]
    assert body["platform_dir_count"] == 7  # APPS, LINKED, MD, PORTS, PS, SFC, ZZNEW
    assert body["storage"]["method"] == "sftp_statvfs" and body["storage"]["total_bytes"] > 0
    assert ssh_server["sftp"].write_attempts == []


async def test_platforms(client):
    r = await client.get("/api/device/platforms")
    by_dir = {p["directory"]: p for p in r.json()}
    assert by_dir["PS"]["label"] == "PlayStation" and by_dir["PS"]["label_status"] == "confirmed"
    assert by_dir["ZZNEW"]["known"] is False and by_dir["ZZNEW"]["label_status"] == "unmapped"
    assert by_dir["LINKED"]["is_symlink"] is True


async def test_inventory_rules(client, ssh_server):
    r = await client.get("/api/device/inventory", params={"include_files": True})
    assert r.status_code == 200, r.text
    inv = {p["directory"]: p for p in r.json()["platforms"]}

    ps = inv["PS"]
    roles = {f["relative_path"]: f["role"] for f in ps["files"]}
    assert roles == {"Ridge Racer (Europe).chd": "candidate", "Final Fantasy VII/FF7 (Disc 1).cue": "candidate",
                     "Final Fantasy VII/FF7 (Disc 1).bin": "component"}
    assert ps["image_dir_present"] and ps["image_count"] == 1  # l'image n'est pas un jeu
    assert ps["candidate_count"] == 2

    sfc = inv["SFC"]
    sfc_names = {f["relative_path"]: f for f in sfc["files"]}
    assert set(sfc_names) == {"Super Mario World (USA).smc", "readme.txt"}
    assert sfc_names["readme.txt"]["role"] == "auxiliary"
    assert sfc_names["Super Mario World (USA).smc"]["role"] == "candidate"
    assert sfc["candidate_count"] == 1
    assert any(".DS_Store" in s for s in sfc["skipped"]) and any("._Super" in s for s in sfc["skipped"])
    assert any("escape.smc" in s and "lien" in s for s in sfc["skipped"])
    assert any("profondeur" in s for s in sfc["skipped"])

    assert inv["MD"]["file_count"] == 1 and inv["MD"]["image_count"] == 2
    assert {f["role"] for f in inv["PORTS"]["files"]} == {"program"}
    assert inv["LINKED"]["file_count"] == 0  # lien vers /etc non suivi
    assert ssh_server["sftp"].write_attempts == []


async def test_inventory_without_files_by_default(client):
    r = await client.get("/api/device/inventory")
    assert all(p["files"] is None for p in r.json()["platforms"])


async def test_platform_files_pagination_sort_filter(client):
    r = await client.get("/api/device/platforms/PS/files", params={"limit": 2, "sort": "size", "order": "desc"})
    body = r.json()
    assert body["page"] == {"total": 3, "offset": 0, "limit": 2}
    assert [f["size"] for f in body["files"]] == [5000, 1200]

    r = await client.get("/api/device/platforms/PS/files", params={"q": "ridge"})
    assert [f["filename"] for f in r.json()["files"]] == ["Ridge Racer (Europe).chd"]

    r = await client.get("/api/device/platforms/SFC/files", params={"role": "candidate"})
    assert r.json()["page"]["total"] == 1


async def test_platform_traversal_rejected(client):
    r = await client.get("/api/device/platforms/..%2F..%2Fetc/files")
    assert r.status_code in (400, 404)
    r = await client.get("/api/device/inventory", params={"platform": ".."})
    assert r.status_code == 400 and r.json()["error"]["code"] == "path_forbidden"


async def test_unknown_platform_404(client):
    r = await client.get("/api/device/platforms/NOPE/files")
    assert r.status_code == 404 and r.json()["error"]["code"] == "platform_not_found"


async def test_wrong_password(app_factory):
    async with await _client(app_factory(password="wrong")) as c:
        r = await c.post("/api/device/test-connection")
    assert r.status_code == 502 and r.json()["error"]["code"] == "device_auth_failed"


async def test_missing_password(app_factory):
    async with await _client(app_factory(password=None)) as c:
        r = await c.get("/api/device/platforms")
    assert r.json()["error"]["code"] == "credentials_missing"


async def test_no_console_yet(app_factory):
    """Installation neuve : aucune adresse par défaut, la console est à indiquer (jamais celle d'un autre)."""
    from app.config import DeviceSettings
    assert DeviceSettings().host == ""
    app = app_factory()
    s = app.state.settings_store.load()
    app.state.settings_store.save(DeviceSettings(**{**s.model_dump(), "host": ""}))
    async with await _client(app) as c:
        status = (await c.get("/api/device/status")).json()
        key = await c.get("/api/device/host-key")
        diag = await c.post("/api/device/diagnose")
    assert status["connected"] is False and status["error"]["code"] == "console_not_configured"
    assert key.status_code == 409 and key.json()["error"]["code"] == "console_not_configured"
    assert diag.json()["error"]["code"] == "console_not_configured"


async def test_unreachable(app_factory, ssh_server):
    app = app_factory()
    from app.config import DeviceSettings
    s = app.state.settings_store.load()
    app.state.settings_store.save(DeviceSettings(**{**s.model_dump(), "port": 1, "connect_timeout": 2}))
    app.state.host_keys.trust("127.0.0.1", 1, ssh_server["host_key"])
    async with await _client(app) as c:
        r = await c.get("/api/device/status")
    assert r.json()["connected"] is False and r.json()["error"]["code"] == "device_ssh_refused"  # port fermé


async def test_wrong_root(app_factory):
    async with await _client(app_factory(roms_root="/mnt/nothing")) as c:
        r = await c.get("/api/device/platforms")
    assert r.status_code == 404 and r.json()["error"]["code"] == "remote_not_found"


async def test_host_key_tofu_flow(app_factory, ssh_server):
    app = app_factory(trust=False)
    async with await _client(app) as c:
        r = await c.get("/api/device/platforms")
        assert r.json()["error"]["code"] == "host_key_unknown"

        hk = (await c.get("/api/device/host-key")).json()
        assert hk["trusted"] is False and hk["fingerprint"].startswith("SHA256:")

        bad = await c.post("/api/device/host-key/trust", json={"fingerprint": "SHA256:nope"})
        assert bad.status_code == 409

        ok = await c.post("/api/device/host-key/trust", json={"fingerprint": hk["fingerprint"]})
        assert ok.json()["trusted"] is True
        assert (await c.get("/api/device/platforms")).status_code == 200


async def test_host_key_mismatch_blocks(app_factory, ssh_server):
    import asyncssh
    app = app_factory(trust=False)
    app.state.host_keys.trust("127.0.0.1", ssh_server["port"], asyncssh.generate_private_key("ssh-ed25519"))
    async with await _client(app) as c:
        r = await c.get("/api/device/platforms")
    assert r.json()["error"]["code"] == "host_key_mismatch"


async def test_storage_df_fallback(client, ssh_server):
    ssh_server["sftp"].statvfs_supported = False
    r = await client.get("/api/device/storage")
    body = r.json()
    assert r.status_code == 200, r.text
    assert body["method"] == "df" and body["free_bytes"] == 50000000 * 1024


async def test_settings_validation_structured_error(client):
    r = await client.put("/api/settings", json={"host": "h", "port": 22, "username": "root",
                                                "auth_method": "password", "roms_root": "/"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_presence_says_asleep_after_recent_contact():
    from app.device.presence import Presence
    from app.errors import AppError, device_unreachable

    p = Presence()
    exc = device_unreachable("192.168.1.42", 22, "OSError: Host is down")
    assert p.explain(exc, "192.168.1.42").code == "device_unreachable"  # jamais vue : on ne suppose rien
    p.seen("192.168.1.42")
    asleep = p.explain(exc, "192.168.1.42")
    assert asleep.code == "device_asleep" and asleep.status == 503 and "veille" in asleep.message
    assert p.explain(exc, "192.168.1.43").code == "device_unreachable"  # autre adresse
    other = AppError("device_auth_failed", "refusé", 502)
    assert p.explain(other, "192.168.1.42") is other
