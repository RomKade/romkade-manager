import time

import pytest

from app import errors
from app.config import DeviceSettings
from app.credentials import MemoryStore
from app.device.pool import DevicePool
from app.device.ssh_client import DeviceClient, HostKeyStore


async def test_unreachable_console_fails_fast_afterwards(tmp_path):
    hk = HostKeyStore(tmp_path / "known_hosts")
    settings = DeviceSettings(host="127.0.0.1", port=1, connect_timeout=2)  # port fermé : refus immédiat
    hk.path.write_text("[127.0.0.1]:1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOq0R5Wv4nP6nW6Y0qgQ2cP9yY3cX0m3h0ZtG2Vb9a1b\n")
    creds = MemoryStore()
    creds.set_password("127.0.0.1", settings.username, "x")
    client = DeviceClient(settings, creds, hk)
    pool = DevicePool()
    with pytest.raises(errors.AppError) as first:
        await pool.run(client, "true")
    assert first.value.code == "device_ssh_refused"  # port fermé
    t = time.perf_counter()
    with pytest.raises(errors.AppError) as second:
        await pool.run(client, "true")
    assert second.value is first.value and time.perf_counter() - t < 0.05  # pas de nouvelle tentative de connexion
    await pool.close()
