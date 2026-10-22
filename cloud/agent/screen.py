#!/usr/bin/env python3
"""Écran de l'app ROMKADE sur la console : code d'appairage, ou console connectée. © 2026 ROMKADE.

Dessiné avec Pillow et écrit directement dans l'écran (/dev/fb0), comme l'app Horloge du firmware Anbernic ;
touches lues dans /dev/input/event1. Même charte que ROMKADE Manager (bleu nuit, cyan et rose néon, vert lime
pour la console connectée), police Atkinson Hyperlegible (SIL OFL 1.1, assets/).

L'état vient de l'agent (/tmp/romkade-status.json) : l'écran se met à jour seul quand la console est appairée.
B ou MENU : retour au menu de la console.

Aperçu sur un ordinateur :  python3 screen.py --preview code.png --state '{"code": "X52A4H", "online": true}'
"""

import json
import math
import os
import struct
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
STATUS = Path("/tmp/romkade-status.json")
FB_CFG = "/mnt/mod/ctrl/configs/fb.cfg"

SHELL = (5, 12, 28)
PANEL = (11, 28, 53)
PANEL_2 = (16, 38, 66)
LINE = (35, 67, 98)
INK = (245, 248, 255)
INK_2 = (169, 189, 211)
INK_3 = (138, 161, 187)
CYAN = (17, 217, 245)
PINK = (255, 67, 181)
LIME = (183, 236, 75)
WARN = (245, 184, 74)

# Écran de chaque modèle (board.ini) : largeur, hauteur, rotation. Les autres : 640 x 480.
BOARDS = {"RGcubexx": (720, 720, 0), "RG34xx": (720, 480, 0), "RG34xxSP": (720, 480, 0), "RG28xx": (640, 480, 90)}
KEY_A, KEY_B, KEY_MENU = 304, 305, 312
EVIOCGRAB = 0x40044590  # accès exclusif aux touches (le menu de la console ne les reçoit plus)

TEXT = {
    "fr": {"code": "CODE D'APPAIRAGE", "where": "Dans ChatGPT ou Claude, avec le connecteur ROMKADE :",
           "say": "« Connecte ma console, code {code} »", "valid": "Valable encore {min} min",
           "connected": "Console connectée", "games": "jeux", "available": "disponibles dans ChatGPT et Claude",
           "try": "Essaie :", "ex1": "« Lance Sonic sur ma console »", "ex2": "« Des codes de triche pour Contra ? »",
           "connecting": "Connexion au cloud ROMKADE", "offline": "Pas de connexion au cloud",
           "offline_hint": "Vérifie que le Wi-Fi est activé, puis rouvre l'app.", "back": "Retour",
           "updated": "App ROMKADE mise à jour", "installed": "App ROMKADE installée", "version": "Version {v}", "linked": "Reliée à ton compte ROMKADE", "ready": "Pilotable depuis ChatGPT et Claude", "close": "Fermer"},
    "en": {"code": "PAIRING CODE", "where": "In ChatGPT or Claude, with the ROMKADE connector:",
           "say": "“Connect my console, code {code}”", "valid": "Valid for {min} more min",
           "connected": "Console connected", "games": "games", "available": "available in ChatGPT and Claude",
           "try": "Try:", "ex1": "“Launch Sonic on my console”", "ex2": "“Cheat codes for Contra?”",
           "connecting": "Connecting to ROMKADE cloud", "offline": "No connection to the cloud",
           "offline_hint": "Check that Wi-Fi is on, then open the app again.", "back": "Back",
           "updated": "ROMKADE app updated", "installed": "ROMKADE app installed", "version": "Version {v}", "linked": "Linked to your ROMKADE account", "ready": "Ready to drive from ChatGPT and Claude", "close": "Close"},
    "es": {"code": "CÓDIGO DE EMPAREJAMIENTO", "where": "En ChatGPT o Claude, con el conector ROMKADE:",
           "say": "«Conecta mi consola, código {code}»", "valid": "Válido {min} min más",
           "connected": "Consola conectada", "games": "juegos", "available": "disponibles en ChatGPT y Claude",
           "try": "Prueba:", "ex1": "«Inicia Sonic en mi consola»", "ex2": "«¿Trucos para Contra?»",
           "connecting": "Conectando con la nube ROMKADE", "offline": "Sin conexión con la nube",
           "offline_hint": "Comprueba que el Wi-Fi está activado y vuelve a abrir la app.", "back": "Volver",
           "updated": "App ROMKADE actualizada", "installed": "App ROMKADE instalada", "version": "Versión {v}", "linked": "Conectada a tu cuenta ROMKADE", "ready": "Lista para controlar desde ChatGPT y Claude", "close": "Cerrar"},
}
LANGS = ["zh", "zh", "en", "ja", "ko", "es", "ru", "de", "fr", "pt"]  # /mnt/vendor/oem/language.ini


