import asyncio
import os
import shutil

import httpx
import pytest

from app.config import DeviceSettings


async def sync(c: httpx.AsyncClient, expect: str = "completed") -> dict:
    r = await c.post("/api/catalog/sync")
    assert r.status_code == 202, r.text
    run_id = r.json()["id"]
    for _ in range(200):
        run = (await c.get(f"/api/catalog/sync/{run_id}")).json()
        if run["status"] != "running":
            break
        await asyncio.sleep(0.02)
    assert run["status"] == expect, run
    return run


async def games(c, **params) -> dict:
    r = await c.get("/api/games", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_status_before_first_sync(client):
    st = (await client.get("/api/catalog/status")).json()
    assert st["synced"] is False and st["game_count"] == 0 and st["last_run"] is None


async def test_first_sync_builds_catalog(client, ssh_server):
    run = await sync(client)
    assert run["added"] == 10 and run["removed"] == 0 and run["platforms_total"] == 7
    assert run["images_seen"] == 3 and run["images_matched"] == 2

    st = (await client.get("/api/catalog/status")).json()
    assert st["synced"] and st["game_count"] == 5 and st["storage_free_bytes"] > 0

    titles = {g["title"] for g in (await games(client))["items"]}
    # Ni images, ni pistes .bin, ni fichiers texte, ni programmes PORTS/APPS
    assert titles == {"Ridge Racer", "FF7", "Super Mario World", "Sonic The Hedgehog", "mystery"}
    assert (await games(client))["page"]["total"] == 5

    plats = {p["directory"]: p for p in (await client.get("/api/platforms")).json()}
    assert plats["PORTS"]["game_count"] == 0 and plats["PORTS"]["file_count"] == 2
    assert plats["MD"]["image_count"] == 2 and plats["MD"]["images_matched"] == 1
    assert ssh_server["sftp"].write_attempts == []


async def test_search_filters_sort(client):
    await sync(client)
    assert [g["title"] for g in (await games(client, q="mario"))["items"]] == ["Super Mario World"]
    assert [g["title"] for g in (await games(client, q="SONIC europe"))["items"]] == ["Sonic The Hedgehog"]
    assert {g["platform"]["directory"] for g in (await games(client, platform=["PS"]))["items"]} == {"PS"}
    assert [g["extension"] for g in (await games(client, extension="chd"))["items"]] == ["chd"]
    assert [g["title"] for g in (await games(client, region="Europe"))["items"]] == ["Ridge Racer", "Sonic The Hedgehog"]
    by_size = await games(client, sort="size", order="desc", limit=2)
    assert by_size["page"] == {"total": 5, "offset": 0, "limit": 2}
    assert by_size["items"][0]["title"] == "Sonic The Hedgehog"
    with_img = await games(client, has_image=True)
    assert {g["title"] for g in with_img["items"]} == {"Ridge Racer", "Sonic The Hedgehog"}
    assert all(g["metadata_status"] == "not_fetched" for g in with_img["items"])
    all_roles = await games(client, role="all", platform=["PS"])
    assert {g["role"] for g in all_roles["items"]} == {"candidate", "component"}


async def test_game_detail_and_image_cache(client, app_factory, ssh_server):
    await sync(client)
    rr = (await games(client, q="ridge"))["items"][0]
    d = (await client.get(f"/api/games/{rr['id']}")).json()
    assert d["remote_path"] == "/mnt/mmc/Roms/PS/Ridge Racer (Europe).chd"
    assert d["image_relpath"] == "Imgs/Ridge Racer (Europe).png"
    assert d["history"][0]["change"] == "added"

    img = await client.get(rr["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and len(img.content) == 300

    # Console injoignable : l'image reste servie depuis le cache, et le catalogue reste consultable
    app = client._transport.app
    s = app.state.settings_store.load()
    app.state.settings_store.save(DeviceSettings(**{**s.model_dump(), "port": 1, "connect_timeout": 1}))
    assert (await client.get(rr["image_url"])).status_code == 200
    assert (await games(client))["page"]["total"] == 5
    assert (await client.get("/api/games/999999")).json()["error"]["code"] == "game_not_found"
    assert ssh_server["sftp"].write_attempts == []


async def test_resync_detects_changes(client, ssh_server):
    await sync(client)
    roms = ssh_server["chroot"] / "mnt/mmc/Roms"
    (roms / "SFC/Super Mario World (USA).smc").unlink()
    (roms / "SFC/Zelda (Europe).sfc").write_bytes(b"\0" * 1024)
    (roms / "MD/Sonic The Hedgehog (Europe).md").write_bytes(b"\1" * 100)
    os.utime(roms / "MD/Sonic The Hedgehog (Europe).md", (1_700_000_000, 1_700_000_000))

    run = await sync(client)
    assert (run["added"], run["modified"], run["removed"]) == (1, 1, 1)

    ch = (await client.get("/api/catalog/changes")).json()
    assert {(i["change"], i["game"]["filename"]) for i in ch["items"]} == {
        ("added", "Zelda (Europe).sfc"), ("modified", "Sonic The Hedgehog (Europe).md"),
        ("removed", "Super Mario World (USA).smc")}

    assert [g["title"] for g in (await games(client, q="mario"))["items"]] == []
    gone = (await games(client, q="mario", include_removed=True))["items"]
    assert gone[0]["present"] is False

    # Le fichier revient : il est "restored", avec le même identifiant
    (roms / "SFC/Super Mario World (USA).smc").write_bytes(b"\0" * 512)
    run = await sync(client)
    assert run["restored"] == 1
    back = (await games(client, q="mario"))["items"][0]
    assert back["id"] == gone[0]["id"] and back["present"] is True
    assert ssh_server["sftp"].write_attempts == []


async def test_platform_folder_removed(client, ssh_server):
    await sync(client)
    shutil.rmtree(ssh_server["chroot"] / "mnt/mmc/Roms/ZZNEW")
    run = await sync(client)
    assert run["removed"] == 1
    plats = {p["directory"] for p in (await client.get("/api/platforms")).json()}
    assert "ZZNEW" not in plats
    absent = {p["directory"]: p for p in (await client.get("/api/platforms", params={"include_absent": True})).json()}
    assert absent["ZZNEW"]["present"] is False


async def test_safety_root_missing_changes_nothing(client, ssh_server):
    await sync(client)
    roms = ssh_server["chroot"] / "mnt/mmc/Roms"
    roms.rename(roms.with_name("Roms.unplugged"))
    run = await sync(client, expect="failed")
    assert "remote_not_found" in run["error"]
    assert (await games(client))["page"]["total"] == 5  # rien marqué supprimé


async def test_safety_root_empty_changes_nothing(client, ssh_server):
    await sync(client)
    roms = ssh_server["chroot"] / "mnt/mmc/Roms"
    shutil.rmtree(roms)
    roms.mkdir()
    run = await sync(client, expect="failed")
    assert "root_empty" in run["error"]
    assert (await games(client))["page"]["total"] == 5


async def test_platform_scan_error_keeps_its_files(client, ssh_server, monkeypatch):
    await sync(client)
    from app.services import inventory
    original = inventory.scan_platform

    async def flaky(fs, platform, include_files=True):
        if platform.directory == "SFC":
            raise OSError("lecture interrompue")
        return await original(fs, platform, include_files)

    monkeypatch.setattr(inventory, "scan_platform", flaky)
    (ssh_server["chroot"] / "mnt/mmc/Roms/SFC/Super Mario World (USA).smc").unlink()
    run = await sync(client, expect="partial")
    assert "SFC" in run["platform_errors"] and run["removed"] == 0
    assert [g["title"] for g in (await games(client, q="mario"))["items"]] == ["Super Mario World"]


async def test_duplicates(client, ssh_server):
    roms = ssh_server["chroot"] / "mnt/mmc/Roms"
    (roms / "PS/Ridge Racer (USA).chd").write_bytes(b"\0" * 1200)
    (roms / "SFC/Super Mario World (Europe).sfc").write_bytes(b"\0" * 999)
    await sync(client)
    groups = {(g["platform"]["directory"], g["normalized_title"]): g for g in (await client.get("/api/catalog/duplicates")).json()}
    assert groups[("PS", "ridge racer")]["confidence"] == "likely"
    assert groups[("SFC", "super mario world")]["confidence"] == "possible"
    rr = (await games(client, q="ridge racer europe"))["items"][0]
    detail = (await client.get(f"/api/games/{rr['id']}")).json()
    assert [d["filename"] for d in detail["possible_duplicates"]] == ["Ridge Racer (USA).chd"]


async def test_unmatched_images(client):
    await sync(client)
    out = {u["platform"]["directory"]: u for u in (await client.get("/api/catalog/unmatched-images")).json()}
    assert out["MD"]["sample"] == ["Orphan Game.png"]


async def test_sync_already_running(client):
    app = client._transport.app
    await app.state.sync.lock.acquire()
    try:
        r = await client.post("/api/catalog/sync")
        assert r.status_code == 409 and r.json()["error"]["code"] == "sync_already_running"
    finally:
        app.state.sync.lock.release()


async def test_sync_auth_failure_recorded(app_factory):
    app = app_factory(password="wrong")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        run = await sync(c, expect="failed")
    assert run["error"].startswith("device_auth_failed")


def test_interrupted_run_recovered_on_restart(tmp_path):
    from app.db.models import ScanRun
    from app.db.session import init_db
    sessions = init_db(tmp_path / "c.sqlite3")
    with sessions.begin() as s:
        from app.db.models import Device
        s.add(Device(id=1, host="h", port=22, username="root", roms_root="/mnt/mmc/Roms"))
        s.add(ScanRun(device_id=1, status="running"))
    sessions = init_db(tmp_path / "c.sqlite3")
    with sessions() as s:
        assert s.get(ScanRun, 1).status == "interrupted"


@pytest.mark.parametrize("bad", [{"limit": 0}, {"limit": 501}, {"sort": "random"}, {"offset": -1}])
async def test_games_param_validation(client, bad):
    r = await client.get("/api/games", params=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
