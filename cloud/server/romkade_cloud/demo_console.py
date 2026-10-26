"""Console de démonstration : une console virtuelle, toujours en ligne, pour les tests de Google (Test Suite,
certification Google Home) et les démonstrations. © 2026 ROMKADE, tous droits réservés.

Elle parle au cloud exactement comme l'app ROMKADE d'une vraie console (/agent/hello, catalog, favorites, recent,
poll, result) et répond aux mêmes ordres (status, launch, quit, save_state, volume, saves, rescan) en simulant l'état
d'une console : jeu en cours, volume, sauvegardes. Son catalogue ne contient que des jeux homebrew distribués
gratuitement par leurs auteurs (aucun jeu commercial).

Mise en place (une fois) : le compte ROMKADE de démonstration est créé sur romkade.com, puis
  python -m romkade_cloud demo-register <compte sb:…>   -> secret de la console, à mettre dans ROMKADE_DEMO_SECRET
Puis le service romkade-demo (cloud/deploy/compose.yaml) lance : python -m romkade_cloud demo-console
"""

import asyncio
import logging
import os
import time

import httpx

log = logging.getLogger("romkade.demo")

VERSION = "demo-1"
POLL_WAIT = 25
PLAY_FLAG = "/tmp/romkade-demo-play"  # fichier créé à la main (docker exec … touch) : un jeu démarre, sans la voix
# Homebrews diffusés gratuitement par leurs auteurs, sous licence libre ou en téléchargement gratuit (dossier de
# plateforme, fichier, taille) : aucun jeu vendu, aucune marque d'un autre éditeur (règle des annuaires d'apps sur la
# propriété intellectuelle). Seuls les noms existent : la console de démo n'a aucun fichier de jeu.
GAMES = [
    ["GB", "Tobu Tobu Girl (World).gb", 262144],             # Tangram Games, open source (MIT, CC BY)
    ["GB", "Deadeus (World).gb", 1048576],                   # IZMA, gratuit
    ["GB", "Libbet and the Magic Floor (World).gb", 262144],  # Damian Yerrick, open source (zlib)
    ["GB", "Sheep It Up! (World).gb", 65536],                # Dr. Ludos, gratuit
    ["NES", "Alter Ego (World).nes", 40976],                 # Shiru, freeware
    ["NES", "Lawn Mower (World).nes", 24592],                # Shiru, freeware
    ["NES", "Blade Buster (World).nes", 524304],             # High Level Challenge, freeware
    ["NES", "Nova the Squirrel (World).nes", 524304],        # NovaSquirrel, open source (GPL)
    ["NES", "Super Tilt Bro (World).nes", 524304],           # sgadrat, open source (WTFPL)
]
FAVORITES = [["GB", "Tobu Tobu Girl (World).gb"], ["NES", "Alter Ego (World).nes"], ["NES", "Nova the Squirrel (World).nes"]]