def app_version() -> str:
    """Version de l'app, écrite par le Manager qui l'installe (fichier VERSION à côté de l'agent)."""
    try:
        return (HERE / "VERSION").read_text().strip()
    except OSError:
        return ""


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "AtkinsonHyperlegible-Bold.ttf" if bold else "AtkinsonHyperlegible-Regular.ttf"
    try:
        return ImageFont.truetype(str(ASSETS / name), size)
    except OSError:
        return ImageFont.load_default()


def system_lang() -> str:
    try:
        lang = LANGS[int(Path("/mnt/vendor/oem/language.ini").read_text().split()[0])]
    except (OSError, ValueError, IndexError):
        lang = "en"
    return lang if lang in TEXT else "en"


def mix(a, b, t: float):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


# ---------- dessin ----------
def background(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), SHELL)
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((w * 0.55, -h * 0.45, w * 1.25, h * 0.35), fill=(10, 95, 120))
    g.ellipse((-w * 0.30, -h * 0.40, w * 0.40, h * 0.30), fill=(110, 25, 80))
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    img = Image.blend(img, glow, 0.55)
    grid = ImageDraw.Draw(img, "RGBA")
    for x in range(0, w, 32):
        grid.line((x, 0, x, h), fill=(*CYAN, 10))
    for y in range(0, h, 32):
        grid.line((0, y, w, y), fill=(*CYAN, 10))
    return img


def neon_box(img: Image.Image, box, color, radius: int = 14, glow: int = 10, width: int = 2, fill=PANEL) -> None:
    """Cadre néon (Manager : --glow-cyan) : halo flou sous un rectangle arrondi."""
    halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).rounded_rectangle(box, radius, outline=(*color, 200), width=width + 4)
    halo = halo.filter(ImageFilter.GaussianBlur(glow))
    img.paste(halo, (0, 0), halo)
    ImageDraw.Draw(img).rounded_rectangle(box, radius, fill=fill, outline=color, width=width)


def centered(d: ImageDraw.ImageDraw, w: int, y: int, text: str, f, fill) -> None:
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2, y), text, font=f, fill=fill)


def paste_asset(img: Image.Image, name: str, center_x: int, top: int, width: int) -> int:
    """Colle une image d'assets/ ; renvoie sa hauteur."""
    try:
        a = Image.open(ASSETS / name).convert("RGBA")
    except OSError:
        return 0
    a = a.resize((width, round(a.height * width / a.width)), Image.LANCZOS)
    img.paste(a, (round(center_x - a.width / 2), top), a)
    return a.height


