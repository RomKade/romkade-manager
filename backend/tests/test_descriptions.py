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


async def test_api_key_and_start(app_factory, monkeypatch, no_llm_env):
    monkeypatch.setattr(d, "load_state", lambda: [])
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.put("/api/settings/llm/key", json={"provider": "anthropic", "api_key": "pas-une-cle"})).status_code == 422
        r = await c.post("/api/descriptions/start")
        assert r.status_code == 409 and r.json()["error"]["code"] == "llm_none"
        # Une clé Anthropic suffit (réglage d'avant le choix du fournisseur) : Claude devient l'IA par défaut.
        key = {"provider": "anthropic", "api_key": "sk-ant-api03-" + "x" * 40}
        assert (await c.put("/api/settings/llm/key", json=key)).json()["provider"] == "anthropic"
        st = (await c.get("/api/descriptions")).json()
        assert st["credentials"] and st["model"] == "claude-opus-5-5" and st["batch"] and st["batches"] == []
        assert st["estimate_usd"] is not None


async def test_describe_one_game_proposes_then_saves_once_validated(app_factory, monkeypatch):
    """Un seul jeu, tout de suite (test avant le lot) ; modèle local sans réflexion préalable."""
    import json as _json

    from tests.test_catalog import sync

    from app.db.models import GameText
    from app.services import llm

    seen = []
    answers = iter([{"known": True, "en": "A platformer.", "fr": "Un jeu de plateforme.", "es": "Un plataformas."},
                    {"known": True, "en": "Mario's quest.", "fr": "La quête de Mario.", "es": "La búsqueda de Mario."}])

    def handler(request):
        body = _json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": _json.dumps(next(answers))},
                                                      "finish_reason": "stop"}]})

    model = llm.LLM(llm.PROVIDERS["local"], "qwen-test", "http://localhost:11434/v1", None,
                    transport=httpx.MockTransport(handler))
    monkeypatch.setattr(llm, "resolve", lambda state: model)
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        game = (await c.get("/api/games", params={"platform": "SFC"})).json()["items"][0]
        r = await c.post(f"/api/games/{game['id']}/description")
        assert r.status_code == 200, r.text
        draft = r.json()
        assert draft["mode"] == "translate" and seen[0]["reasoning_effort"] == "none"
        assert draft["texts"]["fr"] == {"text": "Un jeu de plateforme.", "origin": "translated"}
        assert draft["texts"]["en"]["origin"] == "source"
        # Une proposition n'est pas enregistrée : la fiche ne change qu'une fois validée.
        with app.state.sessions() as s:
            assert s.query(GameText).count() == 0
        save = {"mode": draft["mode"], "model": draft["model"], "known": draft["known"],
                "texts": {k: v["text"] for k, v in draft["texts"].items()}}
        assert (await c.put(f"/api/games/{game['id']}/description", json=save)).json() == {"texts": 3}
        # À nouveau : le français et l'espagnol de l'IA sont remplacés, le résumé anglais d'origine est gardé.
        draft = (await c.post(f"/api/games/{game['id']}/description")).json()
        save["texts"] = {k: v["text"] for k, v in draft["texts"].items()}
        assert (await c.put(f"/api/games/{game['id']}/description", json=save)).json() == {"texts": 2}
    with app.state.sessions() as s:
        texts = {t.lang: (t.text, t.origin) for t in s.query(GameText)}
    assert texts["fr"] == ("La quête de Mario.", "translated") and texts["en"][1] == "source" and len(texts) == 3
