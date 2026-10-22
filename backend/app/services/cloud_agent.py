"""Relier la console à ROMKADE Cloud depuis le Manager, sans code d'appairage : installation de l'agent ROMKADE.

L'agent (cloud/agent du dépôt) tourne sur la console et appelle mcp.romkade.com en HTTPS sortant : ChatGPT, Claude…
pilotent alors la console, et le Manager voit les mêmes consoles que le compte ROMKADE.

Étapes, à la demande de l'utilisateur connecté :
1. le cloud enregistre la console sur son compte (jeton de session Supabase) et renvoie le secret de son agent ;
2. le Manager copie l'agent par SFTP (dossier « romkade » à côté du dossier des ROMs, app « ROMKADE » dans APPS),
   écrit agent.json (adresse du cloud + secret, lisible par root seul), ajoute le démarrage automatique et lance
   l'agent. L'agent embarque les modules de pilotage du Manager (launcher, volume, systems), exécutés sur place.

Seul le firmware Anbernic + Stock OS Mod est pris en charge (Python 3, menu APPS, script de démarrage du mod).
Écriture hors du dossier des ROMs, et dans APPS : exception voulue à remote_writer, limitée aux fichiers listés ici.
"""

import json
import os
import shlex
from pathlib import Path

import httpx

from app import errors

APP_DIR = Path(__file__).resolve().parents[1]                  # backend/app
REPO = APP_DIR.parents[1]                                       # racine du dépôt (installation depuis les sources)
CLOUD_URL = os.environ.get("ROMKADE_CLOUD_URL", "https://mcp.romkade.com").rstrip("/")
SUPPORTED = {"anbernic-stock-mod"}
AUTOSTART = "/mnt/mod/ctrl/autostart"
MARK = "# ROMKADE"
VENDOR = ("__init__.py", "errors.py")
VENDOR_DEVICE = ("__init__.py", "launcher.py", "volume.py", "systems.py", "launch.sh", "onion_launch.sh",
                 "players_apply.sh", "volume_keys.py")


def agent_source() -> Path:
    """Dossier de l'agent : ROMKADE_AGENT_DIR (image Docker), sinon cloud/agent du dépôt."""
    path = Path(os.environ.get("ROMKADE_AGENT_DIR") or REPO / "cloud" / "agent")
    if not (path / "romkade_agent.py").is_file():
        raise errors.AppError("agent_missing", "Agent ROMKADE introuvable dans cette installation du Manager.", 500)
    return path


def bundle(roms_root: str) -> dict[str, tuple[bytes, int]]:
    """{chemin sur la console: (contenu, droits)} de l'agent, de son écran et de l'app du menu APPS."""
    src = agent_source()
    base = roms_root.rstrip("/").rsplit("/", 1)[0] + "/romkade"
    files: dict[str, tuple[bytes, int]] = {}
    for name, mode in (("romkade_agent.py", 0o755), ("screen.py", 0o755), ("start.sh", 0o755), ("uninstall.sh", 0o755)):
        files[f"{base}/{name}"] = ((src / name).read_bytes(), mode)
    for asset in sorted((src / "assets").iterdir()):
        if asset.is_file() and asset.name != "apps-icon.png":
            files[f"{base}/assets/{asset.name}"] = (asset.read_bytes(), 0o644)
    for stub in sorted((src / "stubs").rglob("*.py")):
        files[f"{base}/vendor/{stub.relative_to(src / 'stubs')}"] = (stub.read_bytes(), 0o644)
    for name in VENDOR:
        files[f"{base}/vendor/app/{name}"] = ((APP_DIR / name).read_bytes(), 0o644)
    for name in VENDOR_DEVICE:
        files[f"{base}/vendor/app/device/{name}"] = ((APP_DIR / "device" / name).read_bytes(), 0o644)
    for legal in ("LICENSE", "NOTICE"):  # à la racine du dépôt (ou de /app dans l'image Docker)
        path = src.parents[1] / legal
        if path.is_file():
            files[f"{base}/{legal}"] = (path.read_bytes(), 0o644)
    apps = roms_root.rstrip("/") + "/APPS"
    files[f"{apps}/ROMKADE.sh"] = ((src / "RomKade.sh").read_bytes(), 0o755)
    files[f"{apps}/Imgs/ROMKADE.png"] = ((src / "assets" / "apps-icon.png").read_bytes(), 0o644)
    return files


def agent_dir(roms_root: str) -> str:
    return roms_root.rstrip("/").rsplit("/", 1)[0] + "/romkade"


async def read_agent(sftp, roms_root: str) -> dict | None:
    """agent.json de la console (adresse du cloud, secret), ou None si l'agent n'est pas installé."""
    try:
        async with sftp.open(f"{agent_dir(roms_root)}/agent.json", "rb") as f:
            return json.loads(await f.read())
    except Exception:  # noqa: BLE001 — fichier absent ou illisible : pas d'agent
        return None


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
    if r.status_code >= 400:
        raise errors.AppError("cloud_error", f"ROMKADE Cloud a refusé la liaison ({r.status_code}).", 502)
    return r.json()


async def install(run, client, sftp, roms_root: str, server: str, secret: str) -> None:
    """Copie l'agent, écrit sa configuration, l'ajoute au démarrage de la console et le (re)lance."""
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
    command = (
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
        raise errors.AppError("agent_start_failed", "L'agent ROMKADE n'a pas démarré sur la console.", 502,
                              {"exit": code, "output": out[-300:]})


async def uninstall(run, client, roms_root: str) -> None:
    """Arrête l'agent, le retire du démarrage et efface son secret (la console n'est plus reliée)."""
    base = agent_dir(roms_root)
    await run(client, f"[ -x {shlex.quote(base + '/uninstall.sh')} ] && {shlex.quote(base + '/uninstall.sh')}; "
                      f"rm -f {shlex.quote(base + '/agent.json')}; sync; echo ok", timeout=30)
