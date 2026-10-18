"""Une seule version de ROMKADE Manager : pyproject.toml, API et interface (package.json, affichée par l'interface)."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_versions_match():
    from app.main import create_app

    backend = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text())["project"]["version"]
    frontend = json.loads((ROOT / "frontend" / "package.json").read_text())["version"]
    assert backend == frontend == create_app().version
