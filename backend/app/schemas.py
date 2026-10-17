from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from app.config import DeviceSettings


class SettingsOut(DeviceSettings):
    has_password: bool
    host_key_trusted: bool


class PasswordIn(BaseModel):
    password: SecretStr = Field(min_length=1, max_length=256)


class HostKeyOut(BaseModel):
    host: str
    port: int
    algorithm: str
    fingerprint: str
    trusted: bool


class TrustHostKeyIn(BaseModel):
    fingerprint: str = Field(description="Empreinte SHA256 affichée par GET /api/device/host-key, recopiée pour confirmation")


class StorageOut(BaseModel):
    path: str
    total_bytes: int
    free_bytes: int
    used_bytes: int
    used_percent: float
    method: Literal["sftp_statvfs", "df"]


class DiagnoseStepOut(BaseModel):
    id: str  # network | ssh | host_key | auth | command | roms
    status: str  # ok | failed | skipped
    ms: float | None = None
    detail: str | None = None
    code: str | None = None
    message: str | None = None


class DiagnoseOut(BaseModel):
    ok: bool
    host: str
    port: int
    steps: list[DiagnoseStepOut]


class ConnectionTestOut(BaseModel):
    connected: bool
    host: str
    port: int
    username: str
    sftp: bool
    roms_root: str
    roms_root_exists: bool
    platform_dir_count: int | None = None
    storage: StorageOut | None = None
    latency_ms: float


class PlatformOut(BaseModel):
    directory: str
    label: str | None
    label_status: Literal["confirmed", "assumed", "unknown", "unmapped"]
    kind: str
    known: bool
    is_symlink: bool = False


class RemoteFileOut(BaseModel):
    id: str = Field(description="Identifiant du scan en direct (hash du chemin). L'identifiant du catalogue est celui de /api/games")
    platform: str
    filename: str
    relative_path: str
    remote_path: str
    extension: str | None
    size: int | None
    modified_at: datetime | None
    role: Literal["candidate", "component", "auxiliary", "program"]
    is_symlink: bool


class RemoteImageOut(BaseModel):
    relative_path: str
    filename: str
    size: int | None
    modified_at: datetime | None


class PlatformInventoryOut(PlatformOut):
    file_count: int
    candidate_count: int
    total_bytes: int
    image_dir_present: bool
    image_count: int
    skipped: list[str] = Field(default_factory=list, description="Entrées ignorées (cachées, liens, profondeur)")
    files: list[RemoteFileOut] | None = None
    images: list[RemoteImageOut] | None = None


class InventoryOut(BaseModel):
    roms_root: str
    scanned_at: datetime
    duration_ms: float
    platform_count: int
    file_count: int
    candidate_count: int
    total_bytes: int
    platforms: list[PlatformInventoryOut]


class Page(BaseModel):
    total: int
    offset: int
    limit: int


class FilesPageOut(BaseModel):
    platform: PlatformInventoryOut
    page: Page
    files: list[RemoteFileOut]
