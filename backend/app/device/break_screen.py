"""Alerte de temps de jeu en plein écran sur la console : le jeu est figé, l'écran dit « ça fait 1 h que tu
joues », et la partie ne reprend qu'avec A (ou START), ou depuis ROMKADE Manager.

Lancé par le Manager (app/services/playtime.py) : copié dans /tmp puis exécuté par python3 (présent avec Pillow sur
le firmware d'origine, comme pour l'Horloge). Le jeu est arrêté par SIGSTOP (marche pour RetroArch comme pour les
émulateurs autonomes) et repris par SIGCONT ; tant qu'il est figé, il ne redessine plus : l'alerte est écrite dans
la page affichée de l'écran (/dev/fb0, double tampon : yoffset), sans changer sa résolution, puis l'image du jeu
est remise. Les touches de toutes les manettes sont prises (EVIOCGRAB) : le jeu ne reçoit pas le A qui ferme
l'alerte. SIGTERM (bouton « Reprendre » du Manager) ferme l'alerte de la même façon.

  python3 break_screen.py <pid du jeu> <textes en JSON> [dossier de polices…]
  Aperçu sur un ordinateur :  python3 break_screen.py --preview alerte.png '<textes>' [dossier] [640x480]
"""

import glob
import json
import os
import signal
import struct
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PID_FILE = "/tmp/romkade-break.pid"
SHELL = (5, 12, 28)
PANEL = (11, 28, 53)
PANEL_2 = (16, 38, 66)
LINE = (35, 67, 98)
INK = (245, 248, 255)
INK_2 = (169, 189, 211)
INK_3 = (138, 161, 187)
CYAN = (17, 217, 245)
PINK = (255, 67, 181)
A_GREEN = (120, 200, 90)
ROTATED = {"RG28xx": 90}  # écran monté de travers (board.ini)
KEYS_RESUME = (304, 315)  # A (BTN_SOUTH), START
EVIOCGRAB = 0x40044590
IGNORE_SECONDS = 1.5  # touches ignorées au début : le joueur appuie encore sur les boutons du jeu


class Fonts:
    def __init__(self, dirs: list[str]):
        files = [f for d in dirs for f in sorted(glob.glob(os.path.join(d, "*.ttf")))]
        self.bold = next((f for f in files if "bold" in f.lower()), files[0] if files else None)
        self.regular = next((f for f in files if "bold" not in f.lower()), self.bold)

    def get(self, size: int, bold: bool = False):
        path = self.bold if bold else self.regular
        try:
            return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
        except (OSError, TypeError):
            return ImageFont.load_default()


