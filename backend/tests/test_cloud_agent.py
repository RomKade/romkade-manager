"""Liaison de la console à ROMKADE Cloud depuis le Manager (services/cloud_agent.py)."""

import asyncio
import json

import httpx
import pytest

from app import errors
from app.services import cloud_agent


def test_bundle_contains_agent_screen_app_and_manager_modules():
    files = cloud_agent.bundle("/mnt/mmc/Roms")
    names = set(files)
    assert "/mnt/mmc/romkade/romkade_agent.py" in names and "/mnt/mmc/romkade/screen.py" in names
    assert "/mnt/mmc/romkade/vendor/app/device/launcher.py" in names          # modules du Manager, sur place
    assert "/mnt/mmc/romkade/vendor/asyncssh.py" in names                     # remplaçant de SSH
    assert "/mnt/mmc/Roms/APPS/ROMKADE.sh" in names and "/mnt/mmc/Roms/APPS/Imgs/ROMKADE.png" in names
    assert not any(n.endswith("agent.json") for n in names)                   # le secret est écrit à part
    assert files["/mnt/mmc/romkade/start.sh"][1] == 0o755


def test_register_sends_session_token_and_reuses_installed_agent():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"console": {"id": "c1"}, "secret": "s", "server": "https://mcp.romkade.com", "reused": True})

    reply = asyncio.run(cloud_agent.register("jeton", "Ma RG", {"model": "RG35xxPRO"}, "ancien",
                                             transport=httpx.MockTransport(handler)))
    assert reply["reused"] and seen["auth"] == "Bearer jeton" and seen["body"]["secret"] == "ancien"


def test_register_expired_session():
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(errors.AppError) as exc:
        asyncio.run(cloud_agent.register("vieux", None, {}, None, transport=transport))
    assert exc.value.code == "cloud_unauthorized"


def test_register_one_console_per_account():
    transport = httpx.MockTransport(lambda r: httpx.Response(409, json={"error": "console_limit", "max": 1}))
    with pytest.raises(errors.AppError) as exc:
        asyncio.run(cloud_agent.register("jeton", None, {}, None, transport=transport))
    assert exc.value.code == "cloud_console_limit" and exc.value.status == 409


def test_bundle_contains_the_saves_reader():
    files = cloud_agent.bundle("/mnt/mmc/Roms")
    assert "/mnt/mmc/romkade/vendor/app/services/saves.py" in files             # outil game_details du cloud
    assert "/mnt/mmc/romkade/vendor/app/device/remote_fs.py" in files           # remplaçant de la façade SFTP


async def test_favorites_written_next_to_the_agent(app_factory, ssh_server):
    """Favori ajouté dans le Manager : posé à côté de l'agent ROMKADE (qui l'envoie au cloud), jamais sans agent."""
    from tests.test_catalog import sync

    ssh_server["sftp"].allow_writes = True
    agent = ssh_server["chroot"] / "mnt" / "mmc" / "romkade"
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        items = (await c.get("/api/games", params={"role": "candidate"})).json()["items"]
        mario = next(g for g in items if g["title"] == "Super Mario World")
        sonic = next(g for g in items if g["title"] == "Sonic The Hedgehog")
        assert (await c.put(f"/api/games/{mario['id']}/favorite")).status_code == 204
        await asyncio.gather(*cloud_agent._pushes)
        assert not (agent / "favorites.json").exists()                             # pas d'agent : rien d'écrit

        agent.mkdir()
        (agent / "agent.json").write_text('{"server": "https://mcp.romkade.com", "secret": "s"}')
        assert (await c.put(f"/api/games/{sonic['id']}/favorite")).status_code == 204
        await asyncio.gather(*cloud_agent._pushes)
        assert json.loads((agent / "favorites.json").read_text())["favorites"] == [
            ["MD", "Sonic The Hedgehog (Europe).md"], ["SFC", "Super Mario World (USA).smc"]]
        assert (await c.delete(f"/api/games/{sonic['id']}/favorite")).status_code == 204
        await asyncio.gather(*cloud_agent._pushes)
        assert json.loads((agent / "favorites.json").read_text())["favorites"] == [["SFC", "Super Mario World (USA).smc"]]


def test_bundle_covers_every_app_import():
    """Chaque « from app.x import » des modules envoyés à la console (y compris dans une fonction) a son fichier."""
    import re

    files = cloud_agent.bundle("/mnt/mmc/Roms")
    vendor = {p.split("/vendor/", 1)[1] for p in files if "/vendor/" in p}
    for path in vendor:
        if not path.endswith(".py"):
            continue
        source = files[f"/mnt/mmc/romkade/vendor/{path}"][0].decode()
        for module in re.findall(r"^\s*from (app(?:\.\w+)+) import", source, re.M):
            target = module.replace(".", "/")
            assert f"{target}.py" in vendor or f"{target}/__init__.py" in vendor, f"{path} importe {module}, absent"


class _FakeFile:
    def __init__(self, store, path):
        self.store, self.path = store, path

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def write(self, data):
        self.store[self.path] = data


class _FakeSftp:
    def __init__(self):
        self.files = {}

    async def makedirs(self, path, exist_ok=False):
        pass

    def open(self, path, mode):
        return _FakeFile(self.files, path)

    async def chmod(self, path, mode):
        pass


def test_install_writes_version_and_shows_splash_unless_a_game_runs():
    sftp, commands = _FakeSftp(), []

    async def run(_client, command, timeout=0):
        commands.append(command)
        return 0, "started" if "romkade-agent.pid" in command else "shown"

    shown = asyncio.run(cloud_agent.install(run, None, sftp, "/mnt/mmc/Roms", "https://cloud", "s", splash="updated"))
    assert shown and sftp.files["/mnt/mmc/romkade/VERSION"].decode().strip() == cloud_agent.manager_version()
    assert "for p in retroarch" in commands[-1] and "pidof $p" in commands[-1] and "splash.sh updated 6" in commands[-1]
    # Sans écran demandé (ou pendant un jeu : la commande ne répond pas « shown »), rien ne s'affiche.
    assert not asyncio.run(cloud_agent.install(run, None, sftp, "/mnt/mmc/Roms", "https://cloud", "s"))
