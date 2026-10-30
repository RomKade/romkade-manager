import base64
import io
import re
import zipfile

import httpx

from app.services import cheats as ch
from app.services import llm
from tests.test_assistant import events, fake_llm
from tests.test_catalog import sync

SNES = "Nintendo - Super Nintendo Entertainment System"


def fake_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{SNES}/Super Mario World (USA).cht", 'cheats = 2\n\ncheat0_desc = "Infinite lives"\n'
                   'cheat0_code = "7E0DBE:63"\ncheat0_enable = false\n\ncheat1_desc = "Always have cape"\n'
                   'cheat1_code = "7E0019:02"\ncheat1_enable = false\n')
        z.writestr(f"{SNES}/Super Mario World (USA) (Game Genie).cht", 'cheats = 1\ncheat0_desc = "Start with 9 lives"\n'
                   'cheat0_code = "DD6A-1F0D"\n')
        z.writestr(f"{SNES}/Super Mario World (Rumbles).cht", 'cheat0_desc = "Rumble"\ncheat0_address = "1"\n'
                   'cheat0_value = "1"\ncheat0_handler = "1"\n')
        z.writestr("FBNeo - Arcade Games/1941.cht", 'cheat0_desc = "inf energy p1"\ncheat0_address = "3492"\n'
                   'cheat0_value = "7"\ncheat0_handler = "1"\n')
    return buf.getvalue()


def test_parse_ranking_and_memory_codes():
    idx = ch.CheatIndex([f"{SNES}/Batman Returns (Japan) (En).cht", f"{SNES}/Batman Returns (USA).cht",
                         f"{SNES}/Batman Returns (World) (Game Genie).cht", f"{SNES}/Batman Returns (Rumbles).cht"])
    # Jeu européen : pas de fichier de sa région ; USA d'abord, le japonais à la fin, les vibrations jamais.
    assert [ch.label_of(n) for n in idx.files_for("SFC", "Batman Returns (Europe).sfc")] == [
        "USA", "World · Game Genie", "Japan · En"]
    assert ch.parse('cheat0_desc = "x"\ncheat0_address = "12"\ncheat0_value = "7"\ncheat0_handler = "1"\n'
                    'cheat1_desc = "vide"\ncheat1_code = ""\n') == [{"desc": "x", "code": "12=7"}]


def test_subset_keeps_chosen_codes_enabled():
    text = ('cheats = 3\n\ncheat0_desc = "vide"\ncheat0_code = ""\n\ncheat1_desc = "Lives"\ncheat1_code = "AA"\n'
            'cheat1_enable = false\n\ncheat2_desc = "Jump"\ncheat2_address = "12"\ncheat2_value = "7"\n'
            'cheat2_handler = "1"\ncheat2_repeat_count = "1"\n')
    # Positions de la liste affichée (le code vide n'y est pas) : « Jump » seul, renuméroté et activé
    out = ch.subset(text, [1])
    assert out.startswith("cheats = 1\n") and 'cheat0_desc = "Jump"' in out and 'cheat0_repeat_count = "1"' in out
    assert "cheat0_enable = true" in out and "Lives" not in out and "cheat1" not in out
    assert ch.parse(ch.subset(text, [1, 0, 1, 9])) == [{"desc": "Jump", "code": "12=7"}, {"desc": "Lives", "code": "AA"}]


async def test_download_list_install_and_assistant(app_factory, monkeypatch, tmp_path):
    monkeypatch.setenv("ROMKADE_DATA_DIR", str(tmp_path / "data"))
    data = fake_zip()
    app = app_factory()
    commands = []

    async def runner(client, command, timeout=20):
        commands.append(command)
        return 0, "OK:/.config/retroarch/cheats/x/Super Mario World (USA).cht\n"

    app.state.device_runner = runner
    real_download = ch.download
    monkeypatch.setattr(ch, "download", lambda: real_download(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=data))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        game = next(g for g in (await c.get("/api/games", params={"platform": "SFC"})).json()["items"]
                    if g["title"].startswith("Super Mario World"))
        assert (await c.get(f"/api/games/{game['id']}/cheats")).json()["available"] is False
        st = (await c.post("/api/cheats/download")).json()
        assert st["available"] and st["files"] == 3 and st["license"] == "CC BY-SA 4.0"

        out = (await c.get(f"/api/games/{game['id']}/cheats")).json()
        assert [f["label"] for f in out["files"]] == ["USA", "USA · Game Genie"] and out["can_install"]
        assert out["files"][0]["cheats"][0] == {"desc": "Infinite lives", "code": "7E0DBE:63"}

        bad = await c.post(f"/api/games/{game['id']}/cheats/install", json={"name": "FBNeo - Arcade Games/1941.cht"})
        assert bad.status_code == 404 and commands == []
        r = await c.post(f"/api/games/{game['id']}/cheats/install", json={"name": out["files"][1]["name"]})
        assert r.status_code == 200, r.text
        assert "cheat_database_path" in commands[0] and f"'{SNES}'" in commands[0] and "base64 -d" in commands[0]
        # Un seul code : le fichier copié n'a que lui
        r = await c.post(f"/api/games/{game['id']}/cheats/install", json={"name": out["files"][0]["name"], "only": [1]})
        assert r.status_code == 200, r.text
        sent = base64.b64decode(re.search(r"echo (\S+) \| base64 -d", commands[1]).group(1)).decode()
        assert ch.parse(sent) == [{"desc": "Always have cape", "code": "7E0019:02"}]

        model, seen = fake_llm({"in_scope": True, "intent": "game_help", "search": "cheat codes", "games_mentioned": [],
                                "wants_solution": False}, ["Vies infinies : 7E0DBE:63\nSource: RetroArch"])
        monkeypatch.setattr(llm, "resolve", lambda state: model)
        r = await c.post("/api/assistant", json={"scope": "game", "game_id": game["id"], "lang": "fr",
                                                 "messages": [{"role": "user", "content": "Des codes de triche ?"}]})
        meta = events(r.text)[0][1]
        assert meta["sources"][0] == {"source": "retroarch", "page": "USA", "url": ch.SOURCE_URL, "license": "CC BY-SA 4.0"}
        system = seen["answers"][0]["messages"][0]["content"]
        assert "[RetroArch cheats · USA · 2 codes]" in system and "- Infinite lives: 7E0DBE:63" in system