def render(state: dict, lang: str, size=(640, 480), tick: int = 0) -> Image.Image:
    w, h = size
    s = w / 640 if w / 640 < h / 480 else h / 480  # échelle : écran de référence 640 x 480
    T = TEXT.get(lang, TEXT["en"])
    img = background(w, h)
    d = ImageDraw.Draw(img)
    cx = w // 2
    top = round(18 * s) + (h - round(480 * s)) // 2
    logo_h = paste_asset(img, "romkade-logo.png", cx, top, round(250 * s))
    y = top + logo_h + round(14 * s)
    sc = lambda v: round(v * s)  # noqa: E731

    status = state.get("status")
    if status == "connecting":
        dots = "." * (1 + tick % 3)
        r = sc(26)
        cy = y + sc(90)
        for i in range(12):
            a = (i / 12) * 2 * math.pi + tick * 0.5
            alpha = (i + 1) / 12
            px, py = cx + math.cos(a) * r, cy + math.sin(a) * r
            d.ellipse((px - sc(4), py - sc(4), px + sc(4), py + sc(4)), fill=mix(SHELL, CYAN, alpha))
        centered(d, w, cy + sc(50), T["connecting"] + dots, font(sc(24), True), INK)
    elif status == "offline":
        neon_box(img, (sc(70), y + sc(40), w - sc(70), y + sc(190)), WARN, glow=12)
        d = ImageDraw.Draw(img)
        centered(d, w, y + sc(70), "!", font(sc(44), True), WARN)
        centered(d, w, y + sc(122), T["offline"], font(sc(26), True), INK)
        centered(d, w, y + sc(158), T["offline_hint"], font(sc(17)), INK_2)
    elif status in ("updated", "installed"):  # juste après une installation ou une mise à jour par le Manager
        r = sc(34)
        cy = y + sc(58)
        halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse((cx - r - sc(10), cy - r - sc(10), cx + r + sc(10), cy + r + sc(10)), fill=(*LIME, 150))
        halo = halo.filter(ImageFilter.GaussianBlur(sc(12)))
        img.paste(halo, (0, 0), halo)
        d = ImageDraw.Draw(img)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=LIME)
        d.line((cx - sc(15), cy + sc(1), cx - sc(4), cy + sc(13), cx + sc(17), cy - sc(12)), fill=SHELL, width=sc(7), joint="curve")
        centered(d, w, cy + r + sc(18), T[status], font(sc(32), True), INK)
        ver = state.get("version") or app_version()
        if ver:
            f = font(sc(18), True)
            label = T["version"].format(v=ver)
            tw = d.textlength(label, font=f)
            yv = cy + r + sc(66)
            d.rounded_rectangle((cx - tw / 2 - sc(14), yv - sc(4), cx + tw / 2 + sc(14), yv + sc(28)), sc(16),
                                fill=PANEL_2, outline=CYAN, width=1)
            centered(d, w, yv, label, f, CYAN)
        yy = cy + r + sc(116)
        centered(d, w, yy, T["linked"] + (f" · {state['name']}" if state.get("name") else ""), font(sc(18)), INK_2)
        centered(d, w, yy + sc(30), T["ready"], font(sc(18), True), PINK)
    elif status == "paired":
        r = sc(9)
        title = T["connected"]
        f = font(sc(32), True)
        tw = d.textlength(title, font=f)
        x0 = cx - (tw + sc(26)) / 2
        halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse((x0 - r * 2, y + sc(20) - r * 2, x0 + r * 4, y + sc(20) + r * 4), fill=(*LIME, 160))
        halo = halo.filter(ImageFilter.GaussianBlur(sc(8)))
        img.paste(halo, (0, 0), halo)
        d = ImageDraw.Draw(img)
        d.ellipse((x0, y + sc(20), x0 + r * 2, y + sc(20) + r * 2), fill=LIME)
        d.text((x0 + sc(26), y + sc(8)), title, font=f, fill=INK)
        centered(d, w, y + sc(54), state.get("name") or "", font(sc(22), True), CYAN)
        if state.get("games"):
            neon_box(img, (sc(110), y + sc(96), w - sc(110), y + sc(176)), PINK, glow=12, fill=PANEL)
            d = ImageDraw.Draw(img)
            num = fmt(int(state["games"]))
            fn, fl = font(sc(40), True), font(sc(22), True)
            total = d.textlength(num, font=fn) + sc(10) + d.textlength(T["games"], font=fl)
            x = cx - total / 2
            d.text((x, y + sc(102)), num, font=fn, fill=PINK)
            d.text((x + d.textlength(num, font=fn) + sc(10), y + sc(118)), T["games"], font=fl, fill=INK)
            centered(d, w, y + sc(150), T["available"], font(sc(15)), INK_2)
        yy = y + sc(196)
        centered(d, w, yy, T["try"], font(sc(16)), INK_3)
        for i, ex in enumerate((T["ex1"], T["ex2"])):
            f2 = font(sc(18), True)
            tw = d.textlength(ex, font=f2)
            box = (cx - tw / 2 - sc(16), yy + sc(26 + i * 44), cx + tw / 2 + sc(16), yy + sc(60 + i * 44))
            d.rounded_rectangle(box, sc(17), fill=PANEL_2, outline=LINE, width=1)
            centered(d, w, yy + sc(32 + i * 44), ex, f2, INK)
    else:  # code d'appairage
        code = (state.get("code") or "------")[:6]
        centered(d, w, y + sc(8), T["code"], font(sc(17), True), INK_2)
        bw, bh, gap = sc(70), sc(84), sc(12)
        x0 = cx - (6 * bw + 5 * gap) / 2
        by = y + sc(40)
        for i, ch in enumerate(code.ljust(6)):
            color = mix(CYAN, PINK, i / 5)
            box = (round(x0 + i * (bw + gap)), by, round(x0 + i * (bw + gap) + bw), by + bh)
            neon_box(img, box, color, radius=sc(12), glow=sc(9))
            d = ImageDraw.Draw(img)
            f = font(sc(54), True)
            tw = d.textlength(ch, font=f)
            d.text((box[0] + (bw - tw) / 2, by + sc(8)), ch, font=f, fill=INK)
        yy = by + bh + sc(26)
        centered(d, w, yy, T["where"], font(sc(17)), INK_2)
        say = T["say"].format(code=code)
        f2 = font(sc(21), True)
        tw = d.textlength(say, font=f2)
        d.rounded_rectangle((cx - tw / 2 - sc(18), yy + sc(30), cx + tw / 2 + sc(18), yy + sc(70)), sc(20),
                            fill=PANEL_2, outline=LINE, width=1)
        centered(d, w, yy + sc(37), say, f2, INK)
        left = state.get("code_until")
        if left:
            mins = max(0, math.ceil((left - time.time()) / 60))
            centered(d, w, yy + sc(84), T["valid"].format(min=mins), font(sc(16)), INK_3)

    # Pied : touche B (jaune, comme sur la console) et droits.
    fy = h - (h - round(480 * s)) // 2 - sc(40)
    d.line((sc(24), fy - sc(10), w - sc(24), fy - sc(10)), fill=LINE, width=1)
    d.ellipse((sc(24), fy, sc(24) + sc(24), fy + sc(24)), fill=PANEL_2, outline=(230, 200, 60), width=2)
    centered_in = font(sc(14), True)
    d.text((sc(24) + (sc(24) - d.textlength("B", font=centered_in)) / 2, fy + sc(3)), "B", font=centered_in,
           fill=(230, 200, 60))
    d.text((sc(56), fy + sc(2)), T["close"] if status in ("updated", "installed") else T["back"], font=font(sc(15)), fill=INK_2)
    ver = app_version()
    rights = (f"v{ver} · " if ver else "") + "© 2026 ROMKADE · romkade.com"
    fr = font(sc(14))
    d.text((w - sc(24) - d.textlength(rights, font=fr), fy + sc(3)), rights, font=fr, fill=INK_3)
    return img


