#!/usr/bin/env python3
"""Agent ROMKADE : relie la console au cloud ROMKADE, pour la piloter depuis ChatGPT, Claude…

Tourne sur la console (Python 3.10+, bibliothèque standard seule). C'est lui qui appelle le cloud, par HTTPS
sortant : rien à ouvrir sur la box, pas d'adresse IP à connaître, pas de SSH.

- Au démarrage : se présente (modèle, firmware), reçoit la première fois un secret (gardé dans agent.json) et,
  tant que la console n'est liée à aucun compte, un code d'appairage (écrit dans /tmp pour l'app ROMKADE).
- Envoie la liste des fichiers du dossier des ROMs (noms et tailles seulement), puis de nouveau si elle change.
- Attend les ordres (long polling) et n'exécute que ceux de la liste ACTIONS : jamais de commande libre venue
  du réseau. Les commandes de la console sont celles du Manager (vendor/app/device : launcher, volume, systems).
"""

import asyncio
import gzip
import hashlib
import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "vendor"))

from app import errors  # noqa: E402
from app.device import launcher, systems, volume  # noqa: E402

VERSION = "0.1.0"
CONFIG = HERE / "agent.json"            # {"server": "https://…", "secret": "…"} (sur la carte : survit au redémarrage)
STATUS = Path("/tmp/romkade-status.json")  # état lu par l'app ROMKADE (RomKade.sh) pour l'écran de la console
LOG = Path("/tmp/romkade-agent.log")
PIDFILE = Path("/tmp/romkade-agent.pid")
POLL_WAIT = 25
RESCAN_EVERY = 600
SKIP_DIRS = {"imgs", "images", "videos", "manuals", "media", "snap", "snaps", "screenshots", "titles", "marquees",
             "wheel", "boxart", "box2dfront", "thumbnails", "downloaded_images", "downloaded_videos"}
MAX_DEPTH = 3

log = logging.getLogger("romkade")


class Unauthorized(Exception):
    pass


class Client:
    """Tient lieu du DeviceClient (SSH) du Manager : ici, les commandes tournent sur la console même."""

    def __init__(self) -> None:
        # Même forme que DeviceSettings : launcher lit settings.roms_root.
        self.settings = SimpleNamespace(roms_root="/mnt/mmc/Roms")


async def run_local(_client, command: str, timeout: float = 20) -> tuple[int, str]:
    """Runner du Manager (launcher.Runner), exécuté par bash sur la console au lieu de SSH."""
    proc = await asyncio.create_subprocess_exec("bash", "-c", command, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise errors.AppError("device_command_timeout", f"La console n'a pas répondu à temps ({timeout:.0f} s).", 504)
    return proc.returncode or 0, out.decode("utf-8", "replace")


# ---------- configuration ----------
def load_config() -> dict:
    return json.loads(CONFIG.read_text())


def save_config(cfg: dict) -> None:
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=1))
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG)


def write_status(**status) -> None:
    """Complète l'état lu par l'écran de l'app ROMKADE (screen.py)."""
    try:
        STATUS.write_text(json.dumps({**_read_status(), **status, "at": time.time()}))
    except OSError:
        pass


