"""Transferts Mac -> console : fichier temporaire, vérification, conflits, sauvegarde, espace, annulation."""

import asyncio
import hashlib
import re
import sqlite3

import httpx
import pytest

from conftest import ShellBehaviour
from test_catalog import games, sync

SMW = "Super Mario World (USA).smc"
ALLOWED_WRITE = re.compile(
    r"^(open-write|rename|rename-to|remove) /mnt/mmc/Roms/(SFC|MD|PS|ZZNEW)/(\.agm-[0-9a-f]{32}\.part|[^/.][^/]*)$"
    r"|^(mkdir /mnt/mmc/Roms/\.agm-backups(/(SFC|MD|PS|ZZNEW))?)$"
    r"|^rename-to /mnt/mmc/Roms/\.agm-backups/(SFC|MD|PS|ZZNEW)/[^/]+\.\d{8}-\d{6}$"
)


@pytest.fixture
async def wclient(client, ssh_server):
    ssh_server["sftp"].allow_writes = True
    await sync(client)
    yield client


def roms(ssh_server):
    return ssh_server["chroot"] / "mnt/mmc/Roms"


async def upload(c: httpx.AsyncClient, name: str, data: bytes) -> dict:
    r = await c.put("/api/uploads", params={"filename": name}, content=data)
    assert r.status_code == 200, r.text
    return r.json()


async def plan(c, *items) -> dict:
    r = await c.post("/api/transfers/plan", json={"items": [dict(upload_id=u, **({"platform": p} if p else {})) for u, p in items]})
    assert r.status_code == 200, r.text
    return r.json()


async def run(c, items, confirm=False, expect=202):
    r = await c.post("/api/transfers", json={"items": items, "confirm_overwrite": confirm})
    assert r.status_code == expect, r.text
    if expect != 202:
        return r.json()
    await c._transport.app.state.transfers.wait_idle()
    return [(await c.get(f"/api/transfers/{t['id']}")).json() for t in r.json()]


def assert_writes_confined(ssh_server):
    bad = [w for w in ssh_server["sftp"].write_attempts if not ALLOWED_WRITE.match(w)]
    assert bad == [], bad


def no_temp_left(ssh_server):
    return not any(p.name.startswith(".agm-") and p.suffix == ".part" for p in roms(ssh_server).rglob("*"))


async def test_upload_hashes_and_stages(wclient):
    up = await upload(wclient, "Zelda (Europe).sfc", b"zelda" * 1000)
    assert up["size"] == 5000 and up["sha256"] == hashlib.sha256(b"zelda" * 1000).hexdigest()
    assert [u["id"] for u in (await wclient.get("/api/uploads")).json()] == [up["id"]]


@pytest.mark.parametrize("bad", ["../evil.smc", "a/b.smc", "a:b.smc", ".hidden.smc", "ends.", " lead.smc", "x" * 241 + ".smc"])
async def test_upload_rejects_dangerous_names(wclient, bad):
    r = await wclient.put("/api/uploads", params={"filename": bad}, content=b"x")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_filename"


async def test_empty_upload_refused(wclient):
    r = await wclient.put("/api/uploads", params={"filename": "empty.smc"}, content=b"")
    assert r.json()["error"]["code"] == "empty_file"


async def test_full_transfer_temp_verify_rename_and_catalog(wclient, ssh_server):
    data = b"\x01" * 70_000
    up = await upload(wclient, "Zelda (Europe).sfc", data)
    p = await plan(wclient, (up["id"], None))
    item = p["items"][0]
    assert item["platform"] == "SFC" and item["conflict"] is None and item["error"] is None and p["ready"]

    [t] = await run(wclient, [{"upload_id": up["id"], "platform": "SFC"}])
    assert t["status"] == "completed", t
    assert t["verify_method"] == "sha256" and t["remote_path"] == "/mnt/mmc/Roms/SFC/Zelda (Europe).sfc"
    assert (roms(ssh_server) / "SFC/Zelda (Europe).sfc").read_bytes() == data
    assert no_temp_left(ssh_server)
    # écrit sous un nom temporaire puis renommé
    w = ssh_server["sftp"].write_attempts
    assert any(re.match(r"open-write .*/SFC/\.agm-[0-9a-f]{32}\.part$", x) for x in w)
    assert "rename-to /mnt/mmc/Roms/SFC/Zelda (Europe).sfc" in w
    assert_writes_confined(ssh_server)
    # zone d'attente vidée, catalogue actualisé pour SFC seulement
    assert (await wclient.get("/api/uploads")).json() == []
    assert [g["filename"] for g in (await games(wclient, q="zelda"))["items"]] == ["Zelda (Europe).sfc"]
    runs = (await wclient.get("/api/catalog/syncs")).json()
    assert runs[0]["trigger"] == "transfer" and runs[0]["added"] == 1 and runs[0]["platforms_total"] == 1
    assert (await games(wclient))["page"]["total"] == 6  # rien d'autre n'a été marqué disparu


