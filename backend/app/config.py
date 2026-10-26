"""Réglages non sensibles, stockés hors du dépôt Git.

Emplacement par défaut, selon le système : ~/Library/Application Support/AnbernicGameManager/ (macOS),
%APPDATA%\AnbernicGameManager (Windows), $XDG_DATA_HOME/AnbernicGameManager ou ~/.local/share/… (Linux).
Surcharge : variable d'environnement ROMKADE_DATA_DIR (ou ANBERNIC_DATA_DIR, l'ancien nom) ; l'image Docker
utilise /data, monté sur un volume.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SAFE_REMOTE_PATH = re.compile(r"^/[A-Za-z0-9._/-]*$")


APP_DIR = "AnbernicGameManager"  # nom historique du dossier : ne pas le changer sans migration


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_DIR
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_DIR


def data_dir() -> Path:
    env = os.environ.get("ROMKADE_DATA_DIR") or os.environ.get("ANBERNIC_DATA_DIR")
    base = Path(env) if env else default_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base


class DeviceSettings(BaseModel):
    # Vide tant que l'utilisateur n'a pas indiqué sa console (Tableau de bord ou Paramètres > Connexion).
    host: str = Field("", max_length=253)
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
        v = v.strip()
        if v and not re.fullmatch(r"[A-Za-z0-9.\-:\[\]]+", v):
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
