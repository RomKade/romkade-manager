"""Relais entre le MCP et les consoles.

La console n'est pas joignable depuis Internet (derrière la box) : c'est son agent qui vient chercher les ordres.
Il interroge GET /agent/poll en continu (« long polling » : la requête reste ouverte jusqu'à ce qu'un ordre arrive
ou ~25 s), exécute l'ordre et renvoie le résultat par POST /agent/result. Une requête HTTPS sortante ordinaire passe
par toutes les box et tous les pare-feu, sans rien configurer.

Prototype : un seul processus, ordres en mémoire. Plusieurs serveurs demanderont une file partagée (Redis…).
"""

import asyncio
import secrets
import time
from dataclasses import dataclass, field

ONLINE_WITHIN = 45.0  # une console qui n'a pas interrogé le relais depuis ce délai est hors ligne (veille, éteinte)


class ConsoleOffline(Exception):
    pass


class CommandTimeout(Exception):
    pass


class CommandFailed(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class _Pending:
    console_id: str
    action: str
    params: dict
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    id: str = field(default_factory=lambda: secrets.token_hex(8))


class Relay:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[_Pending]] = {}
        self._waiting: dict[str, _Pending] = {}  # ordres envoyés à une console, en attente de son résultat
        self._last_poll: dict[str, float] = {}

    def _queue(self, console_id: str) -> asyncio.Queue[_Pending]:
        return self._queues.setdefault(console_id, asyncio.Queue())

    def online(self, console_id: str) -> bool:
        return time.time() - self._last_poll.get(console_id, 0) < ONLINE_WITHIN

    def last_poll(self, console_id: str) -> float | None:
        return self._last_poll.get(console_id)

    async def call(self, console_id: str, action: str, params: dict | None = None, timeout: float = 45) -> dict:
        """Envoie un ordre à la console et attend son résultat."""
        if not self.online(console_id):
            raise ConsoleOffline(console_id)
        pending = _Pending(console_id, action, params or {})
        await self._queue(console_id).put(pending)
        try:
            reply = await asyncio.wait_for(asyncio.shield(pending.future), timeout)
        except TimeoutError as exc:
            raise CommandTimeout(action) from exc
        finally:
            self._waiting.pop(pending.id, None)
            if not pending.future.done():
                pending.future.cancel()
        if not reply.get("ok"):
            err = reply.get("error") or {}
            raise CommandFailed(str(err.get("code") or "failed"), str(err.get("message") or "The console failed."))
        return reply.get("result") or {}

    async def poll(self, console_id: str, wait: float = 25) -> dict | None:
        """Prochain ordre pour cette console, ou None au bout de `wait` secondes."""
        self._last_poll[console_id] = time.time()
        queue = self._queue(console_id)
        deadline = time.monotonic() + wait
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            try:
                pending = await asyncio.wait_for(queue.get(), left)
            except TimeoutError:
                return None
            finally:
                self._last_poll[console_id] = time.time()
            if pending.future.done():  # l'appelant a abandonné (délai dépassé) : on ne l'exécute pas
                continue
            self._waiting[pending.id] = pending
            return {"id": pending.id, "action": pending.action, "params": pending.params}

    def result(self, console_id: str, command_id: str, reply: dict) -> bool:
        pending = self._waiting.get(command_id)
        if pending is None or pending.console_id != console_id or pending.future.done():
            return False
        self._last_poll[console_id] = time.time()
        pending.future.set_result(reply)
        return True
