"""Temps de jeu : état en cours, statistiques, historique, réglage de l'alerte."""

import asyncio
import re
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import errors
from app.catalog_schemas import GameOut
from app.db.models import Platform, PlaySession, RemoteFile, utcnow
from app.device.ssh_client import DeviceClient
from app.services import catalog_query as cq
from app.services import playtime as pt
from app.services.classify import stem_of

router = APIRouter(prefix="/api/play", tags=["playtime"])


class AlertOut(BaseModel):
    id: int
    created_at: datetime
    minutes: int
    scope: str
    game_title: str


class PlayStateOut(BaseModel):
    playing: bool
    game: GameOut | None
    title: str | None
    session_started_at: datetime | None
    session_seconds: int
    today_seconds: int
    settings: pt.PlaySettings
    alerts: list[AlertOut]


class DayOut(BaseModel):
    date: str
    seconds: int


class GameTimeOut(BaseModel):
    title: str
    platform: str | None
    game: GameOut | None
    seconds: int
    sessions: int
    last_played: datetime | None
    last_played_console: str | None  # date des journaux RetroArch (horloge de la console)


class SessionOut(BaseModel):
    id: int
    title: str
    platform: str | None
    game: GameOut | None
    started_at: datetime
    ended_at: datetime
    seconds: int


class PlayStatsOut(BaseModel):
    today_seconds: int
    week_seconds: int
    total_seconds: int
    days: list[DayOut]
    games: list[GameTimeOut]
    sessions: list[SessionOut]
    retroarch_available: bool


@router.get("/settings", response_model=pt.PlaySettings)
def get_settings(request: Request) -> pt.PlaySettings:
    return request.app.state.play_settings.load()


@router.put("/settings", response_model=pt.PlaySettings)
def put_settings(body: pt.PlaySettings, request: Request) -> pt.PlaySettings:
    request.app.state.play_settings.save(body)
    return body


@router.get("/state", response_model=PlayStateOut)
async def play_state(request: Request) -> PlayStateOut:
    """Jeu en cours, durée de la partie et de la journée, alertes à afficher. Ne contacte pas la console :
    lit ce que le suivi a observé (toutes les 30 s)."""
    tr = request.app.state.tracker
    now = utcnow()
    cur = tr.current
    game = None
    if cur:
        def find():
            with request.app.state.sessions() as s:
                row = s.get(PlaySession, cur["id"])
                f = s.get(RemoteFile, row.game_id, options=[joinedload(RemoteFile.platform)]) if row and row.game_id else None
                return cq.to_game(f) if f else None
        game = await asyncio.to_thread(find)
    today = await asyncio.to_thread(tr.minutes_today, now)
    return PlayStateOut(
        playing=cur is not None, game=game, title=cur["title"] if cur else None,
        session_started_at=cur["started_at"] if cur else None,
        session_seconds=int((cur["last_seen"] - cur["started_at"]).total_seconds()) if cur else 0,
        today_seconds=int(today * 60), settings=request.app.state.play_settings.load(),
        alerts=[AlertOut(**a) for a in tr.pending_alerts()])


@router.post("/alerts/{alert_id}/ack", status_code=204)
def ack_alert(alert_id: int, request: Request) -> None:
    request.app.state.tracker.acknowledge(alert_id)


@router.get("/stats", response_model=PlayStatsOut)
async def play_stats(request: Request, days: int = Query(14, ge=1, le=90)) -> PlayStatsOut:
    """Temps de jeu par jour et par jeu, historique des parties. Les journaux de RetroArch sont lus sur la
    console quand elle répond (lecture seule) ; sans elle, seules les parties suivies par Game Manager comptent."""
    st = request.app.state
    try:
        _, out = await st.device_runner(DeviceClient(st.settings_store.load(), st.credentials, st.host_keys),
                                        pt.retroarch_command(await st.system.ensure()))
        ra_entries, history = pt.parse_retroarch(out)
        ra_ok = True
    except errors.AppError:
        ra_entries, history, ra_ok = [], [], False
    return await asyncio.to_thread(_stats, request, days, ra_entries, history, ra_ok)


