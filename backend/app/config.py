"""Réglages non sensibles, stockés hors du dépôt Git.

Emplacement par défaut : ~/Library/Application Support/AnbernicGameManager/
Surcharge possible avec la variable d'environnement ANBERNIC_DATA_DIR.
"""

import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SAFE_REMOTE_PATH = re.compile(r"^/[A-Za-z0-9._/-]*$")


def data_dir() -> Path:
    env = os.environ.get("ANBERNIC_DATA_DIR")
    base = Path(env) if env else Path.home() / "Library" / "Application Support" / "AnbernicGameManager"
    base.mkdir(parents=True, exist_ok=True)
    return base


class DeviceSettings(BaseModel):
    host: str = Field("192.168.86.242", min_length=1, max_length=253)
    port: int = Field(22, ge=1, le=65535)
    username: str = Field("root", min_length=1, max_length=64)
    auth_method: Literal["password", "key"] = "password"
    key_path: str | None = None
    roms_root: str = "/mnt/mmc/Roms"
    connect_timeout: float = Field(8.0, gt=0, le=60)
    system: str = Field("auto", description="Profil du firmware (app/device/systems.py) ou « auto » (détecté)")

    @field_validator("system")
    @classmethod
    def _system(cls, v: str) -> str:
        from app.device.systems import PROFILES
        if v != "auto" and v not in PROFILES:
            raise ValueError("système inconnu")
        return v

    @field_validator("host")
    @classmethod
    def _host(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9.\-:\[\]]+", v):
            raise ValueError("hôte invalide")
        return v

    @field_validator("username")
    @classmethod
    def _user(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", v):
            raise ValueError("utilisateur invalide")
        return v

    @field_validator("roms_root")
    @classmethod
    def _root(cls, v: str) -> str:
        v = v.rstrip("/") or "/"
        if not SAFE_REMOTE_PATH.fullmatch(v) or ".." in v.split("/") or v == "/":
            raise ValueError("racine des ROMs invalide (chemin absolu simple, sans '..', différent de '/')")
        return v


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "settings.json"

    def load(self) -> DeviceSettings:
        if self.path.exists():
            return DeviceSettings.model_validate_json(self.path.read_text())
        return DeviceSettings()

    def save(self, settings: DeviceSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.model_dump(), indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
