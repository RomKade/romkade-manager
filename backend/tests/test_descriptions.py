import re

import httpx

from app.services import descriptions as d

GAME = {"platform_id": 1, "normalized_title": "super mario world", "title": "Super Mario World", "platform": "Super Nintendo",
        "year": 1990, "publisher": "Nintendo", "developer": "Nintendo EAD", "genre": "Plateforme", "subgenre": None, "summary": None}


def test_params_translate_or_write():
    mode, p = d.params_for({**GAME, "summary": "Mario's quest to save the princess."})
    assert mode == "translate" and p["model"] == "claude-opus-5-5" and p["output_config"]["effort"] == "low"
    assert p["output_config"]["format"]["schema"]["required"] == ["fr", "es"]
    assert "Mario's quest" in p["messages"][0]["content"]
    mode, p = d.params_for(GAME)
    assert mode == "write" and "Publisher: Nintendo" in p["messages"][0]["content"]
    assert p["output_config"]["format"]["schema"]["required"] == ["known", "en", "fr", "es"]


def test_custom_id_is_valid():
    cid = d.custom_id(12, "legend of zelda, the - a link to the past")
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cid)


class Msg:
    def __init__(self, text, stop="end_turn"):
        self.stop_reason = stop
        self.content = [type("B", (), {"type": "text", "text": text})()]


async def test_parse_and_store(app_factory):
    from tests.test_catalog import sync

    from app.db.models import GameText, Platform
    assert d.parse(Msg('{"fr": "a", "es": "b"}')) == {"fr": "a", "es": "b"}
    assert d.parse(Msg("", stop="refusal")) is None
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
    with app.state.sessions() as s:
        pid = s.query(Platform).filter_by(directory="SFC").one().id
    game = {**GAME, "platform_id": pid, "summary": "Mario's quest."}
    with app.state.sessions.begin() as s:
        assert d.store(s, game, "translate", {"fr": "La quête de Mario.", "es": "La búsqueda de Mario."}) == 3
    with app.state.sessions() as s:
        rows = {t.lang: (t.text, t.origin) for t in s.query(GameText)}
        assert d.coverage(s)["complete"] == 1
    assert rows["en"] == ("Mario's quest.", "source") and rows["fr"] == ("La quête de Mario.", "translated")


async def test_api_key_and_start(app_factory, monkeypatch):
    monkeypatch.setattr(d, "has_credentials", lambda creds: False)
    monkeypatch.setattr(d, "load_state", lambda: [])
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.put("/api/settings/anthropic", json={"api_key": "pas-une-cle"})).status_code == 422
        r = await c.post("/api/descriptions/start")
        assert r.status_code == 409 and r.json()["error"]["code"] == "anthropic_key_missing"
        assert (await c.put("/api/settings/anthropic", json={"api_key": "sk-ant-api03-" + "x" * 40})).status_code == 204
        st = (await c.get("/api/descriptions")).json()
        assert st["key_in_keychain"] and st["model"] == "claude-opus-5-5" and st["batches"] == []
