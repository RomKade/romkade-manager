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
