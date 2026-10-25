"""Relier la console à ROMKADE Cloud depuis le Manager, sans code d'appairage : installation de l'agent ROMKADE.

L'agent (cloud/agent du dépôt) tourne sur la console et appelle mcp.romkade.com en HTTPS sortant : ChatGPT, Claude…
pilotent alors la console, et le Manager voit les mêmes consoles que le compte ROMKADE.

Étapes, à la demande de l'utilisateur connecté :
1. le cloud enregistre la console sur son compte (jeton de session Supabase) et renvoie le secret de son agent ;
2. le Manager copie l'agent par SFTP (dossier « romkade » à côté du dossier des ROMs, app « ROMKADE » dans APPS),
   écrit agent.json (adresse du cloud + secret, lisible par root seul), ajoute le démarrage automatique et lance
   l'agent. L'agent embarque les modules de pilotage du Manager (launcher, volume, systems), exécutés sur place.

Le Manager pose aussi à côté de l'agent les favoris de la console (favorites.json) : l'agent les envoie au cloud.

Seul le firmware Anbernic + Stock OS Mod est pris en charge (Python 3, menu APPS, script de démarrage du mod).
Écriture hors du dossier des ROMs, et dans APPS : exception voulue à remote_writer, limitée aux fichiers listés ici.
"""

import asyncio
import hashlib
import json
import logging
import os
import shlex
import time
from pathlib import Path

import httpx

from app import errors

log = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parents[1]                  # backend/app
REPO = APP_DIR.parents[1]                                       # racine du dépôt (installation depuis les sources)
CLOUD_URL = os.environ.get("ROMKADE_CLOUD_URL", "https://mcp.romkade.com").rstrip("/")
SUPPORTED = {"anbernic-stock-mod"}
AUTOSTART = "/mnt/mod/ctrl/autostart"
MARK = "# ROMKADE"
APP_NAME = "ROMKADE - Played from Anywhere"  # nom de l'app dans le menu APPS de la console (nom du fichier)
OLD_APP_NAMES = ("ROMKADE",)  # anciens noms, effacés à l'installation
# Modules du Manager exécutés sur la console : tout ce qu'ils importent de app (même dans une fonction) doit y être,
# sinon l'app ROMKADE échoue au premier appel (test_bundle_covers_every_app_import).
VENDOR = ("__init__.py", "errors.py", "platforms.py")
VENDOR_SERVICES = ("__init__.py", "saves.py")  # sauvegardes de la carte, lues sur place (outil game_details)
VENDOR_DEVICE = ("__init__.py", "launcher.py", "volume.py", "systems.py", "bluetooth.py", "launch.sh", "onion_launch.sh",
                 "players_apply.sh", "volume_keys.py")


def manager_version() -> str:
    """Version du Manager qui installe l'app : devient celle de l'app sur la console (fichier VERSION)."""
    try:
        from importlib.metadata import version
        return version("anbernic-game-manager")
    except Exception:  # noqa: BLE001 — sources non installées
        return "dev"


UPDATE_EVERY = 3600  # secondes : vérification de la version de l'app au plus une fois par heure et par console
_updates: dict[str, float] = {}  # dernière vérification, par console (hôte)
_build: str | None = None


def build_id() -> str:
    """Empreinte des fichiers de l'app que ce Manager installe : change à chaque modification de l'app, même sans
    nouveau numéro de version. Écrite sur la console (BUILD) : une autre empreinte = mise à jour à faire."""
    global _build
    if _build is None:
        files = bundle("/mnt/mmc/Roms", with_build=False)
        h = hashlib.sha256()
        for path in sorted(files):
            h.update(path.encode() + b"\0" + files[path][0] + b"\0")
        _build = h.hexdigest()[:12]
    return _build


