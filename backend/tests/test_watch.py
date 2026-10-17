import os
import time

import httpx

from tests.test_catalog import games, sync


def touch_later(path, seconds=10):
    """Date de dossier dans le futur : la date SFTP est à la seconde, la copie du test tient dans la même."""
    t = time.time() + seconds
    os.utime(path, (t, t))


async def titles(c, **params):
    return [g["title"] for g in (await games(c, **params))["items"]]


async def test_watch_finds_games_added_outside_the_app(app_factory, ssh_server):
    app = app_factory()
    watcher = app.state.watcher
    roms = ssh_server["chroot"] / "mnt" / "mmc" / "Roms"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert await watcher.check_once() == "offline"   # catalogue jamais synchronisé : rien d'automatique
        await sync(c)
        assert await watcher.check_once() == "unchanged"
        assert await watcher.check_once() == "unchanged"

        # Jeu copié sur la carte par un autre moyen : seul son dossier est relu.
        (roms / "SFC" / "Zelda (USA).smc").write_bytes(b"\0" * 64)
        touch_later(roms / "SFC")
        assert await watcher.check_once() == "refresh"
        assert "Zelda" in await titles(c, q="zelda")
        runs = (await c.get("/api/catalog/syncs")).json()
        assert runs[0]["trigger"] == "watch"
        assert await watcher.check_once() == "unchanged"

        # Jeu retiré.
        (roms / "SFC" / "Zelda (USA).smc").unlink()
        touch_later(roms / "SFC", 20)
        assert await watcher.check_once() == "refresh"
        assert await titles(c, q="zelda") == []

        # Nouveau dossier de console : synchronisation complète.
        (roms / "GB").mkdir()
        (roms / "GB" / "Tetris (World).gb").write_bytes(b"\0" * 32)
        assert await watcher.check_once() == "full"
        await app.state.sync.task
        assert await titles(c, q="tetris") == ["Tetris"]
    assert ssh_server["sftp"].write_attempts == []  # la veille ne fait que lire


async def test_watch_catches_up_after_restart_and_waits_when_busy(app_factory, ssh_server):
    roms = ssh_server["chroot"] / "mnt" / "mmc" / "Roms"
    first = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=first), base_url="http://test") as c:
        await sync(c)
    # Pendant que l'application est fermée, un jeu arrive sur la carte.
    (roms / "MD" / "Streets of Rage (Europe).md").write_bytes(b"\0" * 64)
    touch_later(roms / "MD")
    app = app_factory()
    async with app.state.sync.lock:
        assert await app.state.watcher.check_once() == "busy"
    assert await app.state.watcher.check_once() == "refresh"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert await titles(c, q="streets") == ["Streets of Rage"]
