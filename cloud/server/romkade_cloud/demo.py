"""Console de démonstration, pour les relecteurs des annuaires d'apps (Claude, ChatGPT) et les présentations.

Les relecteurs n'ont pas de console : celle-ci est simulée dans le serveur. Elle répond au relais comme l'agent d'une
vraie console (état, lancement, son, sauvegardes), toujours en ligne. Sa bibliothèque ne contient que des homebrews
diffusés librement par leurs auteurs : aucun jeu du commerce, et aucun fichier, seulement des noms (comme une vraie
console, qui n'envoie que la liste de ses fichiers).

    python -m romkade_cloud demo-console demo@romkade.com    # rattache la console de démo à ce compte

Le compte est créé d'abord par une connexion normale (romkade.com/authentification) ; la commande accepte l'adresse
e-mail du compte ou son identifiant (sb:…). Les consoles de démo sont marquées `"demo": true` dans leurs infos ; le
serveur les fait tourner (`run_all`). Leur état (jeu en cours, son, sauvegardes) vit en mémoire et repart à zéro au
redémarrage.
"""

import asyncio
import logging
import time

from . import catalog
from .relay import Relay
from .store import Console, Store

log = logging.getLogger("romkade.demo")

INFO = {"demo": True, "model": "RG35XX Pro", "firmware": "ROMKADE demo", "profile": "demo", "agent_version": "demo",
        "capabilities": {"launch": True, "resume_slot": True, "quit": True, "save_state": True, "volume": True}}
NAME = "ROMKADE Demo"

# Homebrews gratuits (téléchargement libre chez leurs auteurs), avec les infos que les bases du Manager n'ont pas.
GAMES = [
    ("GB", "Tobu Tobu Girl (World) (Aftermarket) (Unl).gb", {
        "genre": "plateforme", "year": 2017, "developer": "Tangram Games",
        "description": "Arcade platformer: help Kumiko bounce from cloud to cloud to catch her runaway cat. "
                       "Free and open-source Game Boy homebrew."}),
    ("GB", "Deadeus (World) (Aftermarket) (Unl).gb", {
        "genre": "aventure", "year": 2019, "developer": "IZMA",
        "description": "Horror adventure on the original Game Boy: a boy dreams that his village will be destroyed "
                       "in three days. Free homebrew."}),
    ("GBC", "uCity (World) (Aftermarket) (Unl).gbc", {
        "title": "µCity", "genre": "simulation", "year": 2017, "developer": "AntonioND",
        "description": "City-building simulation for the Game Boy Color, with zoning, budget and disasters. "
                       "Open-source homebrew."}),
    ("GBA", "Anguna (World) (Aftermarket) (Unl).gba", {
        "genre": "aventure", "year": 2008, "developer": "Nathan Tolbert",
        "description": "Top-down action-adventure: escape a dungeon full of monsters, find keys and items. "
                       "Freeware Game Boy Advance homebrew."}),
    ("FC", "Alter Ego (World) (Aftermarket) (Unl).nes", {
        "genre": "reflexion", "year": 2011,
        "description": "Puzzle platformer: the hero and his mirrored alter ego move together; swap places to "
                       "collect every pixie. Freeware NES homebrew."}),
    ("FC", "Lan Master (World) (Aftermarket) (Unl).nes", {
        "genre": "reflexion", "year": 2011, "developer": "Shiru",
        "description": "Puzzle game: rotate network cables to connect every computer to the server. "
                       "Freeware NES homebrew."}),
    ("FC", "Blade Buster (World) (Aftermarket) (Unl).nes", {
        "genre": "shmup", "year": 2011, "developer": "High Level Challenge",
        "description": "Caravan-style vertical shoot 'em up: score as much as possible in a few minutes. "
                       "Freeware NES homebrew."}),
    ("FC", "Super Tilt Bro. (World) (Aftermarket) (Unl).nes", {
        "genre": "combat", "developer": "sgadrat",
        "description": "Platform fighting game for two players on the NES. Open-source homebrew."}),
    ("MD", "Old Towers (World) (Aftermarket) (Unl).md", {
        "genre": "reflexion", "year": 2019, "developer": "RetroSouls",
        "description": "Puzzle action in ancient towers: the hero never stops walking, plan his path to grab "
                       "every coin. Free Mega Drive homebrew."}),
]
FAVORITES = [("GBA", "Anguna (World) (Aftermarket) (Unl).gba"), ("GB", "Tobu Tobu Girl (World) (Aftermarket) (Unl).gb")]