def _stats(request: Request, days: int, ra_entries: list[dict], history: list[str], ra_ok: bool) -> PlayStatsOut:
    now = utcnow()
    today = pt.local_day(now)
    root = request.app.state.settings_store.load().roms_root.rstrip("/") + "/"
    with request.app.state.sessions() as s:
        rows = list(s.scalars(select(PlaySession).order_by(PlaySession.started_at.desc())))
        games = {f.id: f for f in s.scalars(select(RemoteFile).options(joinedload(RemoteFile.platform))
                                             .where(RemoteFile.id.in_({r.game_id for r in rows if r.game_id})))}
        # Pour rattacher les journaux RetroArch : jeu par chemin (historique) puis par nom de fichier.
        by_stem: dict[str, RemoteFile] = {}
        for f in s.scalars(select(RemoteFile).join(Platform).options(joinedload(RemoteFile.platform))
                           .where(RemoteFile.role == "candidate", RemoteFile.deleted_at.is_(None))):
            by_stem.setdefault(stem_of(f.filename).lower(), f)
            if root + f"{f.platform.directory}/{f.relative_path}" in history:
                by_stem[stem_of(f.filename).lower()] = f  # le chemin de l'historique départage les homonymes
        out_games = {gid: cq.to_game(f) for gid, f in games.items()}

        def secs(r: PlaySession) -> int:
            return max(0, int((r.ended_at - r.started_at).total_seconds()))

        # par jour (heure locale du Mac)
        per_day: dict = defaultdict(int)
        first_day = today - timedelta(days=days - 1)
        for r in rows:
            d = first_day
            while d <= today:
                a, b = pt.day_bounds(d)
                per_day[d] += int(pt.overlap_seconds(r.started_at, r.ended_at, a, b))
                d += timedelta(days=1)
        week_start = today - timedelta(days=6)

        # par jeu : sessions de Game Manager + journaux RetroArch (le plus grand des deux, ils se recouvrent)
        per_game: dict = {}
        for r in rows:
            key = ("id", r.game_id) if r.game_id else ("path", r.rom_path)
            g = per_game.setdefault(key, {"title": r.title, "platform": r.platform_dir, "game": out_games.get(r.game_id),
                                          "app": 0, "ra": 0, "sessions": 0, "last": None, "last_console": None})
            g["app"] += secs(r)
            g["sessions"] += 1
            g["last"] = max(g["last"], r.ended_at) if g["last"] else r.ended_at
        for e in ra_entries:
            f = by_stem.get(e["stem"].lower())
            key = ("id", f.id) if f else ("ra", e["stem"])
            game = cq.to_game(f) if f else None
            g = per_game.setdefault(key, {"title": game.title if game else e["stem"], "platform": f.platform.directory if f else None,
                                          "game": game, "app": 0, "ra": 0, "sessions": 0, "last": None, "last_console": None})
            g["ra"] += e["seconds"]
            g["last_console"] = e["last_played"]

    game_list = [GameTimeOut(title=g["title"], platform=g["platform"], game=g["game"], seconds=max(g["app"], g["ra"]),
                             sessions=g["sessions"], last_played=g["last"], last_played_console=g["last_console"])
                 for g in per_game.values() if max(g["app"], g["ra"]) > 0]
    game_list.sort(key=lambda g: -g.seconds)
    return PlayStatsOut(
        today_seconds=per_day[today], week_seconds=sum(v for d, v in per_day.items() if d >= week_start),
        total_seconds=sum(g.seconds for g in game_list),
        days=[DayOut(date=(first_day + timedelta(days=i)).isoformat(), seconds=per_day[first_day + timedelta(days=i)])
              for i in range(days)],
        games=game_list,
        sessions=[SessionOut(id=r.id, title=r.title, platform=r.platform_dir, game=out_games.get(r.game_id),
                             started_at=r.started_at, ended_at=r.ended_at, seconds=secs(r)) for r in rows[:40]],
        retroarch_available=ra_ok)


class RecentGameOut(BaseModel):
    title: str
    platform: str | None
    rom_path: str
    game: GameOut | None
    last_played: datetime | None   # horloge du Mac (parties suivies par Game Manager)
    seconds: int                   # temps cumulé suivi par Game Manager


@router.get("/recent", response_model=list[RecentGameOut])
async def recent_games(request: Request, limit: int = Query(12, ge=1, le=50)) -> list[RecentGameOut]:
    """Jeux joués récemment, pour y rejouer. Ordre : l'historique de RetroArch sur la console (il compte aussi
    les parties lancées depuis le menu de la console), complété par les parties suivies par Game Manager
    (jeux hors RetroArch : PSP, DS…). Sans console joignable, seules ces dernières comptent."""
    st = request.app.state
    try:
        _, out = await st.device_runner(DeviceClient(st.settings_store.load(), st.credentials, st.host_keys),
                                        pt.history_command(await st.system.ensure()))
        history = re.findall(r'"path":\s*"([^"]+)"', out)
    except errors.AppError:
        history = []
    return await asyncio.to_thread(_recent, request, history, limit)


def _recent(request: Request, history: list[str], limit: int) -> list[RecentGameOut]:
    root = request.app.state.settings_store.load().roms_root.rstrip("/") + "/"
    with request.app.state.sessions() as s:
        sessions = list(s.scalars(select(PlaySession).order_by(PlaySession.ended_at.desc())))
        by_path: dict[str, dict] = {}
        for r in sessions:
            e = by_path.setdefault(r.rom_path, {"last": r.ended_at, "seconds": 0, "title": r.title, "platform": r.platform_dir})
            e["seconds"] += max(0, int((r.ended_at - r.started_at).total_seconds()))
        order = list(dict.fromkeys(history + [p for p in by_path if p not in history]))

        def game_for(path: str):
            if not path.startswith(root):
                return None
            directory, _, rel = path[len(root):].partition("/")
            f = s.scalar(select(RemoteFile).join(Platform).options(joinedload(RemoteFile.platform))
                         .where(Platform.directory == directory, RemoteFile.relative_path == rel,
                                RemoteFile.role == "candidate"))
            return cq.to_game(f) if f else None

        out = []
        for path in order[:limit]:
            g = game_for(path)
            e = by_path.get(path, {})
            directory = path[len(root):].split("/", 1)[0] if path.startswith(root) else None
            out.append(RecentGameOut(title=g.title if g else e.get("title") or stem_of(path.rsplit("/", 1)[-1]),
                                     platform=directory, rom_path=path, game=g, last_played=e.get("last"),
                                     seconds=e.get("seconds", 0)))
        return out
