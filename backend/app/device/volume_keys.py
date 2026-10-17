"""Touches Vol+ / Vol- de la console pendant un jeu lancé depuis Game Manager (exécuté SUR la console).

RetroArch ne traite ces touches (boutons 16 et 15 de « ANBERNIC-keys ») qu'en maintenant le bouton de raccourci
(Menu, bouton 8), et ne règle alors que son propre volume. Ce script, lancé par launch.sh pendant le jeu, lit les
touches directement (KEY_VOLUMEUP / KEY_VOLUMEDOWN) et règle le volume Game Manager (voir volume.py) par pas de
STEP (2 dB), en affichant le niveau à l'écran (SHOW_MSG de RetroArch). Menu maintenu : on laisse faire RetroArch.
Il s'arrête quand RetroArch s'arrête. Lecture seule des touches : le jeu les reçoit toujours.

Fichier passé en texte à `python3 -c` (variable AGM_VOLKEYS de launch.sh) : bibliothèque standard seulement.
"""

import os
import re
import select
import socket
import struct
import subprocess
import time

VOLUME = "name=Game Manager Playback Volume"
SWITCH = "name=Game Manager Playback Switch"
KEY_VOLUMEDOWN, KEY_VOLUMEUP, HOTKEY = 114, 115, 312
STEP = 4  # 0,5 dB par cran du réglage
EVENT = "llHHi"
ENV = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}  # amixer est un programme 64 bits


def amixer(*args: str) -> str:
    return subprocess.run(["amixer", "-c", "0", *args], capture_output=True, text=True, env=ENV).stdout


def device() -> str | None:
    for name in sorted(os.listdir("/sys/class/input")):
        try:
            if name.startswith("event") and open(f"/sys/class/input/{name}/device/name").read().strip() == "ANBERNIC-keys":
                return f"/dev/input/{name}"
        except OSError:
            pass
    return None


def retroarch() -> bool:
    return subprocess.run(["pidof", "retroarch"], capture_output=True).returncode == 0


def change(delta: int, osd: socket.socket) -> None:
    out = amixer("cget", VOLUME)
    value, top = re.search(r": values=(\d+)", out), re.search(r"\bmax=(\d+)", out)
    if not (value and top):
        return  # réglage pas encore créé (le jeu n'a pas ouvert le son)
    top_ = int(top.group(1))
    new = max(0, min(top_, int(value.group(1)) + delta))
    amixer("cset", VOLUME, f"{new},{new}")
    amixer("cset", SWITCH, "on,on" if new > 0 else "off,off")
    osd.sendto(f"SHOW_MSG Volume {round(new * 100 / top_)} %".encode(), ("127.0.0.1", 55355))


def main() -> None:
    path = device()
    if not path:
        return
    for _ in range(60):  # RetroArch démarre
        if retroarch():
            break
        time.sleep(0.5)
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    osd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    size = struct.calcsize(EVENT)
    hotkey = False
    last_check = time.time()
    while True:
        ready, _, _ = select.select([fd], [], [], 1)
        if time.time() - last_check > 2:
            if not retroarch():
                return
            last_check = time.time()
        if not ready:
            continue
        data = os.read(fd, size * 64)
        for k in range(0, len(data) - size + 1, size):
            _, _, typ, code, value = struct.unpack(EVENT, data[k:k + size])
            if typ != 1:
                continue
            if code == HOTKEY:
                hotkey = value != 0
            elif code in (KEY_VOLUMEUP, KEY_VOLUMEDOWN) and value in (1, 2) and not hotkey:  # appui ou répétition
                change(STEP if code == KEY_VOLUMEUP else -STEP, osd)


main()