def agent_source() -> Path:
    """Dossier de l'agent : ROMKADE_AGENT_DIR (image Docker), sinon cloud/agent du dépôt."""
    path = Path(os.environ.get("ROMKADE_AGENT_DIR") or REPO / "cloud" / "agent")
    if not (path / "romkade_agent.py").is_file():
        raise errors.AppError("agent_missing", "App ROMKADE pour console introuvable dans cette installation du Manager.", 500)
    return path


def bundle(roms_root: str, with_build: bool = True) -> dict[str, tuple[bytes, int]]:
    """{chemin sur la console: (contenu, droits)} de l'agent, de son écran et de l'app du menu APPS."""
    src = agent_source()
    base = roms_root.rstrip("/").rsplit("/", 1)[0] + "/romkade"
    files: dict[str, tuple[bytes, int]] = {}
    for name, mode in (("romkade_agent.py", 0o755), ("screen.py", 0o755), ("splash.sh", 0o755), ("start.sh", 0o755),
                       ("uninstall.sh", 0o755)):
        files[f"{base}/{name}"] = ((src / name).read_bytes(), mode)
    for asset in sorted((src / "assets").iterdir()):
        if asset.is_file() and asset.name != "apps-icon.png":
            files[f"{base}/assets/{asset.name}"] = (asset.read_bytes(), 0o644)
    for stub in sorted((src / "stubs").rglob("*.py")):
        files[f"{base}/vendor/{stub.relative_to(src / 'stubs')}"] = (stub.read_bytes(), 0o644)
    for name in VENDOR:
        files[f"{base}/vendor/app/{name}"] = ((APP_DIR / name).read_bytes(), 0o644)
    for name in VENDOR_SERVICES:
        files[f"{base}/vendor/app/services/{name}"] = ((APP_DIR / "services" / name).read_bytes(), 0o644)
    for name in VENDOR_DEVICE:
        files[f"{base}/vendor/app/device/{name}"] = ((APP_DIR / "device" / name).read_bytes(), 0o644)
    for legal in ("LICENSE", "NOTICE"):  # à la racine du dépôt (ou de /app dans l'image Docker)
        path = src.parents[1] / legal
        if path.is_file():
            files[f"{base}/{legal}"] = (path.read_bytes(), 0o644)
    files[f"{base}/VERSION"] = (manager_version().encode() + b"\n", 0o644)
    if with_build:
        files[f"{base}/BUILD"] = (build_id().encode() + b"\n", 0o644)
    apps = roms_root.rstrip("/") + "/APPS"
    files[f"{apps}/{APP_NAME}.sh"] = ((src / "RomKade.sh").read_bytes(), 0o755)
    files[f"{apps}/Imgs/{APP_NAME}.png"] = ((src / "assets" / "apps-icon.png").read_bytes(), 0o644)
    return files


def agent_dir(roms_root: str) -> str:
    return roms_root.rstrip("/").rsplit("/", 1)[0] + "/romkade"


async def _read_text(sftp, path: str) -> str | None:
    try:
        async with sftp.open(path, "rb") as f:
            return (await f.read()).decode().strip() or None
    except Exception:  # noqa: BLE001 — fichier absent : app plus ancienne
        return None


async def read_version(sftp, roms_root: str) -> str | None:
    """Version de l'app ROMKADE installée sur la console (None avant que le Manager l'écrive)."""
    return await _read_text(sftp, f"{agent_dir(roms_root)}/VERSION")


async def read_build(sftp, roms_root: str) -> str | None:
    """Empreinte de l'app installée sur la console (voir build_id)."""
    return await _read_text(sftp, f"{agent_dir(roms_root)}/BUILD")


def update_later(state, client) -> None:
    """Console connectée au Manager : son app ROMKADE est mise à jour en tâche de fond si ce Manager en a une autre
    version (au plus une vérification par heure). Rien si l'app n'est pas installée (console pas reliée)."""
    host = client.settings.host
    if time.time() - _updates.get(host, 0) < UPDATE_EVERY:
        return
    _updates[host] = time.time()
    task = asyncio.get_running_loop().create_task(_auto_update(state, client))
    _pushes.add(task)
    task.add_done_callback(_pushes.discard)