class DemoConsole:
    def __init__(self, server: str, secret: str, transport: httpx.AsyncBaseTransport | None = None):
        self.server, self.secret, self.transport = server.rstrip("/"), secret, transport
        self.playing: list[str] | None = None   # [dossier, fichier] du jeu « en cours »
        self.volume, self.muted = 60, False
        self.recent: list[list[str]] = []
        self.saved: dict[tuple, float] = {}

    async def call(self, http: httpx.AsyncClient, method: str, path: str, body=None, timeout: float = 30) -> dict:
        r = await http.request(method, self.server + path, json=body, timeout=timeout,
                               headers={"Authorization": f"Bearer {self.secret}", "User-Agent": f"romkade-agent/{VERSION}"})
        r.raise_for_status()
        return r.json() if r.content else {}

    def info(self) -> dict:
        return {"agent_version": VERSION, "hostname": "romkade-demo", "model": "ROMKADE demo console",
                "firmware": "ROMKADE (simulée)", "profile": "demo", "roms_root": "/demo/Roms",
                "capabilities": {"launch": True, "resume_slot": True, "quit": True, "save_state": True, "volume": True}}

    # ---------- ordres (mêmes réponses que l'app ROMKADE) ----------
    def handle(self, action: str, p: dict) -> dict:
        if action == "status":
            return {"playing": self.playing is not None, "menu": self.playing is None,
                    "process": "retroarch" if self.playing else None,
                    "platform_dir": self.playing[0] if self.playing else None,
                    "relative_path": self.playing[1] if self.playing else None,
                    "volume": {"percent": 0 if self.muted else self.volume, "muted": self.muted, "adjustable": True}}
        if action == "launch":
            game = [str(p.get("platform_dir") or ""), str(p.get("relative_path") or "")]
            if game not in [g[:2] for g in GAMES]:
                raise ValueError("Jeu introuvable sur la console de démonstration.")
            self.playing = game
            self.recent = [game, *[g for g in self.recent if g != game]][:30]
            return {"launching": "/demo/Roms/" + "/".join(game)}
        if action == "quit":
            was, self.playing = self.playing, None
            return {"result": "quit" if was else "none"}
        if action == "save_state":
            if not self.playing:
                raise ValueError("Aucun jeu RetroArch en cours sur la console.")
            self.saved[tuple(self.playing)] = time.time()
            return {"saved": True}
        if action == "volume":
            if p.get("percent") is not None:
                self.volume = max(0, min(100, int(p["percent"])))
            if p.get("muted") is not None:
                self.muted = bool(p["muted"])
            return {"percent": self.volume, "muted": self.muted}
        if action == "saves":
            names = {str(n).lower() for n in p.get("names") or []}
            out = [{"platform": d, "name": f.rsplit(".", 1)[0], "kind": "state", "slot": 0, "source": "retroarch",
                    "size": 4096, "modified": at} for (d, f), at in self.saved.items()
                   if not names or f.rsplit(".", 1)[0].lower() in names or f.lower() in names]
            return {"saves": out, "total": len(out)}
        if action == "rescan":
            return {"rescanned": True}
        raise ValueError(f"Action inconnue : {action}")

    async def run_once(self, http: httpx.AsyncClient) -> None:
        """Une session : présentation, catalogue, favoris, puis ordres jusqu'à une coupure."""
        await self.call(http, "POST", "/agent/hello", self.info())
        await self.call(http, "POST", "/agent/catalog", {"files": GAMES}, timeout=60)
        await self.call(http, "POST", "/agent/favorites", {"favorites": FAVORITES})
        log.info("console de démonstration en ligne (%s jeux)", len(GAMES))
        while True:
            if os.path.exists(PLAY_FLAG):  # « lance un jeu » pour la Test Suite (TransportControl), sans assistant
                os.remove(PLAY_FLAG)
                self.handle("launch", {"platform_dir": GAMES[-1][0], "relative_path": GAMES[-1][1]})
                await self.call(http, "POST", "/agent/recent", {"recent": self.recent})
                log.info("jeu lancé à la main : %s", GAMES[-1][1])
            r = await self.call(http, "GET", f"/agent/poll?wait={POLL_WAIT}", timeout=POLL_WAIT + 15)
            cmd = r.get("command")
            if r.get("resync"):
                await self.call(http, "POST", "/agent/catalog", {"files": GAMES}, timeout=60)
            if not cmd:
                continue
            before = list(self.recent)
            try:
                reply = {"id": cmd.get("id"), "ok": True, "result": self.handle(cmd.get("action"), cmd.get("params") or {})}
            except (ValueError, TypeError) as exc:
                reply = {"id": cmd.get("id"), "ok": False, "error": {"code": "demo_error", "message": str(exc)}}
            log.info("ordre %s : %s", cmd.get("action"), "ok" if reply["ok"] else reply["error"]["message"])
            await self.call(http, "POST", "/agent/result", reply)
            if self.recent != before:
                await self.call(http, "POST", "/agent/recent", {"recent": self.recent})

    async def run(self) -> None:
        backoff = 2
        async with httpx.AsyncClient(transport=self.transport) as http:
            while True:
                try:
                    await self.run_once(http)
                except Exception as exc:  # noqa: BLE001 — serveur redéployé, réseau : on se reconnecte
                    log.warning("cloud injoignable (%s) : nouvel essai dans %s s", exc, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                else:
                    backoff = 2


def main() -> None:
    secret = os.environ.get("ROMKADE_DEMO_SECRET", "")
    if not secret:  # pas encore configurée : on attend sans redémarrer en boucle
        log.warning("ROMKADE_DEMO_SECRET manquant (python -m romkade_cloud demo-register <compte>) : en attente")
        while True:
            time.sleep(3600)
    server = os.environ.get("ROMKADE_DEMO_SERVER", "http://romkade-cloud:8787")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # pas une ligne par attente d'ordre (toutes les 25 s)
    asyncio.run(DemoConsole(server, secret).run())