async def test_conflict_skipped_by_default(wclient, ssh_server):
    original = (roms(ssh_server) / f"SFC/{SMW}").read_bytes()
    up = await upload(wclient, SMW, b"new version")
    p = await plan(wclient, (up["id"], None))
    assert p["items"][0]["conflict"] == {"existing": SMW, "existing_size": 512, "same_size": False}
    [t] = await run(wclient, [{"upload_id": up["id"], "platform": "SFC"}])
    assert t["status"] == "skipped"
    assert (roms(ssh_server) / f"SFC/{SMW}").read_bytes() == original
    assert not any(w.startswith("open-write") for w in ssh_server["sftp"].write_attempts)


async def test_overwrite_needs_confirmation_and_keeps_backup(wclient, ssh_server):
    original = (roms(ssh_server) / f"SFC/{SMW}").read_bytes()
    up = await upload(wclient, SMW, b"patched rom")
    items = [{"upload_id": up["id"], "platform": "SFC", "on_conflict": "overwrite"}]
    err = await run(wclient, items, expect=409)
    assert err["error"]["code"] == "overwrite_not_confirmed" and err["error"]["details"]["files"] == [SMW]
    assert ssh_server["sftp"].write_attempts == []

    [t] = await run(wclient, items, confirm=True)
    assert t["status"] == "completed"
    assert (roms(ssh_server) / f"SFC/{SMW}").read_bytes() == b"patched rom"
    [backup] = list((roms(ssh_server) / ".agm-backups/SFC").iterdir())
    assert backup.name.startswith(SMW + ".") and backup.read_bytes() == original
    assert t["backup_path"] == f"/mnt/mmc/Roms/.agm-backups/SFC/{backup.name}"
    assert_writes_confined(ssh_server)
    # le dossier de sauvegarde est caché : il n'apparaît pas comme une console
    assert ".agm-backups" not in {p["directory"] for p in (await wclient.get("/api/platforms", params={"include_absent": True})).json()}


async def test_keep_both_renames(wclient, ssh_server):
    up = await upload(wclient, SMW, b"other dump")
    [t] = await run(wclient, [{"upload_id": up["id"], "platform": "SFC", "on_conflict": "rename"}])
    assert t["final_filename"] == "Super Mario World (USA) (2).smc"
    assert (roms(ssh_server) / "SFC/Super Mario World (USA) (2).smc").read_bytes() == b"other dump"
    assert (roms(ssh_server) / f"SFC/{SMW}").stat().st_size == 512


async def test_case_only_conflict_detected(wclient):
    up = await upload(wclient, SMW.lower(), b"x")
    c = (await plan(wclient, (up["id"], None)))["items"][0]["conflict"]
    assert c["existing"] == SMW and c["case_only"] is True


async def test_ambiguous_extension_requires_choice(wclient, ssh_server):
    up = await upload(wclient, "Mystery.bin", b"x" * 10)
    item = (await plan(wclient, (up["id"], None)))["items"][0]
    assert item["platform"] is None and item["error"]["code"] == "platform_required"
    assert {"MD", "PS"} <= set(item["platform_choices"])
    err = await run(wclient, [{"upload_id": up["id"], "platform": "APPS"}], expect=409)
    assert err["error"]["code"] == "plan_not_ready"
    [t] = await run(wclient, [{"upload_id": up["id"], "platform": "MD"}])
    assert t["status"] == "completed"


async def test_unusual_format_and_same_title_warn(wclient):
    up1 = await upload(wclient, "Notes.pdf", b"x")
    up2 = await upload(wclient, "Super Mario World (Europe).sfc", b"y")
    p = await plan(wclient, (up1["id"], "SFC"), (up2["id"], None))
    assert [w["code"] for w in p["items"][0]["warnings"]] == ["format_unusual"]
    w2 = p["items"][1]["warnings"]
    assert w2[0]["code"] == "same_title" and w2[0]["files"] == [SMW]
    assert p["ready"]  # avertissements non bloquants