def build_catalog() -> tuple[list[dict], list[list]]:
    files = [[d, f, 1 << 20] for d, f, _ in GAMES]
    extra = {(d, f): x for d, f, x in GAMES}
    games = catalog.build(files)
    for g in games:
        g.update(extra.get((g["platform_dir"], g["relative_path"]), {}))
    return games, files


def find_account(store: Store, who: str) -> str | None:
    for a in store.accounts():
        if who in (a["id"], a["label"]):
            return a["id"]
    return None


def setup(store: Store, account_id: str) -> Console:
    """Console de démo du compte (créée la première fois), avec sa bibliothèque et ses favoris."""
    c = next((c for c in store.consoles_of(account_id) if c.info.get("demo")), None)
    if c is None:
        c, _ = store.register_console_for(account_id, INFO, NAME)
    games, files = build_catalog()
    # Version hors d'atteinte : rebuild_catalogs ne la recalcule pas (il perdrait les infos ajoutées ici).
    store.replace_catalog(c.id, games, files, version=1 << 30)
    store.replace_favorites(c.id, [list(f) for f in FAVORITES])
    return store.console(c.id)


class DemoConsole:
    """Répond aux ordres du relais comme romkade_agent.py, sur une console imaginaire."""

    def __init__(self, relay: Relay, console_id: str):
        self.relay, self.console_id = relay, console_id
        self.playing: dict | None = None
        self.volume, self.muted = 60, False
        day = 86400
        self.saves = [  # sauvegardes déjà « sur la carte », pour que game_details en montre
            {"name": "tobu tobu girl (world) (aftermarket) (unl)", "platform": "GB", "kind": "sram",
             "modified": time.time() - 2 * day},
            {"name": "anguna (world) (aftermarket) (unl)", "platform": "GBA", "kind": "sram",
             "modified": time.time() - day},
            {"name": "anguna (world) (aftermarket) (unl)", "platform": "GBA", "kind": "state", "slot": 0,
             "modified": time.time() - day + 600},
        ]

    async def run(self) -> None:
        while True:
            cmd = await self.relay.poll(self.console_id, wait=25)
            if cmd:
                self.relay.result(self.console_id, cmd["id"], {"id": cmd["id"], **self.handle(cmd)})

    def handle(self, cmd: dict) -> dict:
        action, p = cmd["action"], cmd.get("params") or {}
        if action == "status":
            g = self.playing or {}
            return ok({"playing": bool(g), "menu": not g, "process": "retroarch" if g else None,
                       "platform_dir": g.get("platform_dir"), "relative_path": g.get("relative_path"),
                       "volume": {"percent": self.volume, "muted": self.muted}})
        if action == "launch":
            self.playing = {"platform_dir": p.get("platform_dir"), "relative_path": p.get("relative_path")}
            return ok({"launching": p.get("relative_path")})
        if action == "quit":
            if not self.playing:
                return ok({"result": "none"})
            self.save("sram")
            self.playing = None
            return ok({"result": "quit"})
        if action == "save_state":
            if not self.playing:
                return fail("no_retroarch_game", "No RetroArch game is running on the console.")
            self.save("state")
            return ok({"saved": True})
        if action == "volume":
            if p.get("percent") is not None:
                self.volume = int(p["percent"])
            if p.get("muted") is not None:
                self.muted = bool(p["muted"])
            return ok({"percent": self.volume, "muted": self.muted})
        if action == "saves":
            names = {str(n).lower() for n in p.get("names") or []}
            return ok({"saves": [s for s in self.saves if not names or s["name"] in names]})
        if action == "rescan":
            return ok({"rescanned": True})
        return fail("unknown_action", f"Unknown action: {action}")

    def save(self, kind: str) -> None:
        name = self.playing["relative_path"].rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        self.saves = [s for s in self.saves if not (s["name"] == name and s["kind"] == kind)]
        self.saves.append({"name": name, "platform": self.playing["platform_dir"], "kind": kind,
                           "slot": 0 if kind == "state" else None, "modified": time.time()})


def ok(result: dict) -> dict:
    return {"ok": True, "result": result}


def fail(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


async def run_all(store: Store, relay: Relay, every: float = 60) -> None:
    """Fait tourner les consoles de démo, y compris celles ajoutées pendant que le serveur tourne."""
    running: dict[str, asyncio.Task] = {}
    try:
        while True:
            for c in store.demo_consoles():
                if c.id not in running or running[c.id].done():
                    running[c.id] = asyncio.create_task(DemoConsole(relay, c.id).run())
                    log.info("console de démo %s en ligne", c.id)
            await asyncio.sleep(every)
    finally:
        for t in running.values():
            t.cancel()
