import pytest

from app.config import DeviceSettings
from app.device.paths import is_within, platform_dir_name_ok, safe_join
from app.errors import AppError

ROOT = "/mnt/mmc/Roms"


def test_safe_join_ok():
    assert safe_join(ROOT, "PS", "Game.chd") == "/mnt/mmc/Roms/PS/Game.chd"


@pytest.mark.parametrize("bad", ["..", "../etc", "PS/../../etc", "/etc/passwd", "", "a\x00b", "PS/./x"])
def test_safe_join_rejects(bad):
    with pytest.raises(AppError) as exc:
        safe_join(ROOT, bad)
    assert exc.value.code == "path_forbidden"


def test_is_within_prefix_trap():
    assert is_within(ROOT, "/mnt/mmc/Roms/PS")
    assert not is_within(ROOT, "/mnt/mmc/RomsEvil/PS")


@pytest.mark.parametrize("name,ok", [("PS", True), ("..", False), ("a/b", False), ("", False)])
def test_platform_dir_name(name, ok):
    assert platform_dir_name_ok(name) is ok


@pytest.mark.parametrize("root", ["/", "/mnt/../etc", "relative", "/mnt/mmc;rm -rf /", "/mnt/$(id)"])
def test_settings_reject_bad_root(root):
    with pytest.raises(ValueError):
        DeviceSettings(roms_root=root)


def test_settings_strip_trailing_slash():
    assert DeviceSettings(roms_root="/mnt/mmc/Roms/").roms_root == "/mnt/mmc/Roms"