@pytest.mark.parametrize("target,code", [("APPS", "platform_not_allowed"), ("PORTS", "platform_not_allowed"),
                                         ("LINKED", "platform_not_allowed"), ("NOPE", "platform_not_found"),
                                         ("../etc", "platform_not_allowed"), (".agm-backups", "platform_not_allowed")])
async def test_forbidden_destinations(wclient, ssh_server, target, code):
    up = await upload(wclient, "Game.smc", b"x")
    item = (await plan(wclient, (up["id"], target)))["items"][0]
    assert item["error"]["code"] == code
    await run(wclient, [{"upload_id": up["id"], "platform": target}], expect=409)
    assert ssh_server["sftp"].write_attempts == []


async def test_same_file_twice_in_batch(wclient):
    a = await upload(wclient, "Twin.smc", b"1")
    b = await upload(wclient, "twin.smc", b"2")
    p = await plan(wclient, (a["id"], None), (b["id"], None))
    assert p["items"][1]["error"]["code"] == "duplicate_in_batch" and not p["ready"]


async def test_insufficient_space_blocks_before_writing(wclient, ssh_server):
    ssh_server["sftp"].free_bytes = 100 * 1024**2  # 100 Mio libres, marge de 256 Mio
    up = await upload(wclient, "Big.smc", b"x" * 1000)
    p = await plan(wclient, (up["id"], None))
    assert p["fits"] is False and not p["ready"]
    err = await run(wclient, [{"upload_id": up["id"], "platform": "SFC"}], expect=409)
    assert err["error"]["code"] == "plan_not_ready"
    assert ssh_server["sftp"].write_attempts == []


async def test_space_rechecked_at_write_time(wclient, ssh_server, monkeypatch):
    """L'espace est revérifié juste avant l'écriture, même si le plan était bon."""
    from app.services import transfers as tr
    up = await upload(wclient, "Late.smc", b"x" * 1000)
    monkeypatch.setattr(tr, "margin_for", lambda total: 10**15)
    [t] = await run(wclient, [{"upload_id": up["id"], "platform": "SFC"}])
    assert t["status"] == "failed" and t["error"].startswith("insufficient_space") and t["retryable"]
    assert not (roms(ssh_server) / "SFC/Late.smc").exists() and no_temp_left(ssh_server)


async def test_hash_mismatch_fails_and_cleans_up(wclient, ssh_server):
    ShellBehaviour.sha256 = "wrong"
    up = await upload(wclient, "Corrupt.smc", b"data" * 100)
    [t] = await run(wclient, [{"upload_id": up["id"], "platform": "SFC"}])
    assert t["status"] == "failed" and "empreinte" in t["error"]
    assert not (roms(ssh_server) / "SFC/Corrupt.smc").exists() and no_temp_left(ssh_server)
    assert any(w.startswith("remove ") and ".agm-" in w for w in ssh_server["sftp"].write_attempts)


async def test_size_check_when_sha256sum_missing(wclient):
    ShellBehaviour.sha256 = "missing"
    up = await upload(wclient, "NoHash.smc", b"z" * 33)
    [t] = await run(wclient, [{"upload_id": up["id"], "platform": "SFC"}])
    assert t["status"] == "completed" and t["verify_method"] == "size"


async def test_cancel_during_copy_removes_temp(wclient, ssh_server, monkeypatch):
    from app.device.remote_writer import RemoteWriter
    started = asyncio.Event()
    original = RemoteWriter.upload_temp

    async def slow(self, local, ppath, token, progress):
        temp = await original(self, local, ppath, token, progress)
        started.set()
        await asyncio.sleep(30)  # la copie « traîne » : on annule pendant ce temps
        return temp

    monkeypatch.setattr(RemoteWriter, "upload_temp", slow)
    up = await upload(wclient, "Slow.smc", b"s" * 5000)
    r = await wclient.post("/api/transfers", json={"items": [{"upload_id": up["id"], "platform": "SFC"}]})
    tid = r.json()[0]["id"]
    await asyncio.wait_for(started.wait(), 5)
    assert not no_temp_left(ssh_server)  # le fichier temporaire existe pendant la copie
    c = await wclient.post(f"/api/transfers/{tid}/cancel")
    await wclient._transport.app.state.transfers.wait_idle()
    t = (await wclient.get(f"/api/transfers/{tid}")).json()
    assert c.status_code == 200 and t["status"] == "cancelled" and t["retryable"]
    assert no_temp_left(ssh_server) and not (roms(ssh_server) / "SFC/Slow.smc").exists()

    monkeypatch.setattr(RemoteWriter, "upload_temp", original)
    retried = (await wclient.post(f"/api/transfers/{tid}/retry")).json()
    await wclient._transport.app.state.transfers.wait_idle()
    assert (await wclient.get(f"/api/transfers/{retried[0]['id']}")).json()["status"] == "completed"


