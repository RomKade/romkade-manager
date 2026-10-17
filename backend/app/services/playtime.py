"""Temps de jeu : suivi des parties, statistiques, alerte « ça fait 4 heures que tu joues ».

Deux sources :
- PlayTracker (ce module) : toutes les POLL_SECONDS, le serveur regarde ce qui tourne sur la console et
  enregistre des sessions datées avec l'horloge du Mac (table play_session). C'est la seule source qui donne
  l'historique, le temps par jour et la session en cours ; elle ne voit que ce qui se joue quand le Mac et
  Game Manager tournent.
- Les journaux de RetroArch (playlists/logs/<cœur>/<jeu>.lrtl : temps total, dernière partie), qui comptent
  aussi les parties lancées depuis le menu de la console. Leur date vient de l'horloge de la console.

L'alerte compte la session en cours ou la journée (réglage), et peut s'afficher sur l'écran de la console
pendant le jeu (commande réseau SHOW_MSG de RetroArch).
"""

import asyncio
import json
import logging
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app import errors
from app.db.models import Platform, PlaySession, RemoteFile, utcnow
from app.device import launcher
from app.services.classify import display_title, stem_of

log = logging.getLogger("agm.playtime")
POLL_SECONDS = 30
GAP_SECONDS = 150          # au-delà, une absence coupe la session (console éteinte, jeu quitté)
STATUS_FRESH_SECONDS = 20  # l'état mis en cache par le suivi sert aussi à « jeu en cours »


class PlaySettings(BaseModel):
    alert_enabled: bool = False
    alert_minutes: int = Field(240, ge=5, le=24 * 60)
    alert_scope: Literal["session", "day"] = "session"
    repeat_minutes: int = Field(30, ge=0, le=12 * 60)  # 0 : une seule alerte
    console_message: bool = True


class PlaySettingsStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> PlaySettings:
        if self.path.exists():
            return PlaySettings.model_validate_json(self.path.read_text())
        return PlaySettings()

    def save(self, s: PlaySettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(s.model_dump(), indent=2))
        tmp.replace(self.path)


def local_day(dt: datetime) -> date:
    return dt.astimezone().date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day).astimezone()
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def overlap_seconds(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> float:
    return max(0.0, (min(a1, b1) - max(a0, b0)).total_seconds())


def fmt_minutes(minutes: float) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h} h {m:02d}" if h else f"{m} min"


