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

    def fake_generate(model, f):
        seen["params"] = ctl.params_for(f)
        return ctl.parse(Msg(json.dumps(ANSWER)))

    monkeypatch.setattr(ctl, "generate", fake_generate)
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        game = (await c.get("/api/games", params={"platform": "SFC"})).json()["items"][0]
        r = await c.get(f"/api/games/{game['id']}/controls")
        assert r.json() == {"status": "none", "origin": None, "controls": [], "notes": None, "updated_at": None,
                            "can_generate": True}

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