async def _auto_update(state, client) -> bool:
    try:
        profile = await state.system.ensure()
        if profile.id not in SUPPORTED:
            return False
        roms_root = client.settings.roms_root
        async with state.pool.session(client) as (_conn, sftp):
            config = await read_agent(sftp, roms_root)
            if not (config and config.get("secret") and config.get("server")):
                return False
            if await read_build(sftp, roms_root) == build_id():
                return False
            await install(state.device_runner, client, sftp, roms_root, config["server"], config["secret"],
                          splash="updated")
        log.info("app ROMKADE de la console mise à jour (%s)", build_id())
        return True
    except Exception as exc:  # noqa: BLE001 — console occupée, en veille… : réessayé dans une heure
        log.warning("mise à jour de l'app ROMKADE impossible : %s", exc)
        return False


async def read_agent(sftp, roms_root: str) -> dict | None:
    """agent.json de la console (adresse du cloud, secret), ou None si l'agent n'est pas installé."""
    try:
        async with sftp.open(f"{agent_dir(roms_root)}/agent.json", "rb") as f:
            return json.loads(await f.read())
    except Exception:  # noqa: BLE001 — fichier absent ou illisible : pas d'agent
        return None


FAVORITES = "favorites.json"
MAX_FAVORITES = 500
_pushes: set[asyncio.Task] = set()  # envois en cours (référence gardée contre le ramasse-miettes)


async def write_favorites(sftp, roms_root: str, favorites: list[list[str]]) -> bool:
    """Pose les favoris de la console ([dossier de plateforme, chemin relatif], le dernier ajouté en tête) à côté de
    l'agent, qui les envoie au cloud. Rien quand l'agent n'est pas installé : renvoie False."""
    if await read_agent(sftp, roms_root) is None:
        return False
    data = json.dumps({"favorites": favorites[:MAX_FAVORITES]}, ensure_ascii=False).encode()
    async with sftp.open(f"{agent_dir(roms_root)}/{FAVORITES}", "wb") as f:
        await f.write(data)
    return True


async def push_favorites(st, console: str) -> None:
    """Favoris de la console branchée vers son agent ROMKADE. Console injoignable : rien, le prochain envoi (favori
    ajouté ou retiré, synchronisation du catalogue) rattrape."""
    from app.device.ssh_client import DeviceClient
    from app.services import catalog_query as cq

    def rows() -> list[list[str]]:
        with st.sessions() as s:
            return [[g.platform.directory, g.relative_path] for g in cq.favorites(s, console)]

    client = DeviceClient(st.settings_store.load(), st.credentials, st.host_keys)
    try:
        favorites = await asyncio.to_thread(rows)
        async with st.pool.session(client) as (_conn, sftp):
            await write_favorites(sftp, client.settings.roms_root, favorites)
    except Exception as exc:  # noqa: BLE001 — console éteinte, hors Wi-Fi…
        log.info("favoris non envoyés à l'agent ROMKADE : %s", exc)


def push_favorites_later(st, console: str) -> None:
    task = asyncio.create_task(push_favorites(st, console))
    _pushes.add(task)
    task.add_done_callback(_pushes.discard)


