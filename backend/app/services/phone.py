"""Le Manager sur le téléphone, par un QR code, sur le Wi-Fi de la maison.

Le serveur n'écoute que sur 127.0.0.1. Quand on affiche le QR code, un second serveur s'ouvre sur l'adresse de
l'ordinateur dans le réseau local (même application, même port), derrière `PhoneGate` : il n'accepte que les
téléphones associés. Le QR code porte un jeton à usage unique, valable quelques minutes ; le téléphone qui l'ouvre
reçoit un cookie de session (gardé `SESSION_DAYS` jours, haché sur le disque, retiré par « Déconnecter »). Le
téléphone associé ouvre le Manager sans l'écran de connexion au compte : sa vérification anti-robot (Turnstile)
n'est autorisée que sur localhost et romkade.com, et c'est l'ordinateur connecté qui l'a associé.

Ce second serveur se rouvre au lancement tant qu'un téléphone est associé, et se ferme quand on les déconnecte.
Pas dans Docker : le conteneur ne voit pas l'adresse de l'ordinateur sur le réseau local.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import secrets
import socket
import time
from html import escape
from http.cookies import SimpleCookie
from pathlib import Path

import segno
import uvicorn
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import errors

log = logging.getLogger("agm")

PAIR_TTL = 300
SESSION_DAYS = 90
COOKIE = "romkade_phone"
DEVICE_COOKIE = "romkade_device"  # lisible par l'interface : « phone » → pas d'écran de connexion au compte
PATH = "/telephone/"


def lan_ip() -> str | None:
    """Adresse de l'ordinateur sur le réseau local (celle de la route par défaut ; aucun paquet n'est envoyé)."""
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
        if not ip.startswith(("127.", "0.")):
            return ip
    return None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _Server(uvicorn.Server):
    """Serveur du réseau local dans la boucle du serveur principal : il ne prend pas ses signaux (Ctrl+C)."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


class PhoneAccess:
    def __init__(self, path: Path, in_docker: bool | None = None):
        self.path = path
        self.in_docker = Path("/.dockerenv").exists() if in_docker is None else in_docker
        self.pending: dict[str, float] = {}  # jeton haché → fin de validité
        self.app: ASGIApp | None = None  # l'application à servir, posée par create_app
        self.server: _Server | None = None
        self.task: asyncio.Task | None = None
        self.bound: tuple[str, int] | None = None

    # ---------- sessions (sur le disque) ----------
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        now = time.time()
        data["sessions"] = {k: v for k, v in data.get("sessions", {}).items() if v.get("until", 0) > now}
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def devices(self) -> int:
        return len(self._load()["sessions"])

    def valid(self, sid: str | None) -> bool:
        return bool(sid) and _hash(sid) in self._load()["sessions"]

    def redeem(self, token: str) -> str | None:
        """Jeton du QR code → nouvelle session (le jeton ne resert pas)."""
        until = self.pending.pop(_hash(token), 0)
        if until < time.time():
            return None
        sid = secrets.token_urlsafe(32)
        data = self._load()
        data["sessions"][_hash(sid)] = {"since": time.time(), "until": time.time() + SESSION_DAYS * 86400}
        self._save(data)
        return sid

    # ---------- QR code ----------
    async def pair(self, port: int) -> dict:
        if self.in_docker:
            raise errors.AppError("phone_docker", "Avec Docker, le Manager ne s'ouvre pas encore sur le téléphone : "
                                  "lance-le avec ./run.sh pour cela.", 409)
        ip = lan_ip()
        if not ip:
            raise errors.AppError("phone_no_network", "Cet ordinateur n'est relié à aucun réseau local (Wi-Fi).", 409)
        await self.listen(ip, port)
        now = time.time()
        self.pending = {k: v for k, v in self.pending.items() if v > now}
        token = secrets.token_urlsafe(24)
        self.pending[_hash(token)] = now + PAIR_TTL
        data = self._load()
        data["port"] = port
        self._save(data)
        url = f"http://{ip}:{port}{PATH}{token}"
        qr = segno.make(url, error="m").svg_data_uri(scale=6, border=2, dark="#05101f", light="#ffffff")
        return {"url": url, "qr": qr, "expires_in": PAIR_TTL, "devices": self.devices()}

    def status(self) -> dict:
        return {"devices": self.devices(), "listening": self.bound is not None, "available": not self.in_docker}

    async def disconnect(self) -> None:
        self.pending.clear()
        data = self._load()
        data["sessions"] = {}
        self._save(data)
        await self.stop()

    # ---------- serveur du réseau local ----------
    async def listen(self, ip: str, port: int) -> None:
        if self.bound == (ip, port) and self.task and not self.task.done():
            return
        await self.stop()
        assert self.app is not None
        fail = errors.AppError("phone_listen_failed", f"Impossible d'ouvrir le Manager sur le réseau local ({ip}:{port}).",
                               500)
        # Socket ouverte ici : uvicorn, lui, quitte le processus (sys.exit) s'il ne peut pas l'ouvrir.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((ip, port))
        except OSError as exc:
            sock.close()
            raise fail from exc
        self.server = _Server(uvicorn.Config(PhoneGate(self.app, self), host=ip, port=port, lifespan="off",
                                             log_level="warning"))
        self.task = asyncio.create_task(self.server.serve(sockets=[sock]))
        for _ in range(50):
            if self.server.started or self.task.done():
                break
            await asyncio.sleep(0.05)
        if not self.server.started:
            await self.stop()
            sock.close()
            raise fail
        self.bound = (ip, port)
        log.info("Manager ouvert au téléphone sur http://%s:%s", ip, port)

    async def resume(self) -> None:
        """Au lancement : rouvre le serveur du réseau local si un téléphone est associé."""
        data = self._load()
        ip = lan_ip()
        if self.in_docker or not data["sessions"] or not ip:
            return
        with contextlib.suppress(errors.AppError):
            await self.listen(ip, data.get("port", 8765))

    async def stop(self) -> None:
        if self.server and self.task:
            self.server.should_exit = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.task, 5)
        self.server = self.task = self.bound = None


