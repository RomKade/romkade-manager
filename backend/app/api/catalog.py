"""Routes du catalogue : servies depuis SQLite, console éteinte comprise.

Seules exceptions qui contactent la console : POST /api/catalog/sync (scan en lecture seule)
et GET /api/games/{id}/image quand l'image n'est pas encore en cache.
"""

import asyncio
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from app import errors
from app.catalog_schemas import (
    CatalogPlatformOut, CatalogStatusOut, ChangesPageOut, DuplicateGroupOut, GameDetailOut, GameOut, GamesPageOut, SearchOut,
    FacetsOut, ScanRunOut, UnmatchedImagesOut,
)
from app.db.models import PlatformImage
from app.device.ssh_client import DeviceClient
from app.services import boxart
from app.services import catalog_query as cq
from app.services.genres import load_index
from app.services.images import media_type

router = APIRouter(prefix="/api")


def _sessions(request: Request):
    return request.app.state.sessions


def _client(request: Request) -> DeviceClient:
    st = request.app.state
    return DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)


def console_id(request: Request) -> str:
    """Identité de la console configurée : empreinte de sa clé SSH approuvée, sinon « hôte:port »."""
    st = request.app.state
    s = st.settings_store.load()
    return st.host_keys.fingerprint(s.host, s.port) or f"{s.host}:{s.port}"


# ---------- synchronisation ----------

@router.post("/catalog/sync", status_code=202, response_model=ScanRunOut, tags=["catalog"])
async def start_sync(request: Request) -> ScanRunOut:
    """Lance un scan en lecture seule de la carte et met le catalogue à jour en tâche de fond.
    Suivre l'avancement avec GET /api/catalog/sync/{id}."""
    run_id = await request.app.state.sync.start(_client(request))
    return await asyncio.to_thread(_with_session, request, cq.get_run, run_id)


@router.get("/catalog/sync/{run_id}", response_model=ScanRunOut, tags=["catalog"])
def get_sync(run_id: int, request: Request) -> ScanRunOut:
    return _with_session(request, cq.get_run, run_id)


@router.get("/catalog/syncs", response_model=list[ScanRunOut], tags=["catalog"])
def list_syncs(request: Request, limit: int = Query(20, ge=1, le=200)) -> list[ScanRunOut]:
    return _with_session(request, cq.list_runs, limit)


@router.get("/catalog/status", response_model=CatalogStatusOut, tags=["catalog"])
def catalog_status(request: Request) -> CatalogStatusOut:
    return _with_session(request, cq.status, request.app.state.sync.running())


@router.get("/catalog/changes", response_model=ChangesPageOut, tags=["catalog"])
def catalog_changes(
    request: Request,
    run_id: int | None = Query(None, description="Par défaut : dernière synchronisation aboutie"),
    change: Literal["added", "modified", "removed", "restored"] | None = None,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
) -> ChangesPageOut:
    return _with_session(request, cq.changes, run_id, change, offset, limit)


@router.get("/catalog/duplicates", response_model=list[DuplicateGroupOut], tags=["catalog"])
def catalog_duplicates(request: Request, platform: list[str] | None = Query(None)) -> list[DuplicateGroupOut]:
    return _with_session(request, cq.duplicates, platform)


@router.get("/catalog/unmatched-images", response_model=list[UnmatchedImagesOut], tags=["catalog"])
def catalog_unmatched_images(request: Request, sample: int = Query(10, ge=0, le=200)) -> list[UnmatchedImagesOut]:
    """Images des dossiers Imgs qu'aucun jeu n'a pu rapprocher (par nom de fichier)."""
    return _with_session(request, cq.unmatched_images, sample)


# ---------- plateformes et jeux ----------

@router.get("/platforms", response_model=list[CatalogPlatformOut], tags=["catalog"])
def platforms(request: Request, include_absent: bool = False) -> list[CatalogPlatformOut]:
    return _with_session(request, cq.list_platforms, include_absent)


