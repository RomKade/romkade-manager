"""Manette virtuelle sur la console, pilotée à distance (exécuté SUR la console).

Une manette connectée à l'ordinateur (en Bluetooth, sans fil) est lue par le navigateur (API Gamepad) ;
Game Manager relaie ses appuis par la connexion SSH. Ce script crée avec /dev/uinput une manette qui se présente
comme une manette Xbox 360 filaire (même nom, mêmes identifiants USB 045e:028e et mêmes boutons que le pilote
xpad) : RetroArch (pilote sdl2) la reconnaît avec sa configuration « X360 Controller », comme une vraie.

Entrée standard : une ligne par changement, des triplets « type,code,valeur » séparés par des espaces
(événements evdev, voir app/device/gamepad.py), suivis d'un SYN_REPORT. Fin de l'entrée (Game Manager fermé,
connexion coupée) : la manette disparaît.

Argument : l'identifiant du relais, mis dans « Phys » (romkade-relay-<id>) pour que Game Manager retrouve cette
manette parmi celles de la console (app/device/players.py).

Fichier passé en texte à `python3 -c` : bibliothèque standard seulement.
"""

import fcntl
import os
import struct
import sys

UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_ABSBIT, UI_SET_PHYS = 0x40045564, 0x40045565, 0x40045567, 0x4008556C
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
# BTN_A B X Y TL TR SELECT START MODE THUMBL THUMBR, comme xpad
KEYS = (304, 305, 307, 308, 310, 311, 314, 315, 316, 317, 318)
# code : (min, max, fuzz, flat) — sticks X Y RX RY, gâchettes Z RZ, croix HAT0X HAT0Y
AXES = {0: (-32768, 32767, 16, 128), 1: (-32768, 32767, 16, 128), 3: (-32768, 32767, 16, 128),
        4: (-32768, 32767, 16, 128), 2: (0, 255, 0, 0), 5: (0, 255, 0, 0), 16: (-1, 1, 0, 0), 17: (-1, 1, 0, 0)}
NAME = b"Microsoft X-Box 360 pad"
PHYS = b"romkade-relay-" + (sys.argv[1] if len(sys.argv) > 1 else "").encode()[:16]
BUS_USB, VENDOR, PRODUCT, VERSION = 3, 0x045E, 0x028E, 0x0114
EVENT = "llHHi"


def create() -> int:
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    for ev in (EV_KEY, EV_ABS):
        fcntl.ioctl(fd, UI_SET_EVBIT, ev)
    for key in KEYS:
        fcntl.ioctl(fd, UI_SET_KEYBIT, key)
    for code in AXES:
        fcntl.ioctl(fd, UI_SET_ABSBIT, code)
    fcntl.ioctl(fd, UI_SET_PHYS, PHYS + b"\0")
    table = [[0] * 64 for _ in range(4)]  # absmax, absmin, absfuzz, absflat
    for code, (lo, hi, fuzz, flat) in AXES.items():
        table[0][code], table[1][code], table[2][code], table[3][code] = hi, lo, fuzz, flat
    os.write(fd, struct.pack("80sHHHHi256i", NAME, BUS_USB, VENDOR, PRODUCT, VERSION, 0,
                             *table[0], *table[1], *table[2], *table[3]))
    fcntl.ioctl(fd, UI_DEV_CREATE)
    return fd


def main() -> None:
    fd = create()
    print("ready", flush=True)
    try:
        for line in sys.stdin:
            out = b""
            for item in line.split():
                try:
                    typ, code, value = (int(v) for v in item.split(","))
                except ValueError:
                    continue
                if (typ == EV_KEY and code in KEYS) or (typ == EV_ABS and code in AXES):
                    out += struct.pack(EVENT, 0, 0, typ, code, value)
            if out:
                os.write(fd, out + struct.pack(EVENT, 0, 0, EV_SYN, 0, 0))
    finally:
        fcntl.ioctl(fd, UI_DEV_DESTROY)
        os.close(fd)


main()
