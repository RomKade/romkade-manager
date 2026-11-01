"""Jeux aimés ou non (envoyés par le Manager) et classement des plus aimés de tous les comptes."""

import asyncio
import os
import time

import httpx
import uvicorn

os.environ["ROMKADE_FETCH_CHEATS"] = "0"

from romkade_cloud.app import create_app  # noqa: E402
from romkade_cloud.relay import Relay  # noqa: E402
from romkade_cloud.store import Store  # noqa: E402

from test_cloud import FakeAuth, free_port  # noqa: E402


class Players(FakeAuth):
    """« joueur-N » : utilisateur uN."""

    def verify(self, token):
        return {"sub": f"u{token[7:]}", "role": "authenticated"} if token.startswith("joueur-") else None


def like(directory, filename, normalized, title, value=1, at=None):
    return {"platform": directory, "filename": filename, "normalized": normalized, "title": title, "value": value,
            "at": at if at is not None else time.time() - 3600}


MARIO = like("SFC", "Super Mario World (USA).sfc", "super mario world", "Super Mario World")
MARIO_EU = like("snes", "Super Mario World (Europe).sfc", "super mario world", "Super Mario World")
SONIC = like("MD", "Sonic The Hedgehog (USA, Europe).md", "sonic the hedgehog", "Sonic The Hedgehog")


def test_top_liked(tmp_path, monkeypatch):
    monkeypatch.setenv("ROMKADE_LIKES_MIN_ACCOUNTS", "2")
    store = Store(tmp_path / "cloud.sqlite3")

    async def scenario():
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(create_app(store, Relay(), public_url=base, auth=Players()),
                                               host="127.0.0.1", port=port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.02)

        def who(n):
            return {"authorization": f"Bearer joueur-{n}"}

        try:
            async with httpx.AsyncClient(base_url=base) as h:
                assert (await h.put("/api/me/likes", json={"likes": [MARIO]})).status_code == 401
                assert (await h.get("/api/likes/top")).status_code == 401
                # Une seule réaction par jeu : deux éditions du même jeu (dossier SFC ou snes), la plus récente.
                old = {**MARIO_EU, "value": -1, "at": time.time() - 7200}
                bad = [{"platform": "INCONNU", "filename": "x.zip", "normalized": "x", "title": "X", "value": 1, "at": 1},
                       {**SONIC, "value": 2}, {**SONIC, "filename": "../etc/passwd"}]
                r = await h.put("/api/me/likes", headers=who(1), json={"likes": [MARIO, old, SONIC, *bad]})
                assert r.json() == {"likes": 2}
                await h.put("/api/me/likes", headers=who(2), json={"likes": [MARIO_EU, {**SONIC, "value": -1}]})
                await h.put("/api/me/likes", headers=who(3), json={"likes": [{**SONIC, "at": time.time() - 20 * 86400}]})

                top = (await h.get("/api/likes/top?days=30", headers=who(1))).json()
                assert top["days"] == 30
                assert [(g["key"], g["likes"], g["dislikes"]) for g in top["games"]] == [
                    ("SFC/super mario world", 2, 0), ("MD/sonic the hedgehog", 2, 1)]
                mario = top["games"][0]
                assert mario["platform_code"] == "SFC" and mario["cover"].startswith(f"{base}/art/")
                # Sur 7 jours, la réaction d'il y a 20 jours ne compte pas : Sonic n'a plus que 2 comptes, 1 - 1 = 0.
                assert [g["key"] for g in (await h.get("/api/likes/top?days=7", headers=who(1))).json()["games"]] \
                    == ["SFC/super mario world"]
                assert (await h.get("/api/likes/top?days=12", headers=who(1))).status_code == 400
                # Jaquette d'un jeu qui n'est dans aucun catalogue : retrouvée parmi les jeux aimés.
                assert store.game_for_art(mario["cover"].rsplit("/", 1)[1][:-5])["platform_dir"] in ("SFC", "snes")

                # Accord retiré : tout part ; le classement suit (après son cache de 5 minutes).
                assert (await h.delete("/api/me/likes", headers=who(2))).json() == {"likes": 0}
                assert [g["key"] for g in store.top_liked(0, 10, 2)] == ["MD/sonic the hedgehog"]
                # Seuil : un jeu aimé par un seul compte n'apparaît jamais.
                assert store.top_liked(0, 10, 3) == []
                store.delete_account("sb:u1")
                assert store.top_liked(0, 10, 1)[0]["likes"] == 1
        finally:
            server.should_exit = True
            await task

    asyncio.run(scenario())