@router.get("/games", response_model=GamesPageOut, tags=["catalog"])
async def games(
    request: Request,
    q: str | None = Query(None, max_length=100, description="Recherche : Typesense (fautes de frappe tolérées, pertinence) "
                          "quand il est prêt, sinon mots du nom de fichier (accents et casse ignorés)"),
    platform: list[str] | None = Query(None, description="Dossiers de plateforme, ex. PS, SFC"),
    extension: list[str] | None = Query(None, description="Ex. chd, zip"),
    region: list[str] | None = Query(None, description="Ex. Europe, USA, Japon"),
    genre: list[str] | None = Query(None, description="Clés de genre (GET /api/catalog/facets), « none » pour les jeux non classés"),
    subgenre: list[str] | None = Query(None, description="Sous-genres, ex. sport.golf (GET /api/catalog/facets)"),
    role: Literal["candidate", "component", "auxiliary", "program", "all"] = "candidate",
    has_image: bool | None = None,
    include_removed: bool = Query(False, description="Inclure les fichiers disparus de la carte"),
    favorite: bool = Query(False, description="Seulement les jeux favoris"),
    sort: Literal["name", "size", "date", "added", "year"] = "name",
    order: Literal["asc", "desc"] = "asc",
    offset: int = Query(0, ge=0),
    limit: int = Query(60, ge=1, le=500),
) -> GamesPageOut:
    search = request.app.state.search
    # Favoris : peu de jeux, filtrés par SQLite (l'index Typesense ne les connaît pas).
    if q and q.strip() and search.ready and role == "candidate" and has_image is None and not favorite:
        try:
            ids, total = await search.search(q.strip(), platforms=platform, extensions=extension, regions=region,
                                             genres=genre, subgenres=subgenre, include_removed=include_removed,
                                             sort=sort, order=order,
                                             offset=offset, limit=limit)
            return await asyncio.to_thread(_with_session, request, cq.games_by_ids, ids, total, offset, limit)
        except Exception:  # noqa: BLE001 — Typesense indisponible : recherche SQLite
            search.ready = False
    return await asyncio.to_thread(_with_session, request, lambda s: cq.search_games(
        s, q=q, platforms=platform, extensions=extension, regions=region, role=role, genres=genre, subgenres=subgenre,
        has_image=has_image, favorite=favorite, console=console_id(request) if favorite else None,
        include_removed=include_removed, sort=sort, order=order, offset=offset, limit=limit))


@router.get("/search", response_model=SearchOut, tags=["catalog"])
async def quick_search(request: Request, q: str = Query(..., min_length=1, max_length=100),
                       limit: int = Query(8, ge=1, le=30)) -> SearchOut:
    """Recherche rapide (tableau de bord) : les jeux les plus pertinents et le nombre total de résultats."""
    page = await games(request, q=q, platform=None, extension=None, region=None, genre=None, subgenre=None, role="candidate",
                       has_image=None, include_removed=False, favorite=False, sort="name", order="asc", offset=0,
                       limit=limit)
    return SearchOut(items=page.items, total=page.page.total, engine="typesense" if request.app.state.search.ready else "sqlite")


@router.get("/search/status", tags=["catalog"])
def search_status(request: Request) -> dict:
    s = request.app.state.search
    return {"engine": "typesense" if s.ready else "sqlite", "status": s.status}


@router.get("/favorites", response_model=list[GameOut], tags=["catalog"])
async def favorites(request: Request, limit: int | None = Query(None, ge=1, le=500)) -> list[GameOut]:
    """Jeux favoris, le dernier ajouté en tête."""
    return await asyncio.to_thread(_with_session, request, cq.favorites, console_id(request), limit)


@router.put("/games/{game_id}/favorite", status_code=204, tags=["catalog"])
async def add_favorite(game_id: int, request: Request) -> None:
    await asyncio.to_thread(_with_write, request, cq.set_favorite, console_id(request), game_id, True)


