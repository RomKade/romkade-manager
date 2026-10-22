from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas import Page

Role = Literal["candidate", "component", "auxiliary", "program"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CatalogPlatformOut(ORM):
    id: int
    directory: str
    code: str
    label: str | None
    label_status: str
    kind: str
    present: bool
    image_dir_present: bool
    last_scanned_at: datetime | None
    game_count: int
    file_count: int
    total_bytes: int
    image_count: int
    images_matched: int


class PlatformRef(ORM):
    id: int
    directory: str
    code: str
    label: str | None


class GameOut(ORM):
    id: int
    platform: PlatformRef
    title: str
    full_title: str | None
    normalized_title: str
    filename: str
    relative_path: str
    extension: str | None
    region: str | None
    size: int | None
    modified_at: datetime | None
    role: Role
    has_image: bool
    image_url: str | None
    boxart_url: str | None
    metadata_status: Literal["not_fetched", "matched", "unmatched", "verified"]
    genre: str | None
    genre_label: str | None
    genre_detail: str | None
    subgenre: str | None = None  # « sport.golf » (app.services.subgenres)
    subgenre_label: str | None = None
    release_year: int | None = None
    developer: str | None = None
    publisher: str | None = None
    players: int | None = None  # nombre maximum de joueurs (libretro-database), inconnu : None
    players_link: bool = False  # console portable : à plusieurs avec un câble link (une console chacun)
    first_seen_at: datetime
    last_seen_at: datetime
    present: bool
    youtube_url: str | None = None  # recherche YouTube de la bande-annonce (même requête que GET /games/{id}/video)


class ChangeOut(ORM):
    scan_run_id: int
    change: Literal["added", "modified", "removed", "restored"]
    old_size: int | None
    new_size: int | None
    old_mtime: datetime | None
    new_mtime: datetime | None
    run_started_at: datetime


class GameDetailOut(GameOut):
    release_date: str | None = None  # « AAAA-MM-JJ » ou « AAAA-MM »
    franchise: str | None = None
    description: str | None = None  # résumé, en anglais (OpenVGDB)
    descriptions: dict[str, dict] = {}  # {fr|en|es: {text, origin}} : par Claude (services/descriptions.py)
    favorite: bool = False
    broken: bool = False  # signalé comme ne fonctionnant pas sur cette console
    info_url: str | None = None  # fiche de référence (GameFAQs)
    remote_path: str
    image_relpath: str | None
    possible_duplicates: list[GameOut]
    history: list[ChangeOut]


class GamesPageOut(BaseModel):
    page: Page
    items: list[GameOut]


class ScanRunOut(ORM):
    id: int
    status: Literal["running", "completed", "partial", "failed", "interrupted"]
    trigger: Literal["manual", "transfer", "watch"] = "manual"
    started_at: datetime
    finished_at: datetime | None
    platforms_total: int
    platforms_done: int
    files_seen: int
    added: int
    modified: int
    removed: int
    restored: int
    images_seen: int
    images_matched: int
    error: str | None
    platform_errors: dict[str, str]


class CatalogStatusOut(BaseModel):
    synced: bool
    sync_running: bool
    last_run: ScanRunOut | None
    last_successful_sync_at: datetime | None
    platform_count: int
    game_count: int
    file_count: int
    total_bytes: int
    storage_total_bytes: int | None
    storage_free_bytes: int | None
    storage_measured_at: datetime | None


class ChangeItemOut(ChangeOut):
    game: GameOut


class ChangesPageOut(BaseModel):
    page: Page
    items: list[ChangeItemOut]


class DuplicateGroupOut(BaseModel):
    platform: PlatformRef
    normalized_title: str
    confidence: Literal["likely", "possible"]
    reason: str
    items: list[GameOut]


class UnmatchedImagesOut(BaseModel):
    platform: PlatformRef
    total: int
    sample: list[str]


class FacetValue(BaseModel):
    value: str
    count: int
    label: str | None = None


class FacetsOut(BaseModel):
    extensions: list[FacetValue]
    regions: list[FacetValue]
    genres: list[FacetValue]
    subgenres: list[FacetValue] = []  # « sport.golf » : préfixe = genre


class VideoOut(BaseModel):
    id: str
    title: str
    channel: str


class VideoLookupOut(BaseModel):
    status: Literal["found", "not_found", "no_key"]
    query: str
    search_url: str
    videos: list[VideoOut]
    fetched_at: datetime | None = None


class YouTubeSettingsOut(BaseModel):
    configured: bool


class YouTubeKeyIn(BaseModel):
    api_key: str


class SaveOut(BaseModel):
    path: str
    rel: str
    source: Literal["retroarch", "stock", "nds", "psp", "rom-folder"]
    kind: Literal["sram", "state"]
    slot: str | None
    platform: str | None
    name: str
    size: int | None
    modified_at: datetime | None
    game: GameOut | None


class SavesOut(BaseModel):
    saves: list[SaveOut]
    scanned_at: datetime


class BackupFileOut(BaseModel):
    rel: str
    size: int
    kind: str | None = None
    slot: str | None = None
    platform: str | None = None
    game_title: str | None = None
    modified_at: str | None = None


class BackupOut(BaseModel):
    id: str
    created_at: str
    auto: bool
    bytes: int
    files: list[BackupFileOut]


class HotkeyOut(BaseModel):
    action: Literal["save_state", "load_state", "slot_next", "slot_prev", "quit", "menu"]
    combo: list[str]


class SearchOut(BaseModel):
    items: list[GameOut]
    total: int
    engine: Literal["typesense", "sqlite"]
