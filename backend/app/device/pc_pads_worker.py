"""Lecteur des manettes de l'ordinateur (SDL, par pygame-ce), dans un processus à part lancé par
app.services.pc_pads : SDL veut son propre fil principal (macOS), et une panne ici n'arrête pas le Manager.

Contrairement au navigateur (API Gamepad), SDL lit les manettes même quand l'onglet du Manager est masqué ou le
navigateur réduit : c'est tout l'intérêt. La disposition « contrôleur de jeu » de SDL est traduite dans la
disposition « standard » du navigateur (17 boutons, 4 axes), celle qu'attend déjà le relais vers la console
(app/device/gamepad.py) : rien ne change côté console.

Sortie : une ligne JSON à chaque changement, {"pads": [{"id", "name", "b": [17 valeurs 0..1], "a": [4 axes -1..1]}]}.
Fin quand l'entrée standard se ferme (le Manager s'est arrêté).
"""

import json
import os
import sys
import threading
import time

os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")  # manette lue même sans fenêtre au premier plan
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")                   # aucune fenêtre
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

HZ = 250  # lectures par seconde : la latence ajoutée reste sous 5 ms


def standard(c, pg) -> tuple[list[float], list[float]]:
    """Boutons et axes d'une manette SDL dans l'ordre de la disposition « standard » du navigateur."""
    def btn(name: str) -> float:
        return float(c.get_button(getattr(pg, f"CONTROLLER_BUTTON_{name}")))

    def axis(name: str) -> float:
        return max(-1.0, min(1.0, c.get_axis(getattr(pg, f"CONTROLLER_AXIS_{name}")) / 32767))

    buttons = [btn("A"), btn("B"), btn("X"), btn("Y"), btn("LEFTSHOULDER"), btn("RIGHTSHOULDER"),
               max(0.0, axis("TRIGGERLEFT")), max(0.0, axis("TRIGGERRIGHT")), btn("BACK"), btn("START"),
               btn("LEFTSTICK"), btn("RIGHTSTICK"), btn("DPAD_UP"), btn("DPAD_DOWN"), btn("DPAD_LEFT"),
               btn("DPAD_RIGHT"), btn("GUIDE")]
    axes = [axis("LEFTX"), axis("LEFTY"), axis("RIGHTX"), axis("RIGHTY")]
    return [round(v, 3) for v in buttons], [round(v, 3) for v in axes]


def _watch_stdin() -> None:
    sys.stdin.read()
    os._exit(0)


def main() -> None:
    try:
        import pygame as pg
        from pygame._sdl2 import controller
    except ImportError:
        print(json.dumps({"error": "pygame_missing"}), flush=True)
        return
    threading.Thread(target=_watch_stdin, daemon=True).start()
    pg.display.init()
    controller.init()
    pads: dict[int, object] = {}  # identifiant SDL de la manette → Controller
    last = None
    print(json.dumps({"ready": True}), flush=True)
    while True:
        for e in pg.event.get():
            if e.type == pg.CONTROLLERDEVICEADDED:
                try:
                    c = controller.Controller(e.device_index)
                    pads[c.as_joystick().get_instance_id()] = c
                except pg.error:
                    pass
            elif e.type == pg.CONTROLLERDEVICEREMOVED:
                pads.pop(e.instance_id, None)
        out = []
        for pid, c in list(pads.items()):
            if not c.attached():
                pads.pop(pid, None)
                continue
            b, a = standard(c, pg)
            out.append({"id": pid, "name": c.name or "Manette", "b": b, "a": a})
        if out != last:
            print(json.dumps({"pads": out}), flush=True)
            last = out
        time.sleep(1 / HZ)


if __name__ == "__main__":
    main()