class PlayTracker:
    def __init__(self, sessions: sessionmaker[Session], settings: PlaySettingsStore, roms_root, run, client_factory,
                 profile=None):
        self.sessions = sessions
        self.profile = profile or (lambda: None)  # fonction -> profil du firmware (app.device.systems)
        self.settings = settings
        self.roms_root = roms_root          # fonction -> racine des ROMs (réglage courant)
        self.run = run                      # fonction -> runner SSH (remplaçable en test)
        self.client_factory = client_factory
        self.current: dict | None = None    # {id, rom_path, started_at, last_seen, title}
        self.last_status: dict | None = None
        self.last_status_at: datetime | None = None
        self.alerts: list[dict] = []
        self._alerted: set[str] = set()
        self._task: asyncio.Task | None = None

    # ---------- boucle ----------

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self.current:
            await asyncio.to_thread(self._close, self.current)
            self.current = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:  # noqa: BLE001 — le suivi ne doit jamais s'arrêter
                log.exception("suivi du temps de jeu")
            await asyncio.sleep(POLL_SECONDS)

    async def poll_once(self, now: datetime | None = None) -> dict | None:
        now = now or utcnow()
        try:
            status = await launcher.status(self.run(), self.client_factory(), self.profile())
        except errors.AppError:
            status = None  # console injoignable : rien n'est en cours, à notre connaissance
        await self.observe(status, now)
        return status

    def invalidate(self) -> None:
        """Après un lancement ou une sortie de jeu, l'état gardé en cache n'est plus valable."""
        self.last_status_at = None

    def fresh_status(self, now: datetime | None = None) -> dict | None:
        now = now or utcnow()
        if self.last_status_at and (now - self.last_status_at).total_seconds() < STATUS_FRESH_SECONDS:
            return self.last_status
        return None

    # ---------- sessions ----------

    async def observe(self, status: dict | None, now: datetime) -> None:
        if status is not None:
            self.last_status, self.last_status_at = status, now
        # status None : console injoignable. La partie en cours n'est coupée qu'après GAP_SECONDS sans nouvelles.
        rom = status["rom_path"] if status and status.get("playing") else None
        cur = self.current
        if cur:
            changed = rom is not None and rom != cur["rom_path"]
            stopped = status is not None and rom is None
            silent = (now - cur["last_seen"]).total_seconds() > GAP_SECONDS
            if changed or stopped or silent:
                await asyncio.to_thread(self._close, cur)
                self.current = cur = None
        if rom and cur is None:
            self.current = cur = await asyncio.to_thread(self._open, rom, status.get("process"), now)
        if cur and rom:
            cur["last_seen"] = now
            await asyncio.to_thread(self._touch, cur["id"], now)
            await self._check_alerts(now)

    def _open(self, rom: str, process: str | None, now: datetime) -> dict:
        root = self.roms_root().rstrip("/") + "/"
        directory, rel = (rom[len(root):].split("/", 1) + [""])[:2] if rom.startswith(root) else (None, "")
        with self.sessions.begin() as s:
            game = None
            if directory:
                game = s.scalar(select(RemoteFile).join(Platform).where(Platform.directory == directory,
                                                                        RemoteFile.relative_path == rel))
            title = (display_title(game.full_title) if game and game.full_title else game.title) if game \
                else display_title(stem_of(rom.rsplit("/", 1)[-1]))
            row = PlaySession(rom_path=rom, platform_dir=directory, game_id=game.id if game else None, title=title,
                              process=process, started_at=now, ended_at=now)
            s.add(row)
            s.flush()
            return {"id": row.id, "rom_path": rom, "started_at": now, "last_seen": now, "title": title}

    def _touch(self, session_id: int, now: datetime) -> None:
        with self.sessions.begin() as s:
            s.execute(update(PlaySession).where(PlaySession.id == session_id).values(ended_at=now))

    def _close(self, cur: dict) -> None:
        self._touch(cur["id"], cur["last_seen"])

    # ---------- alertes ----------

    def minutes_today(self, now: datetime) -> float:
        start, end = day_bounds(local_day(now))
        with self.sessions() as s:
            rows = s.execute(select(PlaySession.started_at, PlaySession.ended_at)
                             .where(PlaySession.ended_at >= start, PlaySession.started_at < end)).all()
        return sum(overlap_seconds(a, b, start, end) for a, b in rows) / 60

    async def _check_alerts(self, now: datetime) -> None:
        cfg = self.settings.load()
        if not cfg.alert_enabled or not self.current:
            return
        if cfg.alert_scope == "session":
            elapsed = (now - self.current["started_at"]).total_seconds() / 60
            scope_key = f"session:{self.current['id']}"
        else:
            elapsed = await asyncio.to_thread(self.minutes_today, now)
            scope_key = f"day:{local_day(now)}"
        if elapsed < cfg.alert_minutes:
            return
        step = int((elapsed - cfg.alert_minutes) // cfg.repeat_minutes) if cfg.repeat_minutes else 0
        key = f"{scope_key}:{step}"
        if key in self._alerted:
            return
        self._alerted.add(key)
        alert = {"id": len(self.alerts) + 1, "created_at": now, "minutes": round(elapsed), "scope": cfg.alert_scope,
                 "game_title": self.current["title"], "acknowledged": False}
        self.alerts.append(alert)
        p = self.profile()
        if cfg.console_message and (p is None or p.capabilities()["on_screen_message"]):
            text = (f"Game Manager : {fmt_minutes(elapsed)} de jeu "
                    f"{'pour cette partie' if cfg.alert_scope == 'session' else 'aujourd hui'}. Pense a faire une pause !")
            msg = re.sub(r"[^A-Za-z0-9 :!.,'-]", "", text)
            try:
                await self.run()(self.client_factory(), f"bash -c 'echo -n \"SHOW_MSG {msg}\" > /dev/udp/127.0.0.1/55355'")
            except errors.AppError:
                pass

    def pending_alerts(self) -> list[dict]:
        return [a for a in self.alerts if not a["acknowledged"]]

    def acknowledge(self, alert_id: int) -> None:
        for a in self.alerts:
            if a["id"] == alert_id:
                a["acknowledged"] = True


# ---------- statistiques ----------

RA_LOGS = "/mnt/vendor/deep/retro/playlists/logs"
RA_HISTORY = "/.config/retroarch/content_history.lpl"


def parse_runtime(value: str) -> int:
    m = re.fullmatch(r"\s*(\d+):(\d{1,2}):(\d{1,2})\s*", value or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else 0


def retroarch_command(profile=None) -> str:
    """Lit tous les journaux de temps de RetroArch et l'historique, en une commande (lecture seule)."""
    logs = profile.ra_logs if profile else RA_LOGS
    hist = profile.ra_history if profile else RA_HISTORY
    out = ""
    if logs:
        out += (f"find {logs} -name '*.lrtl' 2>/dev/null | while IFS= read -r f; do "
                "echo \"@@LRTL $f\"; cat \"$f\"; echo; done; ")
    out += "echo @@HISTORY; "
    if hist:
        out += f"grep '\"path\":' {hist} 2>/dev/null; "
    return out + "true"



def history_command(profile=None) -> str:
    hist = profile.ra_history if profile else RA_HISTORY
    return f"grep '\"path\":' {hist} 2>/dev/null; true" if hist else "true"


def parse_retroarch(out: str) -> tuple[list[dict], list[str]]:
    entries, history = [], []
    for block in out.split("@@LRTL ")[1:]:
        path, _, body = block.partition("\n")
        body = body.split("@@HISTORY", 1)[0]
        try:
            data = json.loads(body.strip() or "{}")
        except ValueError:
            continue
        core = path.rsplit("/", 2)[-2] if path.count("/") >= 2 else ""
        entries.append({"stem": path.rsplit("/", 1)[-1][: -len(".lrtl")], "core": core,
                        "seconds": parse_runtime(data.get("runtime", "")), "last_played": data.get("last_played")})
    if "@@HISTORY" in out:
        history = re.findall(r'"path":\s*"([^"]+)"', out.split("@@HISTORY", 1)[1])
    return entries, history