def wrap(d: ImageDraw.ImageDraw, text: str, f, width: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        test = f"{cur} {word}".strip()
        if cur and d.textlength(test, font=f) > width:
            lines.append(cur)
            cur = word
        else:
            cur = test
    return lines + [cur] if cur else lines


def render(texts: dict, fonts: Fonts, size=(640, 480)) -> Image.Image:
    w, h = size
    s = min(w / 640, h / 480)

    def sc(v: float) -> int:
        return round(v * s)

    img = Image.new("RGB", (w, h), SHELL)
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((w * 0.55, -h * 0.45, w * 1.25, h * 0.35), fill=(10, 95, 120))
    g.ellipse((-w * 0.30, h * 0.55, w * 0.40, h * 1.30), fill=(110, 25, 80))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(70)), 0.55)
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, w, 32):
        d.line((x, 0, x, h), fill=(*CYAN, 10))
    for y in range(0, h, 32):
        d.line((0, y, w, y), fill=(*CYAN, 10))

    def centered(y: float, text: str, f, fill) -> None:
        d.text(((w - d.textlength(text, font=f)) / 2, y), text, font=f, fill=fill)

    # Sablier néon rose ; contenu centré verticalement sur les écrans carrés (CubeXX)
    y0 = (h - sc(480)) // 2
    cx, top = w / 2, y0 + sc(46)
    hw, hh = sc(26), sc(70)
    halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    sand = [(cx - hw, top), (cx + hw, top), (cx, top + hh / 2), (cx + hw, top + hh), (cx - hw, top + hh), (cx, top + hh / 2)]
    hd.line(sand + [sand[0]], fill=(*PINK, 220), width=sc(8), joint="curve")
    img.paste(halo.filter(ImageFilter.GaussianBlur(sc(8))), (0, 0), halo.filter(ImageFilter.GaussianBlur(sc(8))))
    d = ImageDraw.Draw(img, "RGBA")
    d.line(sand + [sand[0]], fill=PINK, width=sc(3), joint="curve")
    d.polygon([(cx - hw * 0.55, top + hh * 0.22), (cx + hw * 0.55, top + hh * 0.22), (cx, top + hh / 2)], fill=PINK)
    d.polygon([(cx, top + hh * 0.62), (cx + hw * 0.7, top + hh - sc(4)), (cx - hw * 0.7, top + hh - sc(4))], fill=PINK)

    y = top + hh + sc(22)
    centered(y, texts.get("kicker", "PAUSE"), fonts.get(sc(15), True), CYAN)
    y += sc(28)
    ft = fonts.get(sc(34), True)
    for line in wrap(d, texts.get("title", ""), ft, w - sc(60)):
        centered(y, line, ft, INK)
        y += sc(42)
    fg = fonts.get(sc(20))
    for line in wrap(d, texts.get("game", ""), fg, w - sc(80))[:2]:
        centered(y, line, fg, INK_2)
        y += sc(26)
    y += sc(6)
    fb = fonts.get(sc(17))
    for line in wrap(d, texts.get("body", ""), fb, w - sc(90)):
        centered(y, line, fb, INK_3)
        y += sc(23)

    # Bouton « A  Reprendre la partie », cadre néon cyan
    fa = fonts.get(sc(21), True)
    label = texts.get("resume", "Reprendre la partie")
    bw = d.textlength(label, font=fa) + sc(90)
    by = max(y + sc(18), y0 + sc(372))
    box = ((w - bw) / 2, by, (w + bw) / 2, by + sc(54))
    halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).rounded_rectangle(box, sc(27), outline=(*CYAN, 200), width=sc(6))
    halo = halo.filter(ImageFilter.GaussianBlur(sc(10)))
    img.paste(halo, (0, 0), halo)
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle(box, sc(27), fill=PANEL_2, outline=CYAN, width=2)
    r = sc(15)
    kx, ky = box[0] + sc(18) + r, by + sc(27)
    d.ellipse((kx - r, ky - r, kx + r, ky + r), fill=PANEL, outline=A_GREEN, width=2)
    fk = fonts.get(sc(17), True)
    d.text((kx - d.textlength("A", font=fk) / 2, ky - sc(11)), "A", font=fk, fill=A_GREEN)
    d.text((kx + r + sc(14), by + sc(13)), label, font=fa, fill=INK)
    foot = texts.get("foot", "")
    if foot:
        d.line((sc(24), h - sc(40), w - sc(24), h - sc(40)), fill=LINE, width=1)
        centered(h - sc(31), foot, fonts.get(sc(14)), INK_3)
    return img


