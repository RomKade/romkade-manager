"""Lancer un jeu sur la console, savoir ce qui tourne, quitter le jeu en cours.

Seule partie de l'application qui exécute des commandes sur la console (en plus des transferts).
Firmware Anbernic avec « Stock OS Mod » (/mnt/mod/ctrl/RA_launch.sh) : voir launch.sh. Batocera et Knulli
(et ROCKNIX quand il l'a) : serveur web d'EmulationStation (ES_HTTP, /launch, /runningGame, /emukill).
Rien n'est écrit sur la carte ; le script est passé en argument à bash et son journal va dans /tmp.
"""

import re
import shlex
from collections.abc import Awaitable, Callable
from pathlib import Path

import asyncssh

from app import errors
from app.device.ssh_client import DeviceClient

LAUNCH_SCRIPT = (Path(__file__).parent / "launch.sh").read_text()
VOLUME_KEYS_SCRIPT = (Path(__file__).parent / "volume_keys.py").read_text()
PLAYERS_SCRIPT = (Path(__file__).parent / "players_apply.sh").read_text()
LOG = "/tmp/agm-launch.log"
REQUIRED = "/mnt/mod/ctrl/RA_launch.sh"
GAME_PROCESSES = ("retroarch", "PPSSPPSDL", "drastic", "OpenBOR.dge", "PPSSPP", "mupen64plus", "flycast",
                  "duckstation-nogui", "dosbox-pure", "scummvm", "openbor",
                  # Émulateurs autonomes du firmware Anbernic (/mnt/vendor/bin/game), choisis par le menu de la
                  # console pour certaines consoles (« pcsx » pour la PlayStation…) : la ROM est le dernier argument.
                  "pcsx", "gba_emu.dge", "vbanext.dge", "gbcgb_emu.dge", "sfc_emu.dge", "fc_emu.dge", "md_emu.dge",
                  "smsgg_emu.dge", "pce.dge", "ngp.dge", "swanemu.dge", "xmame.dge", "fba4arm.dge", "fbasdl.dge",
                  "fbaverti.dge")
ES_HTTP = "http://127.0.0.1:1234"
ES_GET = "{ curl -s -m 5 %(u)s || wget -q -T 5 -O - %(u)s; } 2>/dev/null"

# (code de sortie, sortie standard). Remplaçable dans les tests.
Runner = Callable[..., Awaitable[tuple[int, str]]]  # (client, commande, timeout=…)


async def ssh_run(client: DeviceClient, command: str, timeout: float = 20) -> tuple[int, str]:
    async with client.connect() as conn:
        try:
            r = await conn.run(command, check=False, timeout=timeout)
        except asyncssh.TimeoutError as exc:
            raise errors.AppError("device_command_timeout", f"La console n'a pas répondu à temps ({timeout:.0f} s).",
                                  504, {"timeout": timeout}) from exc
        return (r.exit_status or 0), str(r.stdout or "")


def launch_command(platform_dir: str, rom_path: str, slot: str | None = None) -> str:
    from app.device.volume import ASOUNDRC, VERSION, asoundrc  # volume importe Runner d'ici

    # Volume des jeux (voir volume.py) : /.asoundrc installé s'il manque ou date d'une autre version (en gardant
    # la sortie Bluetooth si elle était choisie).
    rc = (f"grep -q {VERSION} {ASOUNDRC} 2>/dev/null || {{ if grep -q agm_bt {ASOUNDRC} 2>/dev/null; "
          f"then printf %s {shlex.quote(asoundrc('agm_bt'))} > {ASOUNDRC}; "
          f"else printf %s {shlex.quote(asoundrc())} > {ASOUNDRC}; fi; }}; ")
    # setsid + nohup : le jeu continue après la fermeture de la session SSH. AGM_VOLKEYS : touches de volume
    # pendant le jeu (volume_keys.py, lancé par launch.sh). AGM_PLAYERS : manette de chaque joueur
    # (players_apply.sh, lancé par launch.sh une fois RetroArch fermé).
    return (f"test -x {REQUIRED} || {{ echo no-mod; exit 7; }}; {rc}"
            f"AGM_VOLKEYS={shlex.quote(VOLUME_KEYS_SCRIPT)} AGM_PLAYERS={shlex.quote(PLAYERS_SCRIPT)} "
            f"setsid nohup bash -c {shlex.quote(LAUNCH_SCRIPT)} agm-launch {shlex.quote(platform_dir)} "
            f"{shlex.quote(rom_path)} {shlex.quote(slot or '')} > {LOG} 2>&1 < /dev/null & echo started")


STATUS_COMMAND = (
    "for p in " + " ".join(GAME_PROCESSES) + "; do pid=$(pidof $p | awk '{print $1}'); "
    "if [ -n \"$pid\" ]; then echo \"proc=$p\"; tr '\\0' '\\n' < /proc/$pid/cmdline | tail -1 | sed 's/^/arg=/'; break; fi; done; "
    "pidof dmenu.bin >/dev/null && echo menu=1; true"
)
# Batocera / Knulli : EmulationStation sait quel jeu tourne (JSON avec « path »).
ES_STATUS_COMMAND = "echo @@ES; " + ES_GET % {"u": f"{ES_HTTP}/runningGame"} + "; echo; echo @@PROC; " + STATUS_COMMAND
# Commande réseau de RetroArch (network_cmd_enable, port 55355), envoyée en UDP par bash. Le binaire
# « retroarch --command QUIT » ne marche pas depuis SSH : il lui manque LD_LIBRARY_PATH.
QUIT_UDP = "echo -n QUIT > /dev/udp/127.0.0.1/55355"
QUIT_COMMAND = (f"pidof retroarch >/dev/null || {{ echo none; exit 0; }}; "
                f"for i in $(seq 1 30); do pidof retroarch >/dev/null || break; bash -c '{QUIT_UDP}' 2>/dev/null; sleep 0.3; done; "
                f"pidof retroarch >/dev/null && echo still || echo quit")
