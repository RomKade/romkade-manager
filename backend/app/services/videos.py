"""Bandes-annonces : recherche YouTube (API officielle YouTube Data v3) et choix de la vidéo la plus pertinente.

Une recherche coûte 100 unités de quota ; le quota gratuit est de 10 000 unités par jour, soit environ
100 jeux par jour. La recherche se fait donc à la demande, au premier clic sur un jeu, et son résultat
est gardé en cache (table game_video) : les clics suivants, et les autres éditions du même jeu, ne
coûtent plus rien.

La clé d'API est fournie par l'utilisateur et rangée dans le trousseau macOS.
"""

import re
import urllib.parse
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import errors
from app.catalog_schemas import VideoLookupOut, VideoOut
from app.db.models import GameVideo, RemoteFile, utcnow
from app.services.classify import display_title, search_key
from app.services.genres import ARCADE_DIRS
from app.platforms import canonical

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
KEY_HOST, KEY_ACCOUNT = "youtube.com", "api-key"
API_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{30,60}$")
MAX_RESULTS = 10
KEEP = 5

# Nom de la console tel qu'on le tape sur YouTube.
SEARCH_NAMES = {
    "FC": "NES", "FDS": "Famicom Disk System", "SFC": "SNES", "N64": "N64", "GB": "Game Boy", "GBC": "Game Boy Color",
    "GBA": "GBA", "NDS": "Nintendo DS", "VB": "Virtual Boy", "GW": "Game & Watch", "SMS": "Master System",
    "MD": "Mega Drive Genesis", "MDCD": "Sega CD", "SEGA32X": "32X", "GG": "Game Gear", "SATURN": "Saturn",
    "DREAMCAST": "Dreamcast", "PS": "PS1", "PSP": "PSP", "PCE": "PC Engine", "PCECD": "PC Engine CD",
    "WS": "WonderSwan", "MSX": "MSX", "A2600": "Atari 2600", "A7800": "Atari 7800", "LYNX": "Atari Lynx",
    "NGP": "Neo Geo Pocket", "NEOGEO": "Neo Geo", "PICO": "PICO-8", "OPENBOR": "OpenBOR",
}
GOOD_WORDS = {"trailer": 1.0, "gameplay": 0.8, "longplay": 0.6, "playthrough": 0.5, "intro": 0.4,
              "commercial": 0.6, "pub": 0.3, "attract": 0.4}
BAD_WORDS = {"review", "reaction", "react", "top", "ranking", "tier", "unboxing", "vs", "versus", "tutorial",
             "mod", "hack", "romhack", "music", "ost", "soundtrack", "remix", "cover", "piano", "lets", "news"}
STOP = {"the", "a", "of", "and", "de", "la", "le", "les", "no"}


def search_title(f: RemoteFile) -> str:
    return display_title(f.full_title) if f.full_title else f.title


def build_query(f: RemoteFile) -> str:
    directory = canonical(f.platform.directory)
    console = "arcade" if directory in ARCADE_DIRS else SEARCH_NAMES.get(directory, f.platform.label or directory)
    return f"{search_title(f)} {console} gameplay"


def youtube_search_url(query: str) -> str:
    return "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query})


def _words(text: str) -> list[str]:
    # search_key garde le contenu des parenthèses : « Super Mario World (SNES) » contient bien « snes ».
    return search_key(text).split()


def score(video_title: str, game_title: str, console: str, rank: int) -> float:
    """Part des mots du titre du jeu présents dans le titre de la vidéo, plus quelques indices de pertinence."""
    vw = set(_words(video_title))
    s = 3 * _coverage(video_title, game_title)
    s += max((v for w, v in GOOD_WORDS.items() if w in vw), default=0)
    if any(w in vw for w in _words(console)):
        s += 0.5
    s -= sum(w in vw for w in BAD_WORDS)
    return s - 0.05 * rank  # à égalité, l'ordre de YouTube départage


def rank_videos(items: list[dict], game_title: str, console: str) -> list[VideoOut]:
    scored = []
    for i, it in enumerate(items):
        vid = (it.get("id") or {}).get("videoId")
        sn = it.get("snippet") or {}
        if not vid:
            continue
        title = _unescape(sn.get("title", ""))
        # Il faut au moins la moitié des mots du titre : sinon ce n'est pas le bon jeu.
        if _coverage(title, game_title) < 0.5:
            continue
        scored.append((score(title, game_title, console, i),
                       VideoOut(id=vid, title=title, channel=_unescape(sn.get("channelTitle", "")))))
    scored.sort(key=lambda t: -t[0])
    return [v for _, v in scored[:KEEP]]


def _coverage(video_title: str, game_title: str) -> float:
    vw = set(_words(video_title))
    gw = [w for w in _words(game_title) if w not in STOP] or _words(game_title)
    return sum(w in vw for w in gw) / len(gw) if gw else 0.0


def _unescape(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
            .replace("&lt;", "<").replace("&gt;", ">"))


async def youtube_search(api_key: str, query: str, transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    params = {"part": "snippet", "type": "video", "maxResults": MAX_RESULTS, "q": query,
              "videoEmbeddable": "true", "safeSearch": "moderate", "key": api_key}
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as http:
            r = await http.get(SEARCH_URL, params=params)
    except httpx.HTTPError as exc:
        raise errors.AppError("youtube_unreachable", "YouTube ne répond pas. Vérifie la connexion Internet du Mac.",
                              502, {"error": type(exc).__name__}) from exc
    if r.status_code == 200:
        return r.json().get("items", [])
    reasons = {e.get("reason") for e in (r.json().get("error", {}).get("errors") or [])} if _is_json(r) else set()
    if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
        raise errors.AppError("youtube_quota", "Quota YouTube du jour épuisé (environ 100 recherches par jour). "
                              "Les vidéos déjà trouvées restent disponibles ; réessaie demain.", 429)
    if r.status_code in (400, 403) and (reasons & {"keyInvalid", "badRequest", "accessNotConfigured", "forbidden"}
                                        or not reasons):
        raise errors.AppError("youtube_key_invalid", "La clé d'API YouTube est refusée. Vérifie-la dans Paramètres "
                              "et que « YouTube Data API v3 » est activée pour ce projet Google.", 400,
                              {"reasons": sorted(reasons)})
    raise errors.AppError("youtube_error", f"YouTube a répondu {r.status_code}", 502, {"reasons": sorted(reasons)})


def _is_json(r: httpx.Response) -> bool:
    try:
        r.json()
        return True
    except ValueError:
        return False


def cached(s: Session, f: RemoteFile) -> GameVideo | None:
    return s.scalar(select(GameVideo).where(GameVideo.platform_id == f.platform_id,
                                            GameVideo.normalized_title == f.normalized_title))


def store(s: Session, f: RemoteFile, query: str, videos: list[VideoOut]) -> GameVideo:
    row = cached(s, f) or GameVideo(platform_id=f.platform_id, normalized_title=f.normalized_title)
    row.query, row.videos, row.fetched_at = query, [v.model_dump() for v in videos], utcnow()
    s.add(row)
    return row


def to_out(query: str, status: str, videos: list, fetched_at: datetime | None = None) -> VideoLookupOut:
    return VideoLookupOut(status=status, query=query, search_url=youtube_search_url(query),
                          videos=[VideoOut.model_validate(v) for v in videos], fetched_at=fetched_at)
