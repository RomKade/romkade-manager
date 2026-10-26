"""Captures de l'interface ROMKADE (MCP Apps) pour les annuaires d'apps (Claude, ChatGPT).

Tout tourne en local, sans compte ni console : un serveur ROMKADE Cloud temporaire (base jetable), la console de
démonstration (demo_console.py, homebrews gratuits, aucune jaquette) branchée dessus, les vrais outils MCP appelés par
un client, puis le widget (ui://romkade/app.html) affiché dans une page hôte (host.html) qui joue le rôle de Claude :
même dialogue MCP Apps (ui/initialize, tool-result), thème sombre, anglais. Une capture par vue, recadrée sur le
widget, 720 px de large en double densité : PNG de 1 440 px.

    cd cloud/server
    .venv/bin/pip install playwright && .venv/bin/python -m playwright install chromium
    .venv/bin/python ../../docs/annuaire-claude/outils/captures.py      # -> docs/annuaire-claude/captures/
"""

import asyncio
import functools
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from mcp import Client
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
SERVER = HERE.parents[2] / "cloud" / "server"
OUT = HERE.parent / "captures"
THEME = os.environ.get("THEME", "dark")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cli(env: dict, *args: str) -> str:
    return subprocess.run([sys.executable, "-m", "romkade_cloud", *args], cwd=SERVER, env=env, check=True,
                          capture_output=True, text=True).stdout


async def collect(url: str, work: Path) -> None:
    """Réponses des vrais outils (structuredContent compris) et HTML du widget."""
    async with Client(url) as mcp:
        for _ in range(60):
            c = ((await mcp.call_tool("list_consoles", {})).structured_content or {}).get("consoles") or []
            if c and c[0]["online"] and c[0]["games"]:
                break
            await asyncio.sleep(1)
        (work / "widget.html").write_text((await mcp.read_resource("ui://romkade/app.html")).contents[0].text)

        def save(name, r):
            (work / f"{name}.json").write_text(json.dumps(r.model_dump(by_alias=True, mode="json", exclude_none=True)))

        save("1-library", await mcp.call_tool("library_overview", {}))
        save("2-games", await mcp.call_tool("search_games", {"platform": "Game Boy"}))
        tobu = (await mcp.call_tool("search_games", {"query": "tobu"})).structured_content["games"][0]["game_id"]
        await mcp.call_tool("launch_game", {"game_id": tobu})
        await mcp.call_tool("save_state", {})
        await mcp.call_tool("set_volume", {"percent": 60})
        save("4-now-playing", await mcp.call_tool("console_status", {}))
        save("3-game-details", await mcp.call_tool("game_details", {"game_id": tobu}))
        save("5-favorites", await mcp.call_tool("favorite_games", {}))


async def shoot(base: str, names: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 720, "height": 1600}, device_scale_factor=2)
        for n in names:
            await page.goto(f"{base}/host.html?r={n}&theme={THEME}")
            await page.wait_for_function("window.__sent === true", timeout=15000)
            await page.wait_for_timeout(1500)
            await page.wait_for_function(
                "() => [...document.getElementById('f').contentDocument.images].every((i) => i.complete)", timeout=30000)
            await page.wait_for_timeout(800)
            await page.locator("#f").screenshot(path=str(OUT / f"{n}.png"))
            print("capture", OUT / f"{n}.png")
        await browser.close()


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="romkade-captures-"))
    port = free_port()
    env = {**os.environ, "ROMKADE_CLOUD_DB": str(work / "cloud.sqlite3"), "ROMKADE_DATA_DIR": str(work),
           "ROMKADE_PUBLIC_URL": f"http://127.0.0.1:{port}", "ROMKADE_FETCH_CHEATS": "0"}
    for k in ("ROMKADE_SUPABASE_URL", "POSTHOG_PROJECT_TOKEN"):  # pas d'OAuth ni de statistiques : adresse à jeton
        env.pop(k, None)
    url = cli(env, "new-account", "ROMKADE Demo").strip()
    account = cli(env, "accounts").split("\t", 1)[0]
    secret = cli(env, "demo-register", account).split("ROMKADE_DEMO_SECRET=", 1)[1].strip()
    procs = [subprocess.Popen([sys.executable, "-m", "romkade_cloud", "serve", "--port", str(port)], cwd=SERVER, env=env)]
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), 1).close()
                break
            except OSError:
                time.sleep(0.5)
        procs.append(subprocess.Popen([sys.executable, "-m", "romkade_cloud", "demo-console"], cwd=SERVER, env={
            **env, "ROMKADE_DEMO_SERVER": f"http://127.0.0.1:{port}", "ROMKADE_DEMO_SECRET": secret}))
        asyncio.run(collect(url, work))
        (work / "host.html").write_text((HERE / "host.html").read_text())
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(work))
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        names = ["1-library", "2-games", "3-game-details", "4-now-playing", "5-favorites"]
        asyncio.run(shoot(f"http://127.0.0.1:{httpd.server_address[1]}", names))
        httpd.shutdown()
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
