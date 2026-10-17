"""Game Manager contre les systèmes du labo (systems-lab/) : vrai SSH, vrais scripts du firmware, vrai RetroArch
(sans écran). Lancer : AGM_SYSTEMS_LAB=1 pytest tests/test_systems_lab.py (systems-lab/run.sh démarre les conteneurs)."""

import asyncio
import os
import shutil

import asyncssh
import httpx
import pytest

from app.config import DeviceSettings, SettingsStore
from app.credentials import MemoryStore
from app.main import create_app

LAB = os.environ.get("AGM_SYSTEMS_LAB") == "1" and shutil.which("docker")
pytestmark = pytest.mark.skipif(not LAB, reason="AGM_SYSTEMS_LAB=1 et les conteneurs de systems-lab requis")

SYSTEMS = {
    # profil attendu : (port SSH, mot de passe, dossier des ROMs, dossier de la ROM de test)
    "rocknix": (2231, "rocknix", "/storage/roms", "gb"),
}
ROM_TITLE = "Lab Test"


@pytest.fixture(params=list(SYSTEMS))
async def lab(request, tmp_path):
    profile = request.param
    port, password, roms_root, _ = SYSTEMS[profile]
    store = SettingsStore(tmp_path / "settings.json")
    store.save(DeviceSettings(host="127.0.0.1", port=port, username="root", roms_root=roms_root,
                              connect_timeout=10, system="auto"))
    creds = MemoryStore()
    creds.set_password("127.0.0.1", "root", password)
    os.environ["AGM_NO_TRACKER"] = "1"
    app = create_app(store, creds, tmp_path / "known_hosts", db_path=tmp_path / "catalog.sqlite3",
                     cache_dir=tmp_path / "cache", staging_dir=tmp_path / "staging")
    app.state.host_keys.trust("127.0.0.1", port, await asyncssh.get_server_host_key("127.0.0.1", port))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=60) as c:
        yield profile, c, app
    await app.state.pool.close()
    await app.state.transfers.close()


async def _sync(c):
    run_id = (await c.post("/api/catalog/sync")).json()["id"]
    for _ in range(300):
        run = (await c.get(f"/api/catalog/sync/{run_id}")).json()
        if run["status"] != "running":
            return run
        await asyncio.sleep(0.1)
    raise AssertionError("synchronisation trop longue")


async def _until(fn, seconds=20):
    for _ in range(seconds * 2):
        value = await fn()
        if value:
            return value
        await asyncio.sleep(0.5)
    return await fn()


async def test_full_cycle(lab):
    profile, c, app = lab
    _, _, roms_root, rom_dir = SYSTEMS[profile]

    info = (await c.get("/api/device/system")).json()
    assert info["profile"]["id"] == profile, info
    assert info["detected"]["suggested_roms_root"] == roms_root

    assert (await _sync(c))["status"] == "completed"
    platforms = {p["directory"]: p for p in (await c.get("/api/platforms")).json()}
    assert rom_dir in platforms and platforms[rom_dir]["code"] == "GB"
    assert not {"savestates", "bios"} & set(platforms)  # pas des consoles
    game = (await c.get("/api/games", params={"q": ROM_TITLE})).json()["items"][0]
    assert game["title"].startswith(ROM_TITLE)

    caps = info["capabilities"]
    if caps["launch"]:
        r = await c.post(f"/api/games/{game['id']}/launch")
        assert r.status_code == 202, r.text

        async def playing():
            now = (await c.get("/api/device/now-playing")).json()
            app.state.tracker.invalidate()
            return now if now["playing"] else None
        now = await _until(playing)
        assert now and now["game"] and now["game"]["id"] == game["id"], now
        await asyncio.sleep(6)  # on « joue » un peu : RetroArch écrit temps de jeu et sauvegarde auto en quittant
        assert (await c.post("/api/device/quit-game")).json()["result"] == "quit"
        app.state.tracker.invalidate()
        assert not (await c.get("/api/device/now-playing")).json()["playing"]

    saves = (await c.get("/api/saves")).json()["saves"]
    mine = [s for s in saves if s["game"] and s["game"]["id"] == game["id"]]
    assert any(s["kind"] == "sram" for s in mine), saves
    if caps["launch"]:
        assert any(s["kind"] == "state" and s["slot"] == "auto" for s in mine), mine

    if caps["retroarch_logs"] and caps["launch"]:
        stats = (await c.get("/api/play/stats")).json()
        assert stats["retroarch_available"]
        played = [g for g in stats["games"] if g["game"] and g["game"]["id"] == game["id"]]
        assert played and played[0]["seconds"] > 0, stats["games"]
        recent = (await c.get("/api/play/recent")).json()
        assert recent and recent[0]["game"] and recent[0]["game"]["id"] == game["id"], recent