# Autres firmwares : bash n'existe pas toujours (BusyBox) -> nc ; RetroArch ignore les commandes réseau si
# network_cmd_enable est coupé -> SIGTERM, que RetroArch traite comme « Quitter » (sauvegarde en jeu écrite).
QUIT_GENERIC_COMMAND = (
    "pidof retroarch >/dev/null || { echo none; exit 0; }; "
    "for i in 1 2 3 4 5 6 7 8 9 10; do pidof retroarch >/dev/null || break; "
    f"{{ bash -c '{QUIT_UDP}' || printf QUIT | nc -u -w1 127.0.0.1 55355; }} >/dev/null 2>&1; sleep 0.3; done; "
    "pidof retroarch >/dev/null && { kill -TERM $(pidof retroarch); sleep 2; }; "
    "pidof retroarch >/dev/null && echo still || echo quit")
ES_RUNNING = ES_GET % {"u": f"{ES_HTTP}/runningGame"} + " | grep -q '\"path\"'"
# Serveur web d'EmulationStation absent : même méthode que les autres firmwares.
ES_QUIT_COMMAND = (ES_GET % {"u": f"{ES_HTTP}/caps"} + " >/dev/null || { " + QUIT_GENERIC_COMMAND + "; exit 0; }; "
                   + ES_RUNNING + " || { echo none; exit 0; }; "
                   + ES_GET % {"u": f"{ES_HTTP}/emukill"} + " >/dev/null; "
                   "for i in 1 2 3 4 5 6 7 8 9 10; do " + ES_RUNNING + " || break; sleep 0.5; done; "
                   + ES_RUNNING + " && echo still || echo quit")


def es_launch_command(rom_path: str) -> str:
    body = shlex.quote(rom_path)
    return (f"{{ curl -s -m 10 -X POST --data-binary {body} {ES_HTTP}/launch || "
            f"wget -q -T 10 -O - --post-data={body} {ES_HTTP}/launch; }} >/dev/null 2>&1 && echo started || echo no-es")


SLOT_RE = re.compile(r"^(auto|\d{1,3})$")


async def launch(run: Runner, client: DeviceClient, platform_dir: str, rom_path: str, slot: str | None = None,
                 profile=None) -> None:
    """Lance le jeu ; `slot` : « auto » (reprise automatique) ou numéro d'emplacement de sauvegarde instantanée."""
    if slot is not None and not SLOT_RE.fullmatch(slot):
        raise errors.AppError("bad_slot", "Emplacement de sauvegarde invalide", 422, {"slot": slot})
    method = profile.launcher if profile else "stock-mod"
    if method is None:
        raise errors.AppError("launch_unsupported", f"Lancement à distance impossible sur {profile.label} : "
                              "lance le jeu depuis la console.", 409, {"system": profile.id})
    if method == "es-http":
        if slot is not None:
            raise errors.AppError("launch_unsupported", "Reprendre sur une sauvegarde depuis Game Manager n'est "
                                  f"possible que sur le firmware Anbernic avec Stock OS Mod.", 409, {"system": profile.id})
        _, out = await run(client, es_launch_command(rom_path))
        if "started" not in out:
            raise errors.AppError("launch_unsupported", "Le serveur web d'EmulationStation ne répond pas "
                                  "(port 1234) : lance le jeu depuis la console.", 409, {"system": profile.id})
        return
    code, out = await run(client, launch_command(platform_dir, rom_path, slot))
    if code == 7 or "no-mod" in out:
        raise errors.AppError("launch_unsupported", "Lancement à distance impossible : ce firmware n'a pas le "
                              "« Stock OS Mod » (/mnt/mod/ctrl/RA_launch.sh absent).", 409)
    if "started" not in out:
        raise errors.AppError("launch_failed", "La console n'a pas lancé le jeu", 502, {"exit": code, "output": out[-500:]})


def parse_status(out: str) -> dict:
    if "@@ES" in out:
        es, _, proc = out.partition("@@PROC")
        st = parse_status(proc)
        m = re.search(r'"path"\s*:\s*"([^"]+)"', es)
        if m:
            st.update(playing=True, rom_path=m.group(1).replace("\\/", "/"), process=st["process"] or "emulationstation")
        return st
    info = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    proc = info.get("proc")
    rom = info.get("arg") if proc else None
    return {"playing": proc is not None, "process": proc, "rom_path": rom if rom and rom.startswith("/") else None,
            "menu": info.get("menu") == "1"}


async def status(run: Runner, client: DeviceClient, profile=None) -> dict:
    es = profile is not None and profile.launcher == "es-http"
    _, out = await run(client, ES_STATUS_COMMAND if es else STATUS_COMMAND)
    return parse_status(out)


def quit_command(profile=None) -> str:
    if profile is None or profile.id.startswith("anbernic"):
        return QUIT_COMMAND
    if profile.quit == "es-http":
        return ES_QUIT_COMMAND
    if profile.quit == "none":
        raise errors.AppError("quit_unsupported", f"Quitter le jeu à distance est impossible sur {profile.label}.", 409)
    return QUIT_GENERIC_COMMAND


async def quit_game(run: Runner, client: DeviceClient, profile=None) -> str:
    _, out = await run(client, quit_command(profile))
    result = out.strip().splitlines()[-1] if out.strip() else "none"
    if result == "still":
        raise errors.AppError("quit_failed", "Le jeu ne s'est pas fermé. Quitte-le depuis la console.", 502)
    return result