def _page(title: str, text: str, status: int) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>ROMKADE</title><body style='margin:0;min-height:100vh;display:grid;place-items:center;"
        "background:#050c1c;color:#f5f8ff;font:17px/1.5 system-ui,sans-serif;text-align:center;padding:24px'>"
        f"<div><h1 style='font-size:22px;margin:0 0 8px'>{escape(title)}</h1>"
        f"<p style='color:#a9bdd3;margin:0'>{escape(text)}</p></div>", status_code=status)


class PhoneGate:
    """Devant le serveur du réseau local : ouvre la session du QR code, puis ne laisse passer que les téléphones
    associés (marqués dans le scope pour LocalOnlyMiddleware)."""

    def __init__(self, app: ASGIApp, access: PhoneAccess):
        self.app = app
        self.access = access

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith(PATH):
            return await self._pair(path[len(PATH):], scope, receive, send)
        cookies = SimpleCookie()
        for k, v in scope.get("headers", []):
            if k == b"cookie":
                with contextlib.suppress(Exception):
                    cookies.load(v.decode("latin-1"))
        sid = cookies[COOKIE].value if COOKIE in cookies else None
        if not self.access.valid(sid):
            if scope["type"] == "websocket":
                await receive()
                return await send({"type": "websocket.close", "code": 1008})
            return await _page("Téléphone non associé", "Scanne le QR code affiché par le Manager sur ton ordinateur "
                               "(bouton téléphone, en haut).", 403)(scope, receive, send)
        return await self.app({**scope, "romkade_phone": True}, receive, send)

    async def _pair(self, token: str, scope: Scope, receive: Receive, send: Send) -> None:
        sid = self.access.redeem(token)
        if not sid:
            return await _page("QR code expiré", "Il ne sert qu'une fois et quelques minutes : affiches-en un nouveau "
                               "dans le Manager, sur ton ordinateur.", 403)(scope, receive, send)
        resp = RedirectResponse("/", status_code=303)
        age = SESSION_DAYS * 86400
        resp.set_cookie(COOKIE, sid, max_age=age, httponly=True, samesite="lax")
        resp.set_cookie(DEVICE_COOKIE, "phone", max_age=age, samesite="lax")
        await resp(scope, receive, send)
