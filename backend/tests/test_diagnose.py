import errno
import sys

import pytest

from app.device import diagnose


@pytest.mark.parametrize("ping_ok, expected", [(True, "local_network_blocked"), (False, "device_unreachable")])
async def test_no_route_to_host(monkeypatch, ping_ok, expected):
    """« No route to host » : macOS qui bloque le réseau local si la console répond au ping, sinon console absente."""
    async def fake_ping(host, timeout=2):
        return ping_ok
    monkeypatch.setattr(diagnose, "ping", fake_ping)
    monkeypatch.setattr(sys, "platform", "darwin")
    err = await diagnose.network_error("192.168.86.242", 22, OSError(errno.EHOSTUNREACH, "No route to host"))
    assert err.code == expected


async def test_connection_refused():
    err = await diagnose.network_error("192.168.86.242", 22, OSError(errno.ECONNREFUSED, "Connection refused"))
    assert err.code == "device_ssh_refused"


async def test_steps_after_failure_are_skipped(tmp_path):
    from app.config import DeviceSettings
    from app.device.ssh_client import HostKeyStore

    class NoCreds:
        def get_password(self, host, user):
            return None

    s = DeviceSettings(host="127.0.0.1", port=1, connect_timeout=1)  # port fermé
    r = await diagnose.diagnose(s, NoCreds(), HostKeyStore(tmp_path / "known_hosts"))
    assert not r["ok"] and r["steps"][0]["status"] == "failed" and r["steps"][0]["code"]
    assert [x["status"] for x in r["steps"][1:]] == ["skipped"] * 5
