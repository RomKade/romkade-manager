"""Modèle SQLite du catalogue.

Trois notions séparées : fichier observé sur la carte (remote_file), image observée (platform_image),
et plus tard jeu identifié par les métadonnées (phase 5). Rien n'est jamais supprimé physiquement
à la synchronisation : un fichier disparu reçoit `deleted_at`.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UTCDateTime(TypeDecorator):
    """Stocke en UTC, relit en datetime conscient du fuseau (SQLite perd le fuseau)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None else None


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "device"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="RG35XX Pro")
    host: Mapped[str] = mapped_column(String(253))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(64))
    roms_root: Mapped[str] = mapped_column(String(255))
    total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    free_bytes: Mapped[int | None] = mapped_column(BigInteger)
    storage_measured_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Platform(Base):
    __tablename__ = "platform"
    __table_args__ = (UniqueConstraint("device_id", "directory"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("device.id", ondelete="CASCADE"))
    directory: Mapped[str] = mapped_column(String(100))
    label: Mapped[str | None] = mapped_column(String(100))
    label_status: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    is_symlink: Mapped[bool] = mapped_column(Boolean, default=False)
    image_dir_present: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scanned_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    files: Mapped[list["RemoteFile"]] = relationship(back_populates="platform")

    @property
    def code(self) -> str:
        """Code de console commun à tous les firmwares (« snes » -> « SFC »), voir app.platforms.canonical."""
        from app.platforms import canonical
        return canonical(self.directory)


class RemoteFile(Base):
    __tablename__ = "remote_file"
    __table_args__ = (
        UniqueConstraint("platform_id", "relative_path"),
        Index("ix_remote_file_listing", "role", "deleted_at", "platform_id"),
        Index("ix_remote_file_title", "platform_id", "normalized_title"),
        Index("ix_remote_file_genre", "platform_id", "genre"),
        Index("ix_remote_file_release_year", "release_year"),
        Index("ix_remote_file_subgenre", "platform_id", "subgenre"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(String(1024))
    filename: Mapped[str] = mapped_column(String(512))
    extension: Mapped[str | None] = mapped_column(String(16), index=True)
    size: Mapped[int | None] = mapped_column(BigInteger)
    mtime: Mapped[datetime | None] = mapped_column(UTCDateTime)
    role: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(512))
    normalized_title: Mapped[str] = mapped_column(String(512))
    search_key: Mapped[str] = mapped_column(String(1024))
    region: Mapped[str | None] = mapped_column(String(100))
    image_relpath: Mapped[str | None] = mapped_column(String(1024))
    metadata_status: Mapped[str] = mapped_column(String(20), default="not_fetched")
    # Genre unifié (clé de app.services.genres.GENRES) et catégorie d'origine, rapprochés par nom de fichier.
    genre: Mapped[str | None] = mapped_column(String(32))
    genre_detail: Mapped[str | None] = mapped_column(String(100))
    subgenre: Mapped[str | None] = mapped_column(String(48))  # « sport.golf » (app.services.subgenres)
    # Arcade : titre complet du jeu (le fichier ne porte que le nom court MAME, « sf2.zip »).
    full_title: Mapped[str | None] = mapped_column(String(512))
    # Informations du jeu (app.services.gameinfo, rapprochées par nom de fichier) : sortie, auteurs, résumé.
    release_year: Mapped[int | None] = mapped_column(Integer)
    release_date: Mapped[str | None] = mapped_column(String(10))  # « AAAA-MM-JJ » ou « AAAA-MM »
    developer: Mapped[str | None] = mapped_column(String(200))
    publisher: Mapped[str | None] = mapped_column(String(200))
    franchise: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)  # en anglais (OpenVGDB)
    info_url: Mapped[str | None] = mapped_column(String(500))  # fiche de référence (GameFAQs)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_scan_run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_run.id", ondelete="SET NULL"))

    platform: Mapped[Platform] = relationship(back_populates="files")


class PlatformImage(Base):
    __tablename__ = "platform_image"
    __table_args__ = (UniqueConstraint("platform_id", "relative_path"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(String(1024))
    filename: Mapped[str] = mapped_column(String(512))
    stem_lower: Mapped[str] = mapped_column(String(512), index=True)
    size: Mapped[int | None] = mapped_column(BigInteger)
    mtime: Mapped[datetime | None] = mapped_column(UTCDateTime)
    matched: Mapped[bool] = mapped_column(Boolean, default=False)


class ScanRun(Base):
    __tablename__ = "scan_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("device.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|completed|partial|failed|interrupted
    trigger: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")  # manual|transfer|watch
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    platforms_total: Mapped[int] = mapped_column(Integer, default=0)
    platforms_done: Mapped[int] = mapped_column(Integer, default=0)
    files_seen: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    modified: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    restored: Mapped[int] = mapped_column(Integer, default=0)
    images_seen: Mapped[int] = mapped_column(Integer, default=0)
    images_matched: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    platform_errors: Mapped[dict] = mapped_column(JSON, default=dict)


class ScanChange(Base):
    __tablename__ = "scan_change"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_run.id", ondelete="CASCADE"), index=True)
    remote_file_id: Mapped[int] = mapped_column(ForeignKey("remote_file.id", ondelete="CASCADE"), index=True)
    change: Mapped[str] = mapped_column(String(16))  # added|modified|removed|restored
    old_size: Mapped[int | None] = mapped_column(BigInteger)
    new_size: Mapped[int | None] = mapped_column(BigInteger)
    old_mtime: Mapped[datetime | None] = mapped_column(UTCDateTime)
    new_mtime: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Transfer(Base):
    """Copie d'un fichier du Mac vers la console. Le fichier source est en zone d'attente locale (staging)."""

    __tablename__ = "transfer"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    upload_id: Mapped[str] = mapped_column(String(36))
    filename: Mapped[str] = mapped_column(String(512))            # nom demandé
    final_filename: Mapped[str | None] = mapped_column(String(512))  # nom réellement écrit (renommage éventuel)
    platform_dir: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    on_conflict: Mapped[str] = mapped_column(String(16))          # skip|overwrite|rename
    # queued|running|verifying|completed|skipped|failed|cancelled|interrupted
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    bytes_done: Mapped[int] = mapped_column(BigInteger, default=0)
    verify_method: Mapped[str | None] = mapped_column(String(16))  # sha256|size
    remote_path: Mapped[str | None] = mapped_column(String(1024))
    backup_path: Mapped[str | None] = mapped_column(String(1024))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class GameVideo(Base):
    """Vidéos YouTube trouvées pour un jeu, mises en cache : une recherche coûte du quota YouTube.

    Clé : plateforme + titre normalisé, si bien que toutes les éditions d'un même jeu partagent la recherche.
    """

    __tablename__ = "game_video"
    __table_args__ = (UniqueConstraint("platform_id", "normalized_title"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="CASCADE"))
    normalized_title: Mapped[str] = mapped_column(String(512))
    query: Mapped[str] = mapped_column(String(300))
    videos: Mapped[list] = mapped_column(JSON, default=list)  # meilleure d'abord : {id, title, channel}
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class GameText(Base):
    """Description d'un jeu dans une langue (fr, en, es), rédigée ou traduite par Claude (services/descriptions.py).

    Clé : plateforme + titre normalisé, comme GameVideo : toutes les éditions d'un même jeu la partagent.
    `origin` : « translated » (traduction du résumé OpenVGDB), « written » (jeu connu du modèle), « cautious »
    (jeu mal connu : seulement ce qui est sûr), « source » (résumé d'origine, en anglais).
    """

    __tablename__ = "game_text"
    __table_args__ = (UniqueConstraint("platform_id", "normalized_title", "lang"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="CASCADE"))
    normalized_title: Mapped[str] = mapped_column(String(512))
    lang: Mapped[str] = mapped_column(String(2))
    text: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class GameControls(Base):
    """Commandes d'un jeu sur la console (quelle touche fait quoi), rédigées par Claude à la demande
    (services/controls.py) ou corrigées à la main.

    Clé : plateforme + titre normalisé, comme GameText. `controls` : liste ordonnée {button, fr, en, es} ;
    `notes` : {fr, en, es} ou None. `origin` : « sourced » (d'après les passages Wikipédia / StrategyWiki du jeu,
    services/knowledge.py), « written » (jeu connu du modèle), « cautious » (jeu mal connu : commandes génériques de
    la console), « edited » (corrigé à la main). `sources` : pages utilisées [{source, page, url}] ou None.
    """

    __tablename__ = "game_controls"
    __table_args__ = (UniqueConstraint("platform_id", "normalized_title"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="CASCADE"))
    normalized_title: Mapped[str] = mapped_column(String(512))
    controls: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[dict | None] = mapped_column(JSON)
    origin: Mapped[str] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(40))
    sources: Mapped[list | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Favorite(Base):
    """Jeu mis en favori depuis sa fiche (l'édition choisie, pas toutes celles du même titre), pour une console.

    `console` : empreinte SHA-256 de la clé SSH de la console (stable, contrairement à son adresse IP), à défaut
    « hôte:port ». Changer de console (celle d'un ami, un autre firmware) n'affiche que ses propres favoris.
    NULL : favori d'avant cette distinction, montré sur toute console où le jeu est présent."""

    __tablename__ = "favorite"
    __table_args__ = (UniqueConstraint("console", "file_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("remote_file.id", ondelete="CASCADE"), index=True)
    console: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class GameKnowledge(Base):
    """Recherche de connaissances pour un jeu (services/knowledge.py) : trouvé sur Wikidata ou non, pages retenues.

    Clé : plateforme + titre normalisé, comme GameText. `status` : found | not_found | error. `sources` :
    {"wikipedia": {"en": "Titre", …}, "strategywiki": "Id"}.
    """

    __tablename__ = "game_knowledge"
    __table_args__ = (UniqueConstraint("platform_id", "normalized_title"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="CASCADE"))
    normalized_title: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16))
    wikidata_id: Mapped[str | None] = mapped_column(String(20))
    sources: Mapped[dict] = mapped_column(JSON, default=dict)
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class KnowledgeChunk(Base):
    """Passage de connaissances (une section d'une page, 400 mots au plus), avec sa source et sa licence."""

    __tablename__ = "knowledge_chunk"
    __table_args__ = (Index("ix_knowledge_chunk_game", "platform_id", "normalized_title"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platform.id", ondelete="CASCADE"))
    normalized_title: Mapped[str] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(20))   # wikipedia | strategywiki
    lang: Mapped[str] = mapped_column(String(2))
    page: Mapped[str] = mapped_column(String(300))
    section: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(600))
    license: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)


class PlayReset(Base):
    """Temps de jeu remis à zéro pour un jeu. Les parties de Game Manager sont effacées ; les journaux de RetroArch
    restent sur la console (on n'y touche pas) : `ra_baseline` est leur total au moment de la remise à zéro, retiré
    ensuite de ce qu'ils comptent. Clé : celle des statistiques (« id:12 », « path:/mnt/… », « ra:nom »)."""

    __tablename__ = "play_reset"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(1100), unique=True)
    ra_baseline: Mapped[int] = mapped_column(Integer, default=0)
    reset_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PlaySession(Base):
    """Une partie observée par Game Manager (jeu en cours sur la console), datée avec l'horloge du Mac."""

    __tablename__ = "play_session"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rom_path: Mapped[str] = mapped_column(String(1024))
    platform_dir: Mapped[str | None] = mapped_column(String(100))
    game_id: Mapped[int | None] = mapped_column(ForeignKey("remote_file.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(512))   # titre au moment de la partie (le jeu peut disparaître)
    process: Mapped[str | None] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    ended_at: Mapped[datetime] = mapped_column(UTCDateTime)
