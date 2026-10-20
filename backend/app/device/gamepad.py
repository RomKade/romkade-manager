"""Manette de l'ordinateur : une manette connectée à l'ordinateur pilote la console, par le Wi-Fi.

Le Bluetooth de certaines manettes (Xbox) porte trop court pour la console : la manette reste connectée à
l'ordinateur (Mac, Windows, Linux) ou au téléphone, l'interface lit ses appuis (API Gamepad du navigateur, disposition « standard ») et les envoie par
WebSocket (api/gamepad.py). Ce module les traduit en événements evdev d'une manette Xbox 360 et les passe à
gamepad_relay.py, qui tourne sur la console (une connexion SSH dédiée par manette, ouverte le temps du relais) et
y crée une manette virtuelle que RetroArch reconnaît comme une vraie.
"""

import asyncio
import re
import shlex
from contextlib import AsyncExitStack
from pathlib import Path

import asyncssh

from app import errors
from app.device.ssh_client import DeviceClient

RELAY_SCRIPT = (Path(__file__).parent / "gamepad_relay.py").read_text()
TOKEN_RE = re.compile(r"^[a-z0-9]{4,16}$")  # identifiant du relais, choisi par l'interface (voir players.py)
READY_SECONDS = 10

EV_KEY, EV_ABS = 1, 3
# Bouton de la disposition standard (navigateur) → touche evdev de xpad.
BUTTONS = {0: 304, 1: 305, 2: 307, 3: 308, 4: 310, 5: 311, 8: 314, 9: 315, 10: 317, 11: 318, 16: 316}
TRIGGERS = {6: 2, 7: 5}  # gâchettes LT / RT → ABS_Z / ABS_RZ (0 à 255)
STICKS = {0: 0, 1: 1, 2: 3, 3: 4}  # axes standard → ABS_X, ABS_Y, ABS_RX, ABS_RY (vers le bas = positif, des deux côtés)
HAT_X, HAT_Y = 16, 17
DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT = 12, 13, 14, 15
PRESSED = 0.5


def to_events(buttons: list[float], axes: list[float]) -> dict[tuple[int, int], int]:
    """État complet de la manette virtuelle (type, code) → valeur, d'après l'état lu par le navigateur."""
    def b(i: int) -> float:
        return float(buttons[i]) if i < len(buttons) else 0.0

    state: dict[tuple[int, int], int] = {(EV_KEY, code): int(b(i) >= PRESSED) for i, code in BUTTONS.items()}
    for i, code in TRIGGERS.items():
        state[(EV_ABS, code)] = round(min(1.0, max(0.0, b(i))) * 255)
    for i, code in STICKS.items():
        v = float(axes[i]) if i < len(axes) else 0.0
        state[(EV_ABS, code)] = round(min(1.0, max(-1.0, v)) * 32767)
    state[(EV_ABS, HAT_X)] = (b(DPAD_RIGHT) >= PRESSED) - (b(DPAD_LEFT) >= PRESSED)
    state[(EV_ABS, HAT_Y)] = (b(DPAD_DOWN) >= PRESSED) - (b(DPAD_UP) >= PRESSED)
    return state


def changes(before: dict[tuple[int, int], int], after: dict[tuple[int, int], int]) -> str:
    """Ligne pour gamepad_relay.py : les valeurs qui ont changé (« type,code,valeur » séparés par des espaces)."""
    return " ".join(f"{t},{c},{v}" for (t, c), v in sorted(after.items()) if before.get((t, c)) != v)


class Relay:
    """Une manette virtuelle sur la console, le temps d'une connexion WebSocket."""

    def __init__(self, client: DeviceClient, token: str):
        if not TOKEN_RE.match(token):
            raise errors.AppError("gamepad_token_invalid", "Identifiant de manette invalide.", 422, {"token": token})
        self.client = client
        self.command = f"python3 -u -c {shlex.quote(RELAY_SCRIPT)} {token}"
        self.state = to_events([], [])
        self._stack = AsyncExitStack()
        self._proc: asyncssh.SSHClientProcess | None = None

    async def __aenter__(self) -> "Relay":
        try:
            conn = await self._stack.enter_async_context(self.client.connect())
            self._proc = await conn.create_process(self.command)
            line = await asyncio.wait_for(self._proc.stdout.readline(), READY_SECONDS)
            if line.strip() != "ready":
                err = (await asyncio.wait_for(self._proc.stderr.read(), 2)).strip()
                raise errors.AppError("gamepad_relay_failed", "La console n'a pas pu créer la manette virtuelle.",
                                      502, {"stderr": err[-500:]})
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._proc is not None:
            try:
                self._proc.stdin.write_eof()  # gamepad_relay.py retire la manette
                await asyncio.wait_for(self._proc.wait(), 3)
            except (OSError, asyncssh.Error, asyncio.TimeoutError):
                pass
        await self._stack.aclose()

    def send(self, buttons: list[float], axes: list[float]) -> None:
        after = to_events(buttons, axes)
        line = changes(self.state, after)
        self.state = after
        if line and self._proc is not None:
            self._proc.stdin.write(line + "\n")

    def release(self) -> None:
        """Relâche tout (manette déconnectée du Mac, onglet masqué) : rien ne reste appuyé sur la console."""
        self.send([], [])