# ---------- écran et touches de la console ----------
class Screen:
    def __init__(self):
        try:
            board = Path("/mnt/vendor/oem/board.ini").read_text().split()[0]
        except (OSError, IndexError):
            board = ""
        self.w, self.h, self.rotate = BOARDS.get(board, (640, 480, 0))
        self.fd = os.open("/dev/fb0", os.O_RDWR)
        try:
            from fcntl import ioctl
            if os.path.exists(FB_CFG):  # même remise à zéro que l'Horloge (résolution changée par un jeu)
                ioctl(self.fd, 0x4601, bytearray(Path(FB_CFG).read_bytes()))
            ioctl(self.fd, 0x4611, 0)
        except OSError:
            pass
        import mmap
        self.mm = mmap.mmap(self.fd, self.w * self.h * 4)

    @property
    def size(self):
        return (self.h, self.w) if self.rotate else (self.w, self.h)

    def show(self, img: Image.Image) -> None:
        if self.rotate:
            img = img.rotate(self.rotate, expand=True)
        r, g, b = img.convert("RGB").split()
        a = Image.new("L", img.size, 255)
        self.mm.seek(0)
        self.mm.write(Image.merge("RGBA", (b, g, r, a)).tobytes())  # l'écran attend du BGRA

    def snapshot(self) -> bytes:
        self.mm.seek(0)
        return self.mm.read(self.w * self.h * 4)

    def close(self, restore: bytes | None = None) -> None:
        self.mm.seek(0)
        self.mm.write(restore if restore is not None else bytes(self.w * self.h * 4))
        self.mm.close()
        os.close(self.fd)


