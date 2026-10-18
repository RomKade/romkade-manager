import json

import httpx

from app.services import controls as ctl
from app.services import descriptions as d


class Msg:
    def __init__(self, text, stop="end_turn"):
        self.stop_reason = stop
        self.content = [type("B", (), {"type": "text", "text": text})()]


ANSWER = {"known": True, "notes": {"fr": "Haut + B : uppercut.", "en": "Up + B: uppercut.", "es": "Arriba + B: gancho."},
          "controls": [{"button": "dpad", "fr": "Se déplacer", "en": "Move", "es": "Moverse"},
                       {"button": "b", "fr": "Coup de poing", "en": "Punch", "es": "Puñetazo"},
                       {"button": "a", "fr": "Tir", "en": "Fire", "es": "Disparo"}]}


def test_mapping_and_params():
    assert ctl.mapping_for("MD").startswith("Mega Drive") and "C = A" in ctl.mapping_for("md")
    assert ctl.mapping_for("FBNEO") == ctl.ARCADE and "button 1 = B" in ctl.ARCADE
    assert "default core mapping" in ctl.mapping_for("INCONNU")
    assert ctl.parse(Msg(json.dumps(ANSWER)))["controls"][1]["button"] == "b"
    assert ctl.parse(Msg(json.dumps({**ANSWER, "controls": []}))) is None
    assert ctl.parse(Msg("", stop="refusal")) is None


async def test_generate_store_and_edit(app_factory, monkeypatch):
    from tests.test_catalog import sync

    from app.services import llm

    monkeypatch.setattr(llm, "resolve", lambda state: llm.LLM(llm.PROVIDERS["anthropic"], "claude-opus-5-5", "x", "k"))
    seen = {}

    def fake_generate(model, f, passages=None):
        seen["params"] = ctl.params_for(f)
        return ctl.parse(Msg(json.dumps(ANSWER)))

    monkeypatch.setattr(ctl, "generate", fake_generate)
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        game = (await c.get("/api/games", params={"platform": "SFC"})).json()["items"][0]
        r = await c.get(f"/api/games/{game['id']}/controls")
        assert r.json() == {"status": "none", "origin": None, "sources": None, "controls": [], "notes": None,
                            "updated_at": None, "can_generate": True}

        r = await c.post(f"/api/games/{game['id']}/controls")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["origin"] == "written" and body["controls"][1] == {"button": "b", "fr": "Coup de poing",
                                                                        "en": "Punch", "es": "Puñetazo"}
        assert "Same letters" in seen["params"]["messages"][0]["content"]
        assert seen["params"]["output_config"]["effort"] == "medium"

        r = await c.put(f"/api/games/{game['id']}/controls",
                        json={"controls": [{"button": "y", "text": "Sauter"}], "notes": ""})
        assert r.json()["origin"] == "edited" and r.json()["notes"] is None
        assert r.json()["controls"] == [{"button": "y", "fr": "Sauter", "en": "Sauter", "es": "Sauter"}]
        assert (await c.get(f"/api/games/{game['id']}/controls")).json()["controls"][0]["button"] == "y"


async def test_generate_needs_key(app_factory, no_llm_env):
    from tests.test_catalog import sync

    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        game = (await c.get("/api/games")).json()["items"][0]
        r = await c.post(f"/api/games/{game['id']}/controls")
        assert r.status_code == 409 and r.json()["error"]["code"] == "llm_none"


async def test_generate_from_knowledge_passages(app_factory, monkeypatch):
    """Jeu jamais documenté : ses connaissances sont récupérées au clic, ses passages joints à la demande, et les
    commandes rédigées d'après eux sont marquées « sourced » avec les pages utilisées."""
    from tests.test_catalog import sync
    from tests.test_knowledge import wiki_mock

    from app.services import llm

    monkeypatch.setattr(llm, "resolve", lambda state: llm.LLM(llm.PROVIDERS["local"], "qwen2.5:7b", "x", None))
    seen = {}

    def fake_generate(model, f, passages=None):
        seen["prompt"] = ctl.prompt_for(f, passages)
        return ctl.clean({**ANSWER, "from_sources": True})

    monkeypatch.setattr(ctl, "generate", fake_generate)
    app = app_factory()
    calls = []
    app.state.knowledge.fetcher.transport = wiki_mock(calls)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        game = next(g for g in (await c.get("/api/games", params={"platform": "SFC"})).json()["items"]
                    if "Mario" in g["title"])
        r = await c.post(f"/api/games/{game['id']}/controls")
        assert r.status_code == 200, r.text
        body = r.json()
    assert calls, "connaissances récupérées au clic"
    assert "Reference passages about this game" in seen["prompt"]
    assert "[strategywiki · Super Mario World/Controls" in seen["prompt"]  # la page des commandes passe en premier
    assert body["origin"] == "sourced"
    assert body["sources"][0] == {"source": "strategywiki", "page": "Super Mario World/Controls",
                                  "url": "https://strategywiki.org/wiki/Super_Mario_World/Controls"}


def test_without_passages_prompt_is_unchanged():
    class P:
        label, directory = "Super Nintendo", "SFC"
    f = type("F", (), {"full_title": None, "title": "Jeu", "platform": P, "release_year": None, "genre": None,
                       "publisher": None, "developer": None, "description": None})()
    assert "Reference passages" not in ctl.prompt_for(f) and "Reference passages" not in ctl.prompt_for(f, [])


def test_pick_passages_keeps_only_controls():
    """Page « Controls » d'abord, puis les passages qui parlent de boutons ; intrigue et critiques écartées."""
    C = type("C", (), {})

    def chunk(page, section, text):
        c = C()
        c.page, c.section, c.text = page, section, text
        return c

    plot = chunk("Metroid", "Plot", "Samus Aran fights the Space Pirates on planet Zebes.")
    gameplay = chunk("Metroid", "Gameplay", "Press the A button to jump and the B button to fire.")
    page = chunk("Metroid/Controls", "Basics", "Movement and weapons.")
    assert ctl.pick_passages([plot, gameplay, page], [plot, gameplay]) == [page, gameplay]
    assert ctl.pick_passages([plot], [plot]) == []