# ---------- HTTP ----------
def _request(cfg: dict, method: str, path: str, body=None, timeout: float = 30, compress: bool = False):
    data = None
    headers = {"User-Agent": f"romkade-agent/{VERSION}", "Accept": "application/json",
               "ngrok-skip-browser-warning": "1"}
    if cfg.get("secret"):
        headers["Authorization"] = f"Bearer {cfg['secret']}"
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
        if compress:
            data = gzip.compress(data)
            headers["Content-Encoding"] = "gzip"
    req = urllib.request.Request(cfg["server"].rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise Unauthorized() from exc
        raise


async def http(cfg: dict, method: str, path: str, body=None, timeout: float = 30, compress: bool = False):
    return await asyncio.to_thread(_request, cfg, method, path, body, timeout, compress)


# ---------- catalogue ----------
def scan(root: str) -> list[list]:
    """[[dossier de plateforme, chemin relatif, taille], …] : noms et tailles seulement."""
    files: list[list] = []
    try:
        platforms = sorted(os.listdir(root))
    except OSError:
        return files
    for d in platforms:
        base = os.path.join(root, d)
        if d.startswith(".") or not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            depth = 0 if dirpath == base else dirpath[len(base) + 1:].count("/") + 1
            dirnames[:] = [x for x in dirnames if not x.startswith(".") and x.lower() not in SKIP_DIRS
                           and depth < MAX_DEPTH]
            for f in filenames:
                if f.startswith("."):
                    continue
                full = os.path.join(dirpath, f)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                files.append([d, os.path.relpath(full, base), size])
    return files


# ---------- l'agent ----------
class Agent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.client = Client()
        self.profile = systems.PROFILES[systems.DEFAULT_PROFILE]
        self.detection = None
        self.catalog_digest = None
        self.catalog_at = 0.0
        self.device_lock = asyncio.Lock()  # un ordre à la fois sur la console

    @property
    def roms_root(self) -> str:
        return self.client.settings.roms_root

    async def detect(self) -> None:
        try:
            self.detection = await systems.detect(run_local, self.client)
            self.profile = systems.PROFILES[self.detection.profile]
            root = systems.suggested_root(self.profile, self.detection.roms_roots)
            if root:
                self.client.settings.roms_root = root
        except Exception as exc:  # noqa: BLE001
            log.warning("détection du firmware impossible : %s", exc)

    def info(self) -> dict:
        def first_line(p: str) -> str | None:
            try:
                return Path(p).read_text(errors="replace").split()[0].strip() or None
            except (OSError, IndexError):
                return None

        model = first_line("/mnt/vendor/oem/board.ini") or first_line("/proc/device-tree/model")
        firmware = self.profile.label
        if v := first_line("/mnt/vendor/oem/version.ini"):
            firmware += f" ({v[:8]})"
        caps = self.profile.capabilities(bool(self.detection and self.detection.es_http))
        return {"agent_version": VERSION, "hostname": socket.gethostname(), "model": model, "firmware": firmware,
                "profile": self.profile.id, "os_name": self.detection.os_name if self.detection else None,
                "roms_root": self.roms_root,
                "capabilities": {k: caps[k] for k in ("launch", "resume_slot", "quit", "save_state", "volume")}}

    async def hello(self) -> dict:
        try:
            r = await http(self.cfg, "POST", "/agent/hello", self.info())
        except Unauthorized:
            log.warning("secret refusé par le cloud (console supprimée ?) : nouvel enregistrement")
            self.cfg.pop("secret", None)
            save_config(self.cfg)
            r = await http(self.cfg, "POST", "/agent/hello", self.info())
        if r.get("secret"):
            self.cfg["secret"] = r["secret"]
            save_config(self.cfg)
        expires = r.get("pairing_expires_in")
        write_status(paired=r.get("paired", False), code=r.get("pairing_code"), name=r.get("name"), online=True,
                     code_until=time.time() + expires if expires else None)
        log.info("connecté au cloud : console %s, %s", r.get("console_id"),
                 "appairée" if r.get("paired") else f"code d'appairage {r.get('pairing_code')}")
        return r

    async def sync_catalog(self, force: bool = False) -> None:
        files = await asyncio.to_thread(scan, self.roms_root)
        digest = hashlib.sha256(json.dumps(files).encode()).hexdigest()
        if digest == self.catalog_digest and not force:
            return
        r = await http(self.cfg, "POST", "/agent/catalog", {"files": files}, timeout=120, compress=True)
        self.catalog_digest = digest
        write_status(games=r.get("games"))
        log.info("catalogue envoyé : %s fichiers, %s jeux", len(files), r.get("games"))

    # ---------- ordres ----------
    def rom_path(self, platform_dir: str, relative_path: str) -> str:
        """Chemin complet d'un jeu, refusé s'il sort du dossier des ROMs ou n'existe pas."""
        if not platform_dir or "/" in platform_dir or platform_dir.startswith("."):
            raise errors.AppError("bad_path", "Jeu invalide.", 422)
        root = os.path.realpath(self.roms_root)
        full = os.path.realpath(os.path.join(root, platform_dir, relative_path))
        if not full.startswith(root + "/") or not os.path.isfile(full):
            raise errors.AppError("not_on_card", "Ce jeu n'est plus sur la carte de la console.", 409)
        return full

    def split_rom(self, rom: str | None) -> tuple[str | None, str | None]:
        root = os.path.realpath(self.roms_root) + "/"
        if not rom or not rom.startswith(root):
            return None, None
        platform_dir, _, rel = rom[len(root):].partition("/")
        return platform_dir, rel

    async def do_status(self, _p: dict) -> dict:
        st = await launcher.status(run_local, self.client, self.profile)
        platform_dir, rel = self.split_rom(st.get("rom_path"))
        out = {"playing": st["playing"], "menu": st.get("menu"), "process": st.get("process"),
               "platform_dir": platform_dir, "relative_path": rel}
        if self.profile.capabilities()["volume"]:
            v = await volume.status(run_local, self.client)
            out["volume"] = {"percent": v["percent"], "muted": v["muted"], "adjustable": v["adjustable"]}
        return out

    async def do_launch(self, p: dict) -> dict:
        rom = self.rom_path(str(p.get("platform_dir") or ""), str(p.get("relative_path") or ""))
        slot = p.get("slot")
        await launcher.launch(run_local, self.client, p["platform_dir"], rom, str(slot) if slot else None,
                              self.profile)
        return {"launching": rom}

    async def do_quit(self, _p: dict) -> dict:
        return {"result": await launcher.quit_game(run_local, self.client, self.profile)}

    async def do_save_state(self, _p: dict) -> dict:
        if not self.profile.capabilities()["save_state"]:
            raise errors.AppError("save_state_unsupported", "Sauvegarde à distance impossible sur ce firmware : "
                                  "utilise le raccourci de la console.", 409)
        st = await launcher.status(run_local, self.client, self.profile)
        if not st["playing"] or st["process"] != "retroarch":
            raise errors.AppError("no_retroarch_game", "Aucun jeu RetroArch en cours sur la console.", 409)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(b"SAVE_STATE", ("127.0.0.1", 55355))
        return {"saved": True}

    async def do_volume(self, p: dict) -> dict:
        percent = p.get("percent")
        muted = p.get("muted")
        v = await volume.set_volume(run_local, self.client, int(percent) if percent is not None else None,
                                    bool(muted) if muted is not None else None)
        return {"percent": v["percent"], "muted": v["muted"]}

    async def do_rescan(self, _p: dict) -> dict:
        await self.sync_catalog(force=True)
        return {"rescanned": True}

    ACTIONS = {"status": do_status, "launch": do_launch, "quit": do_quit, "save_state": do_save_state,
               "volume": do_volume, "rescan": do_rescan}

    async def handle(self, command: dict) -> None:
        action = command.get("action")
        params = command.get("params") or {}
        handler = self.ACTIONS.get(action)
        try:
            if handler is None:
                raise errors.AppError("unknown_action", f"Action inconnue : {action}", 400)
            async with self.device_lock:
                result = await handler(self, params)
            reply = {"id": command.get("id"), "ok": True, "result": result}
        except errors.AppError as exc:
            reply = {"id": command.get("id"), "ok": False, "error": {"code": exc.code, "message": exc.message}}
        except Exception as exc:  # noqa: BLE001
            log.exception("ordre %s en échec", action)
            reply = {"id": command.get("id"), "ok": False, "error": {"code": "agent_error", "message": str(exc)}}
        log.info("ordre %s : %s", action, "ok" if reply["ok"] else reply["error"]["code"])
        try:
            await http(self.cfg, "POST", "/agent/result", reply)
        except Exception as exc:  # noqa: BLE001
            log.warning("résultat non envoyé : %s", exc)

    async def run(self) -> None:
        await self.detect()
        backoff = 2
        while True:
            try:
                await self.hello()
                await self.sync_catalog(force=True)
                last_scan = time.time()
                backoff = 2
                while True:
                    r = await http(self.cfg, "GET", f"/agent/poll?wait={POLL_WAIT}", timeout=POLL_WAIT + 15)
                    if r.get("command"):
                        asyncio.ensure_future(self.handle(r["command"]))
                    elif r.get("resync"):
                        await self.sync_catalog(force=True)  # le cloud n'a plus la liste (mise à jour du serveur)
                    elif "paired" in r:
                        status = _read_status()
                        if status.get("paired") != r["paired"]:
                            await self.hello()  # appairée (ou détachée) depuis : l'écran de l'app suit
                        elif not r["paired"] and (status.get("code_until") or 0) < time.time() + 30:
                            await self.hello()  # code bientôt expiré : le cloud en donne un nouveau
                    if time.time() - last_scan > RESCAN_EVERY:
                        last_scan = time.time()
                        await self.sync_catalog()
            except Exception as exc:  # noqa: BLE001 — Wi-Fi coupé (veille), cloud indisponible… : on réessaie
                log.warning("cloud injoignable (%s) : nouvel essai dans %s s", exc, backoff)
                write_status(**{**_read_status(), "online": False})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)


def _read_status() -> dict:
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {}


def already_running() -> bool:
    try:
        pid = int(PIDFILE.read_text())
        return pid != os.getpid() and "romkade_agent" in Path(f"/proc/{pid}/cmdline").read_text(errors="replace")
    except (OSError, ValueError):
        return False


def main() -> None:
    if already_running():
        print("agent déjà lancé")
        return
    PIDFILE.write_text(str(os.getpid()))
    if LOG.exists() and LOG.stat().st_size > 1_000_000:
        LOG.write_text("")
    logging.basicConfig(filename=str(LOG), level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(Agent(load_config()).run())


if __name__ == "__main__":
    main()
