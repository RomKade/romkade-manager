"""Date, heure et fuseau horaire de la console, mis à l'heure du Mac à la demande.

La console n'a pas de synchronisation réseau active (NTP inactif) et son horloge dérive ou repart d'une date
ancienne : les parties lancées depuis la console sont alors mal datées (temps de jeu, journaux de RetroArch).
On envoie l'heure UTC du Mac (`date -u -s @<secondes>`), on l'écrit dans l'horloge matérielle (`hwclock -w`,
gardée console éteinte) et on règle le fuseau horaire (/etc/localtime, comme timedatectl).

Le menu de la console (dmenu.bin) lit le fuseau une seule fois, à son démarrage : après un changement de fuseau,
il afficherait encore l'ancienne heure. On le redémarre donc (MENU_RESTART), comme après un jeu, si aucun jeu ne
tourne : il quitte proprement (SIGINT), sa boucle (/mnt/vendor/ctrl/loadapp.sh) le relance aussitôt.
"""

import re
import shlex
import time

from app import errors
from app.device.launcher import Runner
from app.device.ssh_client import DeviceClient

TZ_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+){0,2}$")
STATUS_COMMAND = ("date -u +%s; readlink /etc/localtime 2>/dev/null || cat /etc/timezone 2>/dev/null; "
                  "date +%z; true")


def parse_status(out: str, now: float | None = None) -> dict:
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    if not lines or not lines[0].isdigit():
        raise errors.AppError("clock_unreadable", "L'heure de la console n'a pas pu être lue.", 502,
                              {"output": out[:200]})
    epoch = int(lines[0])
    tz = next((x.split("zoneinfo/", 1)[1] for x in lines[1:] if "zoneinfo/" in x), None) \
        or next((x for x in lines[1:-1] if TZ_RE.match(x)), None)
    offset = lines[-1] if re.fullmatch(r"[+-]\d{4}", lines[-1]) else None
    mac = time.time() if now is None else now
    return {"console_epoch": epoch, "timezone": tz, "utc_offset": offset, "mac_epoch": int(mac),
            "drift_seconds": int(epoch - mac)}


async def status(run: Runner, client: DeviceClient) -> dict:
    _, out = await run(client, STATUS_COMMAND)
    return parse_status(out)


# Redémarre le menu si aucun jeu ne tourne. dmenu_ln attend 30 s après un menu fermé par signal : on l'arrête
# (avec son « sleep »), la boucle loadapp.sh relance aussitôt dmenu_ln, donc le menu.
MENU_RESTART = r"""M=$(pidof dmenu.bin | awk '{print $1}')
if [ -n "$M" ] && ! pidof retroarch pcsx >/dev/null; then
  kill -INT "$M"; for _ in $(seq 1 25); do [ -d "/proc/$M" ] || break; sleep 0.2; done
  for d in /proc/[0-9]*; do
    [ "$( { tr '\0' ' ' < "$d/cmdline"; } 2>/dev/null)" = "/bin/bash /mnt/vendor/ctrl/dmenu_ln " ] || continue
    p=${d#/proc/}; pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null
  done
  echo menu-restarted
fi"""


def sync_command(epoch: int, timezone: str | None) -> str:
    cmd = f"date -u -s @{epoch} >/dev/null && (hwclock -w 2>/dev/null || true)"
    if timezone:
        zone = shlex.quote(f"/usr/share/zoneinfo/{timezone}")
        # Fuseau changé : on l'écrit, puis le menu redémarre pour l'afficher.
        cmd += (f"; if [ -f {zone} ] && [ \"$(readlink /etc/localtime)\" != {zone} ]; then "
                f"ln -sf {zone} /etc/localtime && echo {shlex.quote(timezone)} > /etc/timezone && sync\n{MENU_RESTART}\nfi")
    return cmd + "; sync"


async def sync(run: Runner, client: DeviceClient, timezone: str | None) -> dict:
    """Met la console à l'heure du Mac (et au fuseau `timezone`, nom IANA comme « Europe/Paris »)."""
    if timezone is not None and (not TZ_RE.match(timezone) or ".." in timezone):
        raise errors.AppError("clock_bad_timezone", "Fuseau horaire invalide.", 422, {"timezone": timezone})
    await run(client, sync_command(int(time.time()), timezone))
    return await status(run, client)
