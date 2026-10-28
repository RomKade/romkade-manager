"""Manettes de l'ordinateur lues par le Manager lui-même (et non plus par le navigateur), relayées vers la console.

Le navigateur ne lit plus les manettes dès que l'onglet du Manager est masqué : changer d'onglet coupait la
manette en plein jeu. Ici, un processus à part (app.device.pc_pads_worker, SDL par pygame-ce) lit les manettes
branchées à l'ordinateur en continu, et chaque relais vers la console (app.device.gamepad.Relay, le même que
celui du navigateur) vit dans le serveur : onglet masqué, navigateur réduit ou même fermé, la manette marche.

Sans pygame-ce, ou dans Docker (le conteneur ne voit pas les manettes de l'ordinateur), `available` est faux et
l'interface garde la lecture par le navigateur.
"""

import asyncio
import contextlib
import importlib.util
import json
import logging
import secrets
import string
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app import errors
from app.device.gamepad import Relay
from app.device.ssh_client import DeviceClient

log = logging.getLogger("agm")

MAX_RELAYS = 4
START_SECONDS = 10


@dataclass
class Pad:
    id: int
    name: str
    b: list[float]
    a: list[float]


@dataclass
class RelayState:
    token: str
    pad: int
    name: str
    status: str = "connecting"  # connecting | live | waiting (manette éteinte) | error
    error: str | None = None
    task: asyncio.Task | None = None
    changed: asyncio.Event = field(default_factory=asyncio.Event)


def _token() -> str:
    return "pc" + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))


class PcPads:
    def __init__(self, client_factory: Callable[[], DeviceClient], in_docker: bool | None = None,
                 worker_cmd: list[str] | None = None):
        self.client_factory = client_factory
        self.in_docker = Path("/.dockerenv").exists() if in_docker is None else in_docker
        self.worker_cmd = worker_cmd or [sys.executable, "-u", "-m", "app.device.pc_pads_worker"]
        self.pads: dict[int, Pad] = {}
        self.relays: dict[str, RelayState] = {}
        self.proc: asyncio.subprocess.Process | None = None
        self.reader: asyncio.Task | None = None
        self.ready = asyncio.Event()
        self.reason: str | None = None

    # ---------- lecteur ----------
    @property
    def available(self) -> bool:
        if self.in_docker:
            self.reason = "docker"
            return False
        if importlib.util.find_spec("pygame") is None:
            self.reason = "pygame_missing"
            return False
        return self.reason is None

    async def ensure_started(self) -> None:
        """Lance le lecteur au premier besoin (page Manettes ouverte, relais demandé), puis le garde."""
        if not self.available or (self.proc and self.proc.returncode is None):
            return
        self.ready = asyncio.Event()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *self.worker_cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, cwd=str(Path(__file__).resolve().parents[2]))
        except OSError as exc:
            self.reason = "worker_failed"
            log.warning("lecteur de manettes non lancé : %s", exc)
            return
        self.reader = asyncio.create_task(self._read(self.proc))
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.ready.wait(), START_SECONDS)

    async def _read(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        while line := await proc.stdout.readline():
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("error"):
                self.reason = str(msg["error"])
                self.ready.set()
            elif msg.get("ready"):
                self.ready.set()
            elif isinstance(msg.get("pads"), list):
                self._update(msg["pads"])
        self.pads = {}
        self._notify_all()
        log.info("lecteur de manettes arrêté (code %s)", proc.returncode)

    def _update(self, pads: list[dict]) -> None:
        new = {}
        for p in pads:
            try:
                new[int(p["id"])] = Pad(int(p["id"]), str(p.get("name") or "Manette")[:80],
                                        [float(v) for v in p.get("b", [])][:32], [float(v) for v in p.get("a", [])][:8])
            except (KeyError, TypeError, ValueError):
                continue
        for r in self.relays.values():
            # Manette rallumée : SDL lui donne un nouvel identifiant ; même nom et libre → le relais la reprend.
            if r.pad not in new:
                taken = {x.pad for x in self.relays.values()}
                again = next((p for p in new.values() if p.name == r.name and p.id not in taken), None)
                if again:
                    r.pad = again.id
            if self.pads.get(r.pad) != new.get(r.pad):
                r.changed.set()
        self.pads = new

    def _notify_all(self) -> None:
        for r in self.relays.values():
            r.changed.set()

    async def stop(self) -> None:
        for token in list(self.relays):
            await self.stop_relay(token)
        if self.proc and self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.proc.wait(), 3)
        if self.reader:
            self.reader.cancel()

    # ---------- relais vers la console ----------
    async def start_relay(self, pad_id: int) -> RelayState:
        await self.ensure_started()
        pad = self.pads.get(pad_id)
        if pad is None:
            raise errors.AppError("pc_pad_missing", "Cette manette n'est plus connectée à l'ordinateur.", 404)
        if any(r.pad == pad_id for r in self.relays.values()):
            raise errors.AppError("pc_pad_busy", "Cette manette pilote déjà la console.", 409)
        if len(self.relays) >= MAX_RELAYS:
            raise errors.AppError("gamepad_too_many", f"Déjà {MAX_RELAYS} manettes relayées vers la console.", 409)
        r = RelayState(_token(), pad_id, pad.name)
        self.relays[r.token] = r
        started = asyncio.get_running_loop().create_future()
        r.task = asyncio.create_task(self._run(r, started))
        try:
            await started
        except errors.AppError:
            self.relays.pop(r.token, None)
            raise
        return r

    async def _run(self, r: RelayState, started: asyncio.Future) -> None:
        try:
            async with Relay(self.client_factory(), r.token) as relay:
                r.status = "live"
                started.set_result(True)
                while True:
                    pad = self.pads.get(r.pad)
                    if pad is None:
                        relay.release()  # manette éteinte : rien ne reste appuyé sur la console
                        r.status = "waiting"
                    else:
                        relay.send(pad.b, pad.a)
                        r.status = "live"
                    r.changed.clear()
                    await r.changed.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — console injoignable, connexion perdue
            err = exc if isinstance(exc, errors.AppError) else errors.AppError(
                "gamepad_relay_lost", "Connexion à la console perdue.", 502, {"reason": str(exc)})
            if not started.done():
                started.set_exception(err)
            r.status, r.error = "error", err.message
            log.info("relais de manette %s arrêté : %s", r.token, err.message)
        finally:
            if self.relays.get(r.token) is r and r.status != "error":
                self.relays.pop(r.token, None)

    async def stop_relay(self, token: str) -> None:
        r = self.relays.pop(token, None)
        if r and r.task:
            r.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await r.task

    def snapshot(self) -> dict:
        return {
            "available": self.available, "reason": self.reason,
            "pads": [{"id": p.id, "name": p.name, "relayed": any(r.pad == p.id for r in self.relays.values())}
                     for p in self.pads.values()],
            "relays": [{"token": r.token, "pad": r.pad, "name": r.name, "status": r.status, "error": r.error}
                       for r in self.relays.values()],
        }