async def register(token: str, name: str | None, info: dict, secret: str | None,
                   transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Enregistre (ou reprend) la console sur le compte ROMKADE de l'utilisateur ; renvoie console, secret, serveur."""
    body = {**info, "name": name, "secret": secret}
    try:
        async with httpx.AsyncClient(timeout=20, transport=transport) as http:
            r = await http.post(f"{CLOUD_URL}/api/me/consoles", json=body, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise errors.AppError("cloud_unreachable", "ROMKADE Cloud est injoignable : vérifie la connexion Internet.", 502) from exc
    if r.status_code == 401:
        raise errors.AppError("cloud_unauthorized", "Session ROMKADE expirée : reconnecte-toi.", 401)
    if r.status_code == 409:
        raise errors.AppError("cloud_console_limit", "Une seule console par compte pour l'instant : retire celle déjà "
                              "reliée avant de relier celle-ci.", 409)
    if r.status_code >= 400:
        raise errors.AppError("cloud_error", f"ROMKADE Cloud a refusé la liaison ({r.status_code}).", 502)
    return r.json()


async def install(run, client, sftp, roms_root: str, server: str, secret: str, splash: str | None = None) -> bool:
    """Copie l'agent, écrit sa configuration, l'ajoute au démarrage de la console et le (re)lance. Avec `splash`
    (« installed » ou « updated »), l'écran ROMKADE l'annonce quelques secondes sur la console, sauf pendant un jeu :
    renvoie True s'il s'est affiché."""
    for path, (data, mode) in bundle(roms_root).items():
        await sftp.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
        async with sftp.open(path, "wb") as f:
            await f.write(data)
        await sftp.chmod(path, mode)
    base = agent_dir(roms_root)
    config = json.dumps({"server": server, "secret": secret}, indent=1).encode()
    async with sftp.open(f"{base}/agent.json.tmp", "wb") as f:
        await f.write(config)
    await sftp.chmod(f"{base}/agent.json.tmp", 0o600)
    start = f"{base}/start.sh"
    line = f"[ -x {start} ] && {start}  {MARK}"
    apps = roms_root.rstrip("/") + "/APPS"
    old_apps = " ".join(shlex.quote(f"{apps}/{p}") for n in OLD_APP_NAMES for p in (f"{n}.sh", f"Imgs/{n}.png"))
    command = (
        f"rm -f {old_apps}; "  # app renommée : l'ancienne entrée du menu APPS disparaît
        f"mv {shlex.quote(base + '/agent.json.tmp')} {shlex.quote(base + '/agent.json')} && sync; "
        # Démarrage avec la console : une ligne marquée avant le « exit 0 » final du script du Stock OS Mod.
        f"if [ -f {AUTOSTART} ] && ! grep -qF {shlex.quote(MARK)} {AUTOSTART}; then "
        f"sed -i {shlex.quote('/^exit 0$/i ' + line)} {AUTOSTART}; fi; "
        "[ -f /tmp/romkade-agent.pid ] && kill \"$(cat /tmp/romkade-agent.pid)\" 2>/dev/null; sleep 1; "
        f"{shlex.quote(start)}; sleep 3; p=$(cat /tmp/romkade-agent.pid 2>/dev/null); "
        "[ -n \"$p\" ] && [ -d /proc/$p ] && echo started"
    )
    code, out = await run(client, command, timeout=40)
    if "started" not in out:
        raise errors.AppError("agent_start_failed", "L'app ROMKADE n'a pas démarré sur la console.", 502,
                              {"exit": code, "output": out[-300:]})
    if splash not in ("installed", "updated"):
        return False
    from app.device.launcher import GAME_PROCESSES  # jeu en cours : on ne le recouvre pas
    _, out = await run(client, (
        f"for p in {' '.join(GAME_PROCESSES)}; do pidof $p >/dev/null 2>&1 && exit 0; done; "
        # splash.sh ferme le menu le temps de l'écran (il s'affiche au-dessus de l'app), puis le laisse revenir.
        f"(setsid bash {shlex.quote(base + '/splash.sh')} {splash} 6 </dev/null >/tmp/romkade-splash.log 2>&1 &); "
        "echo shown"), timeout=15)
    return "shown" in out


async def uninstall(run, client, roms_root: str) -> None:
    """Arrête l'agent, le retire du démarrage et efface son secret (la console n'est plus reliée)."""
    base = agent_dir(roms_root)
    await run(client, f"[ -x {shlex.quote(base + '/uninstall.sh')} ] && {shlex.quote(base + '/uninstall.sh')}; "
                      f"rm -f {shlex.quote(base + '/agent.json')}; sync; echo ok", timeout=30)
