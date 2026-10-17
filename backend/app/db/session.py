"""Moteur SQLite (WAL, clés étrangères) et migrations Alembic appliquées au démarrage."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ScanRun, Transfer, utcnow

MIGRATIONS = Path(__file__).parent / "migrations"


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def run_migrations(engine: Engine) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def init_db(db_path: Path) -> sessionmaker[Session]:
    engine = make_engine(db_path)
    run_migrations(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    # Une synchronisation interrompue (arrêt du serveur) ne doit pas rester "running".
    with factory.begin() as s:
        s.execute(update(ScanRun).where(ScanRun.status == "running")
                  .values(status="interrupted", finished_at=utcnow(), error="Serveur arrêté pendant la synchronisation"))
        s.execute(update(Transfer).where(Transfer.status.in_(("queued", "running", "verifying")))
                  .values(status="interrupted", finished_at=utcnow(),
                          error="Serveur arrêté pendant le transfert. Le fichier temporaire sera nettoyé au prochain envoi."))
    return factory