def read_keys(fd) -> list[int]:
    keys = []
    try:
        while True:
            data = os.read(fd, 24 * 16)
            if not data:
                break
            for i in range(0, len(data) - 23, 24):
                _s, _u, etype, code, value = struct.unpack("llHHi", data[i:i + 24])
                if etype == 1 and value == 1:
                    keys.append(code)
    except BlockingIOError:
        pass
    return keys


def current_state(started: float) -> dict:
    try:
        st = json.loads(STATUS.read_text())
    except (OSError, ValueError):
        st = {}
    fresh = st.get("at", 0) >= started - 1
    if not fresh:
        st["status"] = "connecting" if time.time() - started < 25 else "offline"
    elif not st.get("online"):
        st["status"] = "offline"
    else:
        st["status"] = "paired" if st.get("paired") else "code"
    return st


def splash(kind: str, seconds: float) -> None:
    """Écran « app installée / mise à jour » lancé par le Manager, par-dessus le menu de la console : l'image du menu
    est gardée puis remise, et les touches sont prises le temps de l'écran (le menu ne les reçoit pas). B, A ou
    MENU le ferment plus tôt."""
    lang = system_lang()
    screen = Screen()
    before = screen.snapshot()
    keys = grab = None
    try:
        keys = os.open("/dev/input/event1", os.O_RDONLY | os.O_NONBLOCK)
        from fcntl import ioctl
        ioctl(keys, EVIOCGRAB, 1)
        grab = True
    except OSError:
        pass
    end = time.time() + seconds
    last = None
    try:
        while time.time() < end:
            try:
                st = json.loads(STATUS.read_text())
            except (OSError, ValueError):
                st = {}
            state = {"status": kind if kind in ("updated", "installed") else "updated", "name": st.get("name")}
            if state != last:
                screen.show(render(state, lang, screen.size))
                last = state
            if keys is not None and any(k in (KEY_A, KEY_B, KEY_MENU) for k in read_keys(keys)):
                break
            time.sleep(0.2)
    finally:
        if keys is not None:
            if grab:
                try:
                    from fcntl import ioctl
                    ioctl(keys, EVIOCGRAB, 0)
                except OSError:
                    pass
            os.close(keys)
        screen.close(before)


def main() -> None:
    if "--preview" in sys.argv:
        out = sys.argv[sys.argv.index("--preview") + 1]
        state = json.loads(sys.argv[sys.argv.index("--state") + 1]) if "--state" in sys.argv else {}
        lang = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "fr"
        size = tuple(int(v) for v in sys.argv[sys.argv.index("--size") + 1].split("x")) if "--size" in sys.argv else (640, 480)
        render(state, lang, size).save(out)
        return
    if "--splash" in sys.argv:
        i = sys.argv.index("--splash")
        splash(sys.argv[i + 1], float(sys.argv[i + 2]) if len(sys.argv) > i + 2 else 6)
        return
    started = float(sys.argv[1]) if len(sys.argv) > 1 else time.time()
    lang = system_lang()
    screen = Screen()
    try:
        keys = os.open("/dev/input/event1", os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        keys = None
    last, tick = None, 0
    try:
        while True:
            state = current_state(started)
            key = (state.get("status"), state.get("code"), state.get("name"), state.get("games"),
                   math.ceil((state.get("code_until") or 0) - time.time()) // 60)
            if key != last or state["status"] == "connecting":
                screen.show(render(state, lang, screen.size, tick))
                last = key
            if keys is not None and any(k in (KEY_B, KEY_MENU) for k in read_keys(keys)):
                break
            tick += 1
            time.sleep(0.25)
    finally:
        screen.close()


if __name__ == "__main__":
    main()
