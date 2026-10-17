"""Serveur web d'EmulationStation, version labo (EmulationStation lui-même a besoin d'un écran).

Mêmes adresses que le vrai (port 1234) : POST /launch (chemin de la ROM), GET /runningGame, GET /emukill,
GET /caps. /launch exécute la commande que le vrai EmulationStation lirait dans es_systems.cfg.
"""
import json
import os
import re
import shlex
import signal
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

ES_SYSTEMS = sys.argv[1]
CORES = {"gb": "gambatte", "gbc": "gambatte", "snes": "snes9x", "megadrive": "genesis_plus_gx", "nes": "fceumm", "gba": "mgba"}
running: dict = {}


def systems():
    text = open(ES_SYSTEMS, encoding="utf-8").read()
    for block in re.findall(r"<system>(.*?)</system>", text, re.S):
        get = lambda tag: (re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S) or [None, ""])[1].strip()  # noqa: E731
        yield get("name"), get("path"), get("command")


def command_for(rom: str) -> list[str] | None:
    for name, path, command in systems():
        if path and rom.startswith(path.rstrip("/") + "/"):
            cmd = (command.replace("%ROM%", shlex.quote(rom)).replace("%SYSTEM%", name)
                   .replace("%CORE%", CORES.get(name, "")).replace("%EMULATOR%", "retroarch")
                   .replace("%CONTROLLERSCONFIG%", ""))
            return ["/bin/sh", "-c", cmd]
    return None


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode() if not isinstance(body, bytes) else body
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def _alive(self):
        p = running.get("proc")
        return p is not None and p.poll() is None

    def do_GET(self):
        if self.path == "/caps":
            return self._send(200, {"Version": "lab"})
        if self.path == "/runningGame":
            if self._alive():
                return self._send(200, {"path": running["rom"], "name": os.path.basename(running["rom"])})
            return self._send(201, {"msg": "NO GAME RUNNING"})
        if self.path == "/emukill":
            if self._alive():
                os.killpg(running["proc"].pid, signal.SIGTERM)
            return self._send(200, b"OK")
        return self._send(404, {"msg": "not found"})

    def do_POST(self):
        if self.path != "/launch":
            return self._send(404, {"msg": "not found"})
        rom = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode().strip()
        cmd = command_for(rom)
        if not cmd or not os.path.exists(rom):
            return self._send(400, {"msg": "bad rom"})
        log = open("/tmp/agm-lab-es.log", "a")
        running.update(rom=rom, proc=subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True))
        return self._send(200, b"OK")

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", 1234), Handler).serve_forever()
