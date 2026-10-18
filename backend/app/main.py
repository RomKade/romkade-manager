from pathlib import Path

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import bluetooth, catalog, controls, descriptions, knowledge, llm, play, players, playtime, saves, system, transfers, videos, volume
from app.api.routes import router
from app.config import SettingsStore, data_dir
from app.credentials import CredentialStore, default_store
from app.db.session import init_db
from app.device import launcher
from app.device.pool import DevicePool
from app.device.ssh_client import DeviceClient, HostKeyStore
from app.errors import AppError
from app.security import LocalOnlyMiddleware
from app.services.catalog_sync import SyncManager
from app.services.gameinfo import apply_all as apply_gameinfo
from app.services.llm import LlmConfigStore
from app.services.genres import apply_all as apply_genres
from app.services.boxart import BoxartStore
from app.services.images import ImageCache
from app.services.playtime import PlaySettingsStore, PlayTracker
from app.services.knowledge import Fetcher, KnowledgeJobs
from app.services.knowledge import settings_store as knowledge_settings
from app.services.search import SearchService
from app.device.systems import SystemService
from app.services.catalog_watch import CatalogWatcher
from app.services.save_vault import SaveVault
from app.services.staging import StagingStore
from app.services.transfers import TransferManager


def create_app(
    settings_store: SettingsStore | None = None,
    credentials: CredentialStore | None = None,
    known_hosts: Path | None = None,
    db_path: Path | None = None,
    cache_dir: Path | None = None,
    frontend_dist: Path | None = None,
    staging_dir: Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Suivi du temps de jeu : interroge la console toutes les 30 s (AGM_NO_TRACKER=1 pour le couper).
        if os.environ.get("AGM_NO_TRACKER") != "1":
            app.state.tracker.start()
        app.state.search.start()
        app.state.watcher.start()  # veille de la carte (AGM_NO_WATCH=1 pour la couper)
        yield
        await app.state.watcher.stop()
        await app.state.search.stop()
        await app.state.tracker.stop()
        await app.state.transfers.close()
        await app.state.pool.close()

    app = FastAPI(
        title="ROMKADE Manager",
        version="0.4.0",
        lifespan=lifespan,
        description="Catalogue local et transferts vers une Anbernic RG35XX Pro.",
    )
    base = data_dir()
    app.state.settings_store = settings_store or SettingsStore()
    app.state.credentials = credentials or default_store()
    app.state.host_keys = HostKeyStore(known_hosts or base / "known_hosts")
    app.state.sessions = init_db(db_path or base / "catalog.sqlite3")
    # Table de genres embarquée : recalcul complet à chaque démarrage (quelques dixièmes de seconde),
    # ce qui applique aussi une table mise à jour avec l'application.
    apply_genres(app.state.sessions)
    apply_gameinfo(app.state.sessions)
    app.state.sync = SyncManager(app.state.sessions)
    app.state.image_cache = ImageCache(cache_dir or base / "cache" / "images")
    app.state.boxart = BoxartStore((cache_dir or base / "cache" / "images").parent / "boxart")
    app.state.pool = DevicePool()
    # Copies des sauvegardes sur le Mac (à côté du cache en test, dans le dossier de données sinon).
    app.state.save_vault = SaveVault((cache_dir.parent if cache_dir else base) / "save-backups")
    # Commandes sur la console, sur la connexion SSH partagée du pool (une poignée de main SSH coûte ~0,5 s sur la
    # console ; les tests remplacent ce runner).
    app.state.device_runner = lambda client, command, timeout=20: app.state.pool.run(client, command, timeout)
    app.state.youtube_transport = None  # les tests y branchent un faux YouTube (httpx.MockTransport)
    app.state.staging = StagingStore(staging_dir or base / "staging")
    st = app.state
    app.state.system = SystemService(st.settings_store, lambda: st.device_runner,
                                     lambda: DeviceClient(st.settings_store.load(), st.credentials, st.host_keys))
    app.state.search = SearchService(st.sessions, cache_dir.parent if cache_dir else base)
    # Connaissances pour l'assistant ; récupérées pour les nouveaux jeux après une synchronisation si l'option est active.
    app.state.knowledge = KnowledgeJobs(st.sessions, Fetcher(getattr(st, "knowledge_transport", None)),
                                        knowledge_settings(cache_dir.parent if cache_dir else base))
    app.state.sync.after.append(app.state.knowledge.after_sync)
    app.state.play_settings = PlaySettingsStore((cache_dir.parent if cache_dir else base) / "play_settings.json")
    app.state.llm_config = LlmConfigStore((cache_dir.parent if cache_dir else base) / "llm.json")
    app.state.llm_transport = None  # les tests y branchent un faux fournisseur (httpx.MockTransport)
    app.state.tracker = PlayTracker(
        st.sessions, st.play_settings, lambda: st.settings_store.load().roms_root, lambda: st.device_runner,
        lambda: DeviceClient(st.settings_store.load(), st.credentials, st.host_keys),
        lambda: st.system.profile())
    app.state.transfers = TransferManager(
        st.sessions, st.staging, st.sync,
        lambda: DeviceClient(st.settings_store.load(), st.credentials, st.host_keys))
    app.state.watcher = CatalogWatcher(
        st.sessions, st.sync, st.transfers.idle, st.pool,
        lambda: DeviceClient(st.settings_store.load(), st.credentials, st.host_keys))

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.to_dict(), status_code=exc.status)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Une erreur imprévue garde la forme habituelle, avec un message lisible plutôt qu'un « Erreur 500 » nu.
        logging.getLogger("agm").exception("Erreur interne")
        return JSONResponse({"error": {"code": "internal_error", "message": f"Erreur interne : {type(exc).__name__}: {exc}",
                                       "details": {}}}, status_code=500)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "validation_error", "message": "Paramètres invalides",
                       "details": {"errors": [{"loc": list(e.get("loc", ())), "msg": e.get("msg"),
                                               "type": e.get("type")} for e in exc.errors()]}}},
            status_code=422,
        )

    # Les tests utilisent l'hôte « test » ; en usage réel seul localhost est accepté.
    app.add_middleware(LocalOnlyMiddleware, extra_hosts=_extra_hosts())
    app.include_router(router)
    app.include_router(catalog.router)
    app.include_router(transfers.router)
    app.include_router(videos.router)
    app.include_router(play.router)
    app.include_router(saves.router)
    app.include_router(bluetooth.router)
    app.include_router(players.router)
    app.include_router(volume.router)
    app.include_router(descriptions.router)
    app.include_router(controls.router)
    app.include_router(llm.router)
    app.include_router(knowledge.router)
    app.include_router(playtime.router)
    app.include_router(system.router)
    _mount_frontend(app, frontend_dist)
    return app


def _extra_hosts() -> set[str]:
    return {h.strip().lower() for h in os.environ.get("AGM_EXTRA_HOSTS", "").split(",") if h.strip()}


def _mount_frontend(app: FastAPI, dist: Path | None) -> None:
    """Sert l'interface compilée (frontend/dist) sur le même port que l'API."""
    dist = dist or Path(os.environ.get("AGM_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
    index = dist / "index.html"
    if not index.exists():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith(("api/", "docs", "openapi.json", "redoc")):
            return JSONResponse({"error": {"code": "not_found", "message": "Route inconnue", "details": {}}}, 404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