@router.delete("/games/{game_id}/favorite", status_code=204, tags=["catalog"])
async def remove_favorite(game_id: int, request: Request) -> None:
    await asyncio.to_thread(_with_write, request, cq.set_favorite, console_id(request), game_id, False)


@router.get("/games/{game_id}", response_model=GameDetailOut, tags=["catalog"])
def game(game_id: int, request: Request) -> GameDetailOut:
    root = request.app.state.settings_store.load().roms_root
    return _with_session(request, cq.game_detail, game_id, root, console_id(request))


@router.get("/games/{game_id}/image", tags=["catalog"],
            responses={200: {"content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}}})
async def game_image(
    game_id: int, request: Request,
    size: Literal["thumb", "full"] = Query("full", description="thumb : miniature WebP pour la grille"),
) -> FileResponse:
    """Image de présentation (dossier Imgs). Lue une fois par SFTP en lecture seule, puis servie depuis le cache."""
    def lookup(s):
        f = cq.get_file(s, game_id)
        if not f.image_relpath:
            raise errors.AppError("image_not_found", "Aucune image rapprochée pour ce jeu", 404)
        img = s.scalar(select(PlatformImage).where(PlatformImage.platform_id == f.platform_id,
                                                   PlatformImage.relative_path == f.image_relpath))
        return f.platform.directory, f.image_relpath, img.size if img else None, \
            img.mtime.timestamp() if img and img.mtime else None

    plat_dir, relpath, img_size, mtime = await asyncio.to_thread(_with_session, request, lookup)
    cache = request.app.state.image_cache
    target = cache.path_for(plat_dir, relpath, img_size, mtime)
    if not target.exists():
        async with cache.lock(target):
            if not target.exists():
                async with request.app.state.pool.fs(_client(request)) as fs:
                    await cache.fetch(fs, plat_dir, relpath, target)
    served = await cache.thumbnail(target) if size == "thumb" else target
    return FileResponse(served, media_type=media_type(str(served)),
                        headers={"Cache-Control": "private, max-age=604800"})


@router.get("/games/{game_id}/boxart", tags=["catalog"],
            responses={200: {"content": {"image/png": {}, "image/webp": {}}}})
async def game_boxart(
    game_id: int, request: Request,
    size: Literal["thumb", "full"] = Query("thumb", description="thumb : miniature WebP pour la grille"),
) -> FileResponse:
    """Jaquette du jeu (libretro-thumbnails), téléchargée au premier appel puis servie depuis le cache du Mac."""
    def lookup(s):
        f = cq.get_file(s, game_id)
        s.expunge(f)
        return f

    f = await asyncio.to_thread(_with_session, request, lookup)
    if not boxart.has_source(f.platform.directory):
        raise errors.AppError("boxart_not_found", "Pas de banque de jaquettes pour cette console", 404)
    store = request.app.state.boxart
    path = await store.get(f, load_index())
    if path is None:
        raise errors.AppError("boxart_not_found", "Aucune jaquette trouvée pour ce jeu", 404)
    served = await store.thumbnail(path) if size == "thumb" else path
    return FileResponse(served, media_type=media_type(str(served)),
                        headers={"Cache-Control": "private, max-age=604800"})


@router.get("/catalog/facets", response_model=FacetsOut, tags=["catalog"])
def catalog_facets(request: Request, platform: list[str] | None = Query(None)) -> FacetsOut:
    """Valeurs disponibles pour les filtres (formats, régions, genres), avec leur nombre de jeux."""
    return _with_session(request, cq.facets, platform)


def _with_session(request: Request, fn, *args):
    with _sessions(request)() as s:
        return fn(s, *args)


def _with_write(request: Request, fn, *args):
    with _sessions(request).begin() as s:
        return fn(s, *args)
