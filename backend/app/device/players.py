"""Qui contrôle le jeu : manette attribuée à chaque joueur de RetroArch (firmware d'origine).

RetroArch (pilote sdl2) numérote les manettes dans l'ordre où le système les a vues : 0 = les boutons de la
console (« ANBERNIC-keys »), puis les manettes USB ou Bluetooth. Chaque joueur reçoit un numéro
(input_playerN_joypad_index). RetroArch enregistre sa config en quittant (config_save_on_exit) : un joueur 1
attribué un jour à une manette Bluetooth y reste, et la console ne contrôle plus le jeu quand la manette est
absente.

Les numéros de Game Manager suivent l'ordre des jsN de /proc/bus/input/devices, mais RetroArch (SDL2 avec udev)
numérote les manettes par chemin sysfs : avec une manette Xbox USB, Xbox = 0 et boutons de la console = 1, si
bien que « joueur 1 = n°1 » donnait la main à la console. PLAYERS_FILE garde les numéros de Game Manager ;
players_apply.sh les traduit dans l'ordre de RetroArch et réserve en plus la manette au joueur.

Le choix est rangé dans PLAYERS_FILE, puis écrit dans la config de RetroArch par players_apply.sh (qui en garde
une copie, APPLIED_FILE : ce qui a été appliqué) :
- tout de suite si aucun jeu ne tourne ;
- sinon au prochain jeu lancé depuis Game Manager (launch.sh, une fois RetroArch fermé). Écrit pendant le jeu,
  il serait écrasé par RetroArch en quittant.
"""

import re
import shlex
from pathlib import Path

from app import errors
from app.device.launcher import Runner
from app.device.ssh_client import DeviceClient

RA_CONFIG = "/.config/retroarch/retroarch.cfg"
PLAYERS_FILE = "/.config/agm-players"
APPLIED_FILE = PLAYERS_FILE + ".applied"
APPLY_SCRIPT = (Path(__file__).parent / "players_apply.sh").read_text()
PLAYERS = 4
MAX_INDEX = 15
LINE_RE = re.compile(r'^input_player([1-9])_joypad_index = "(\d+)"', re.M)

STATUS_COMMAND = (
    "echo @@INPUT; cat /proc/bus/input/devices; "
    f"echo @@CFG; grep -E '^input_player[1-{PLAYERS}]_joypad_index' {RA_CONFIG} 2>/dev/null; "
    f"echo @@WANT; cat {PLAYERS_FILE} 2>/dev/null; "
    f"echo @@APPLIED; cat {APPLIED_FILE} 2>/dev/null; "
    "echo @@RA; pidof retroarch; true"
)
# Même écriture que launch.sh (qui lance le même script avant chaque jeu).
APPLY = f"bash -c {shlex.quote(APPLY_SCRIPT)} >/dev/null"


def parse_controllers(text: str) -> list[dict]:
    """Manettes de /proc/bus/input/devices (gestionnaire « jsN »), dans l'ordre de RetroArch."""
    found = []
    for block in text.strip().split("\n\n"):
        name = re.search(r'^N: Name="(.*)"', block, re.M)
        js = re.search(r"^H: Handlers=.*\bjs(\d+)\b", block, re.M)
        if not (name and js):
            continue
        phys = re.search(r"^P: Phys=(.*)", block, re.M)
        ids = re.search(r"^I: .*Vendor=([0-9a-f]{4}) Product=([0-9a-f]{4})", block, re.M | re.I)
        builtin = name.group(1) == "ANBERNIC-keys" or "gpio-keys" in (phys.group(1) if phys else "")
        usb_id = f"{ids.group(1).lower()}:{ids.group(2).lower()}" if ids else None
        found.append((int(js.group(1)), name.group(1), builtin, usb_id))
    found.sort()
    return [{"index": i, "name": name, "builtin": builtin, "usb_id": usb_id}
            for i, (_, name, builtin, usb_id) in enumerate(found)]


def _indexes(text: str) -> list[int | None]:
    got = {int(p): int(i) for p, i in LINE_RE.findall(text)}
    return [got.get(p) for p in range(1, PLAYERS + 1)]


def parse_status(out: str) -> dict:
    parts = dict((head.strip(), body) for head, _, body in
                 (sec.partition("\n") for sec in re.split(r"^@@", out, flags=re.M) if sec))
    saved = _indexes(parts.get("CFG", ""))  # numéros de RetroArch (avant Game Manager : pas de traduction)
    wanted = _indexes(parts.get("WANT", ""))
    applied = _indexes(parts.get("APPLIED", ""))
    players = [w if w is not None else s for w, s in zip(wanted, saved)]
    done = applied if any(i is not None for i in applied) else saved
    return {"controllers": parse_controllers(parts.get("INPUT", "")), "players": players,
            "applied": players == done, "game_running": bool(parts.get("RA", "").strip())}


async def status(run: Runner, client: DeviceClient) -> dict:
    _, out = await run(client, STATUS_COMMAND)
    return parse_status(out)


def file_text(players: list[int]) -> str:
    """PLAYERS_FILE : numéro de Game Manager de chaque joueur (players_apply.sh le traduit pour RetroArch)."""
    return "".join(f'input_player{p}_joypad_index = "{i}"\n' for p, i in enumerate(players, 1))


async def set_players(run: Runner, client: DeviceClient, players: list[int]) -> dict:
    if len(players) != PLAYERS or len(set(players)) != PLAYERS or not all(0 <= i <= MAX_INDEX for i in players):
        raise errors.AppError("players_invalid", f"Il faut {PLAYERS} manettes différentes (numéros 0 à {MAX_INDEX}).",
                              422, {"players": players})
    await run(client, f"printf %s {shlex.quote(file_text(players))} > {PLAYERS_FILE} && "
                      f"{{ pidof retroarch >/dev/null || {{ {APPLY}; }}; }}; sync")
    return await status(run, client)