async def test_cancel_queued_item(wclient, monkeypatch):
    from app.device.remote_writer import RemoteWriter
    gate = asyncio.Event()
    original = RemoteWriter.upload_temp

    async def gated(self, *a):
        await gate.wait()
        return await original(self, *a)

    monkeypatch.setattr(RemoteWriter, "upload_temp", gated)
    a = await upload(wclient, "First.smc", b"1")
    b = await upload(wclient, "Second.smc", b"2")
    r = (await wclient.post("/api/transfers", json={"items": [
        {"upload_id": a["id"], "platform": "SFC"}, {"upload_id": b["id"], "platform": "SFC"}]})).json()
    await asyncio.sleep(0.2)
    assert (await wclient.post(f"/api/transfers/{r[1]['id']}/cancel")).json()["status"] == "cancelled"
    gate.set()
    await wclient._transport.app.state.transfers.wait_idle()
    assert (await wclient.get(f"/api/transfers/{r[0]['id']}")).json()["status"] == "completed"
    assert (await wclient.get(f"/api/transfers/{r[1]['id']}")).json()["status"] == "cancelled"


async def test_orphan_temp_files_swept(wclient, ssh_server):
    orphan = roms(ssh_server) / "SFC/.agm-0123456789abcdef0123456789abcdef.part"
    orphan.write_bytes(b"leftover")
    keep = roms(ssh_server) / "SFC/.agm-notmine.part"
    keep.write_bytes(b"not ours")
    up = await upload(wclient, "Fresh.smc", b"f")
    [t] = await run(wclient, [{"upload_id": up["id"], "platform": "SFC"}])
    assert t["status"] == "completed" and not orphan.exists() and keep.exists()


async def test_list_and_events(wclient, monkeypatch):
    up = await upload(wclient, "Listed.smc", b"l")
    await run(wclient, [{"upload_id": up["id"], "platform": "SFC"}])
    lst = (await wclient.get("/api/transfers")).json()
    assert lst[0]["filename"] == "Listed.smc" and lst[0]["status"] == "completed"
    # Le transport de test attend la fin de la réponse : on simule un navigateur qui se déconnecte après un message.
    from starlette.requests import Request
    calls = {"n": 0}

    async def disconnected(self):
        calls["n"] += 1
        return calls["n"] > 1

    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    r = await wclient.get("/api/transfers/events")
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.text.startswith("event: transfers") and '"active": []' in r.text


async def test_unknown_transfer_and_upload(wclient):
    assert (await wclient.get("/api/transfers/999")).json()["error"]["code"] == "transfer_not_found"
    r = await wclient.post("/api/transfers/plan", json={"items": [{"upload_id": "0" * 32}]})
    assert r.json()["error"]["code"] == "upload_not_found"


def test_migration_from_phase2_database(tmp_path):
    """Une base créée en phase 2 (révision 0001) est mise à niveau sans perte au démarrage."""
    from alembic import command
    from alembic.config import Config

    from app.db.session import MIGRATIONS, init_db, make_engine
    db = tmp_path / "old.sqlite3"
    eng = make_engine(db)
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0001")
    with sqlite3.connect(db) as c:
        c.execute("insert into device (id, name, host, port, username, roms_root, created_at) values (1,'x','h',22,'root','/mnt/mmc/Roms','2026-01-01')")
        c.execute("insert into scan_run (id, device_id, status, started_at, platforms_total, platforms_done, files_seen, added, modified, removed, restored, images_seen, images_matched, platform_errors) values (1,1,'completed','2026-01-01',0,0,0,5,0,0,0,0,0,'{}')")
    init_db(db)
    with sqlite3.connect(db) as c:
        assert c.execute("select added, trigger from scan_run").fetchone() == (5, "manual")
        assert c.execute("select count(*) from transfer").fetchone() == (0,)
        assert c.execute("select version_num from alembic_version").fetchone() == ("0013",)
