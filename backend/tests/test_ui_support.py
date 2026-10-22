"""Fonctions backend ajoutées pour l'interface : miniatures, connexion partagée, facettes, service du frontend."""

import asyncio
import io

import httpx
from PIL import Image

from app.services import cloud_agent

from conftest import PasswordServer
from test_catalog import games, sync


def _png(path, size=(800, 600), color=(120, 40, 140)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    path.write_bytes(buf.getvalue())


async def test_thumbnail_is_small_webp(client, ssh_server):
    _png(ssh_server["chroot"] / "mnt/mmc/Roms/PS/Imgs/Ridge Racer (Europe).png")
    await sync(client)
    rr = (await games(client, q="ridge"))["items"][0]
    thumb = await client.get(rr["image_url"], params={"size": "thumb"})
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    w, h = Image.open(io.BytesIO(thumb.content)).size
    assert max(w, h) == 360
    full = await client.get(rr["image_url"])
    assert full.headers["content-type"] == "image/png" and Image.open(io.BytesIO(full.content)).size == (800, 600)


async def test_unreadable_image_falls_back_to_original(client):
    await sync(client)
    rr = (await games(client, q="ridge"))["items"][0]  # image de 300 octets nuls : pas un PNG valide
    r = await client.get(rr["image_url"], params={"size": "thumb"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


async def test_grid_burst_uses_one_ssh_connection(client, ssh_server):
    roms = ssh_server["chroot"] / "mnt/mmc/Roms/SFC"
    for i in range(30):
        (roms / f"Game {i}.smc").write_bytes(b"\0")
        _png(roms / "Imgs" / f"Game {i}.png", size=(64, 64))
    await sync(client)
    items = (await games(client, platform="SFC", has_image=True, limit=100))["items"]
    assert len(items) == 30
    await asyncio.gather(*cloud_agent._pushes)  # favoris vers l'agent après la synchronisation : connexion du pool
    before = PasswordServer.connections
    results = await asyncio.gather(*(client.get(g["image_url"], params={"size": "thumb"}) for g in items))
    assert all(r.status_code == 200 for r in results)
    assert PasswordServer.connections - before <= 1  # la connexion partagée, jamais une par image
    assert ssh_server["sftp"].write_attempts == []


async def test_thumbs_db_is_not_an_image(client):
    run = await sync(client)
    assert run["images_seen"] == 3  # Thumbs.db ignoré


async def test_facets(client):
    await sync(client)
    f = (await client.get("/api/catalog/facets")).json()
    assert {e["value"] for e in f["extensions"]} == {"chd", "cue", "smc", "bin", "md"}
    assert {r["value"]: r["count"] for r in f["regions"]} == {"Europe": 2, "USA": 1}
    ps = (await client.get("/api/catalog/facets", params={"platform": "PS"})).json()
    assert {e["value"] for e in ps["extensions"]} == {"chd", "cue"}


async def test_frontend_served_with_spa_fallback(tmp_path, app_factory):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    from app.main import create_app
    base = app_factory()
    app = create_app(base.state.settings_store, base.state.credentials, tmp_path / "kh",
                     db_path=tmp_path / "ui.sqlite3", cache_dir=tmp_path / "c", frontend_dist=dist)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert "root" in (await c.get("/bibliotheque")).text
        assert (await c.get("/assets/app.js")).status_code == 200
        assert (await c.get("/favicon.svg")).text == "<svg/>"
        assert (await c.get("/api/health")).json()["status"] == "ok"
        assert (await c.get("/api/nope")).status_code == 404
        assert "root" in (await c.get("/..%2F..%2Fetc%2Fpasswd")).text  # pas de sortie du dossier dist
