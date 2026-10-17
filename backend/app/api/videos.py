"""Bandes-annonces YouTube : clé d'API (trousseau macOS) et recherche à la demande, mise en cache."""

import asyncio

from fastapi import APIRouter, Query, Request

from app import errors
from app.catalog_schemas import VideoLookupOut, YouTubeKeyIn, YouTubeSettingsOut
from app.services import catalog_query as cq
from app.services import videos as yt
from app.services.genres import ARCADE_DIRS
from app.platforms import canonical

router = APIRouter(prefix="/api", tags=["videos"])


def _key(request: Request) -> str | None:
    return request.app.state.credentials.get_password(yt.KEY_HOST, yt.KEY_ACCOUNT)


@router.get("/settings/youtube", response_model=YouTubeSettingsOut)
def youtube_settings(request: Request) -> YouTubeSettingsOut:
    return YouTubeSettingsOut(configured=bool(_key(request)))


@router.put("/settings/youtube", status_code=204)
def put_youtube_key(body: YouTubeKeyIn, request: Request) -> None:
    key = body.api_key.strip()
    if not yt.API_KEY_RE.fullmatch(key):
        raise errors.AppError("youtube_key_format", "Ce n'est pas une clé d'API Google (lettres, chiffres, - et _, "
                              "commence souvent par « AIza »).", 422)
    request.app.state.credentials.set_password(yt.KEY_HOST, yt.KEY_ACCOUNT, key)


@router.delete("/settings/youtube", status_code=204)
def delete_youtube_key(request: Request) -> None:
    request.app.state.credentials.delete_password(yt.KEY_HOST, yt.KEY_ACCOUNT)


@router.get("/games/{game_id}/video", response_model=VideoLookupOut)
async def game_video(game_id: int, request: Request,
                     refresh: bool = Query(False, description="Refaire la recherche (coûte du quota YouTube)")) -> VideoLookupOut:
    """Vidéos YouTube du jeu, la plus pertinente d'abord. Recherche au premier appel, cache ensuite."""
    sessions = request.app.state.sessions

    def lookup():
        with sessions() as s:
            f = cq.get_file(s, game_id)
            q = yt.build_query(f)
            row = yt.cached(s, f)
            directory = canonical(f.platform.directory)
            console = "arcade" if directory in ARCADE_DIRS else yt.SEARCH_NAMES.get(directory, f.platform.label or "")
            return q, yt.search_title(f), console, (row.videos, row.fetched_at) if row else None

    query, title, console, hit = await asyncio.to_thread(lookup)
    if hit and not refresh:
        return yt.to_out(query, "found" if hit[0] else "not_found", hit[0], hit[1])
    key = _key(request)
    if not key:
        return yt.to_out(query, "no_key", [])
    items = await yt.youtube_search(key, query, request.app.state.youtube_transport)
    found = yt.rank_videos(items, title, console)

    def save():
        with sessions.begin() as s:
            row = yt.store(s, cq.get_file(s, game_id), query, found)
            s.flush()
            return row.fetched_at

    fetched = await asyncio.to_thread(save)
    return yt.to_out(query, "found" if found else "not_found", found, fetched)
