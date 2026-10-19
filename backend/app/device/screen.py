"""Capture d'écran de la console : l'image affichée, lue dans le framebuffer (/dev/fb0).

La commande SCREENSHOT de RetroArch ne produit rien sur le firmware d'origine (pilote vidéo mali-fbdev) : on lit
donc l'écran lui-même, ce qui marche aussi pour les jeux hors RetroArch (NDS, PSP). L'écran est en double tampon
(640x960 virtuel pour 640x480 affiché) : on lit la page affichée (yoffset). Un petit script python3 (présent sur
la console) en fait un PNG, renvoyé en base64 sur la sortie standard ; rien n'est écrit sur la carte.
"""

import base64
import binascii
import shlex

from app import errors
from app.device.launcher import Runner
from app.device.ssh_client import DeviceClient

# Pixels lus selon les champs de couleur du pilote (FBIOGET_VSCREENINFO) : 32 bits (jeux) par tranches, rapide ;
# 16 bits (le menu de la console) pixel par pixel, plus lent mais rare.
GRAB_SCRIPT = r'''import base64, fcntl, os, struct, sys, zlib
fd = os.open("/dev/fb0", os.O_RDONLY)
v = bytearray(160); fcntl.ioctl(fd, 0x4600, v)
xres, yres, _, _, xoff, yoff, bpp = struct.unpack_from("7I", v)
red, green, blue = [struct.unpack_from("2I", v, 32 + 12 * i) for i in range(3)]
f = bytearray(68); fcntl.ioctl(fd, 0x4602, f)
stride = struct.unpack_from("I", f, 48)[0]
os.lseek(fd, yoff * stride, 0)
raw = os.read(fd, yres * stride)
step = bpp // 8
rows = []
for y in range(yres):
    line = raw[y * stride + xoff * step: y * stride + (xoff + xres) * step]
    px = bytearray(xres * 3)
    if bpp == 32:
        for c, (off, _) in enumerate((red, green, blue)):
            px[c::3] = line[off // 8::4]
    else:
        for x in range(xres):
            p = int.from_bytes(line[x * step:(x + 1) * step], "little")
            for c, (off, n) in enumerate((red, green, blue)):
                px[3 * x + c] = ((p >> off) & ((1 << n) - 1)) * 255 // ((1 << n) - 1)
    rows.append(b"\0" + bytes(px))
def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", xres, yres, 8, 2, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))
sys.stdout.write("@@PNG " + base64.b64encode(png).decode() + "\n")
'''
COMMAND = f"python3 -c {shlex.quote(GRAB_SCRIPT)} 2>&1"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


async def grab(run: Runner, client: DeviceClient) -> bytes:
    """L'écran de la console en PNG."""
    _, out = await run(client, COMMAND, timeout=30)
    data = b""
    if "@@PNG " in out:
        try:
            data = base64.b64decode(out.split("@@PNG ", 1)[1].split("\n", 1)[0], validate=True)
        except binascii.Error:
            data = b""
    if not data.startswith(PNG_MAGIC):
        raise errors.AppError("screenshot_failed", "La capture d'écran a échoué : l'écran de la console n'a pas pu "
                              "être lu.", 502, {"detail": out.strip()[-300:]})
    return data