# ---------- écran ----------
class Framebuffer:
    """Page affichée de /dev/fb0, telle quelle (résolution, profondeur et ordre des couleurs du jeu en cours)."""

    def __init__(self):
        from fcntl import ioctl
        self.fd = os.open("/dev/fb0", os.O_RDWR)
        v = bytearray(160)
        ioctl(self.fd, 0x4600, v)  # FBIOGET_VSCREENINFO
        self.xres, self.yres, _, _, self.xoff, self.yoff, self.bpp = struct.unpack_from("7I", v)
        self.offsets = [struct.unpack_from("2I", v, 32 + 12 * i) for i in range(3)]  # rouge, vert, bleu
        f = bytearray(68)
        ioctl(self.fd, 0x4602, f)  # FBIOGET_FSCREENINFO
        self.stride = struct.unpack_from("I", f, 48)[0]
        self.start = self.yoff * self.stride
        try:
            board = Path("/mnt/vendor/oem/board.ini").read_text().split()[0]
        except (OSError, IndexError):
            board = ""
        self.rotate = ROTATED.get(board, 0)

    @property
    def size(self):
        return (self.yres, self.xres) if self.rotate else (self.xres, self.yres)

    def snapshot(self) -> bytes:
        os.lseek(self.fd, self.start, 0)
        return os.read(self.fd, self.yres * self.stride)

    def restore(self, data: bytes) -> None:
        os.lseek(self.fd, self.start, 0)
        os.write(self.fd, data)

    def show(self, img: Image.Image) -> None:
        if self.rotate:
            img = img.rotate(self.rotate, expand=True)
        img = img.convert("RGB")
        step = self.bpp // 8
        if self.bpp == 32:
            r, g, b = img.split()
            chans = [Image.new("L", img.size, 255) for _ in range(4)]
            for ch, (off, _) in zip((r, g, b), self.offsets):
                chans[off // 8] = ch
            rows = Image.merge("RGBA", chans).tobytes()
        elif self.bpp == 16:
            out = bytearray(self.xres * self.yres * 2)
            (ro, rn), (go, gn), (bo, bn) = self.offsets
            for i, (r, g, b) in enumerate(img.getdata()):
                p = (r >> (8 - rn)) << ro | (g >> (8 - gn)) << go | (b >> (8 - bn)) << bo
                out[2 * i:2 * i + 2] = p.to_bytes(2, "little")
            rows = bytes(out)
        else:
            raise OSError(f"écran en {self.bpp} bits")
        line = self.xres * step
        if self.stride == line:
            self.restore(rows)
        else:
            for y in range(self.yres):
                os.lseek(self.fd, self.start + y * self.stride + self.xoff * step, 0)
                os.write(self.fd, rows[y * line:(y + 1) * line])


def open_keys() -> list[int]:
    """Toutes les manettes et claviers (console, manette USB, relais réseau), pris en exclusivité si possible."""
    from fcntl import ioctl
    fds = []
    for path in sorted(glob.glob("/dev/input/event*")):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            ioctl(fd, EVIOCGRAB, 1)
        except OSError:
            pass
        fds.append(fd)
    return fds


def pressed(fds: list[int]) -> list[int]:
    keys = []
    for fd in fds:
        try:
            while True:
                data = os.read(fd, 24 * 16)
                if not data:
                    break
                for i in range(0, len(data) - 23, 24):
                    _s, _u, etype, code, value = struct.unpack("llHHi", data[i:i + 24])
                    if etype == 1 and value == 1:
                        keys.append(code)
        except (BlockingIOError, OSError):
            pass
    return keys


def run(game_pid: int, texts: dict, font_dirs: list[str]) -> None:
    def stop(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    Path(PID_FILE).write_text(str(os.getpid()))
    fb = before = None
    fds: list[int] = []
    try:
        if game_pid:
            os.kill(game_pid, signal.SIGSTOP)
            time.sleep(0.15)  # dernière image du jeu affichée avant de dessiner par-dessus
        fb = Framebuffer()
        before = fb.snapshot()
        fb.show(render(texts, Fonts(font_dirs), fb.size))
        fds = open_keys()
        shown = time.time()
        while True:
            keys = pressed(fds)
            if time.time() - shown > IGNORE_SECONDS and any(k in KEYS_RESUME for k in keys):
                break
            if game_pid and not os.path.exists(f"/proc/{game_pid}"):
                break
            time.sleep(0.1)
    finally:
        from fcntl import ioctl
        for fd in fds:
            try:
                ioctl(fd, EVIOCGRAB, 0)
            except OSError:
                pass
            os.close(fd)
        if fb is not None and before is not None:
            fb.restore(before)
        if game_pid:
            try:
                os.kill(game_pid, signal.SIGCONT)
            except OSError:
                pass
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


def main() -> None:
    if sys.argv[1] == "--preview":
        out, texts = sys.argv[2], json.loads(sys.argv[3])
        dirs = sys.argv[4:5]
        size = tuple(int(v) for v in sys.argv[5].split("x")) if len(sys.argv) > 5 else (640, 480)
        render(texts, Fonts(dirs), size).save(out)
        return
    run(int(sys.argv[1] or 0), json.loads(sys.argv[2]), sys.argv[3:])


if __name__ == "__main__":
    main()
