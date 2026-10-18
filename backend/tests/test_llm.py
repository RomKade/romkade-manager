"""Paramètres > IA : fournisseurs, clés, modèles, test, et usage réel (commandes, descriptions) avec un faux serveur
compatible OpenAI (comme Ollama ou LM Studio)."""

import asyncio
import json

import httpx
import pytest

from app.services import llm
from tests.test_controls import ANSWER

pytestmark = pytest.mark.usefixtures("no_llm_env")


def fake_server(answer, *, schema_ok=True, models=("llama3.2:3b", "qwen2.5:7b")):
    """Faux serveur compatible OpenAI : /models, et /chat/completions qui répond `answer(body)`."""
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": m} for m in models]})
        body = json.loads(req.content)
        seen.append({"url": str(req.url), "auth": req.headers.get("authorization"), **body})
        if body["response_format"]["type"] == "json_schema" and not schema_ok:
            return httpx.Response(400, json={"error": {"message": "response_format json_schema is not supported"}})
        content = answer(body)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})

    return httpx.MockTransport(handler), seen


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_parse_json_text():
    assert llm.parse_json_text('```json\n{"ok": true}\n```') == {"ok": True}
    assert llm.parse_json_text('Voici : {"ok": true} !') == {"ok": True}
    assert llm.parse_json_text("[1, 2]") is None and llm.parse_json_text("pas du json") is None


async def test_status_keys_and_providers(app_factory):
    app = app_factory()
    async with client(app) as c:
        st = (await c.get("/api/settings/llm")).json()
        assert st["provider"] == "anthropic" and st["model"] == "claude-opus-5-5"
        assert not st["ready"] and st["problem"] == "llm_key_missing"
        assert {p["id"] for p in st["providers"]} == {"anthropic", "openai", "mistral", "gemini", "local", "custom"}
        assert st["local_presets"]["Ollama"] == "http://localhost:11434/v1"

        bad = await c.put("/api/settings/llm/key", json={"provider": "openai", "api_key": "sk-ant-pas-openai"})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "llm_key_format"
        none = await c.put("/api/settings/llm/key", json={"provider": "local", "api_key": "x" * 30})
        assert none.status_code == 422 and none.json()["error"]["code"] == "llm_key_unused"
        assert (await c.put("/api/settings/llm/key", json={"provider": "openai", "api_key": "sk-proj-" + "a" * 40})).status_code == 204

        st = (await c.put("/api/settings/llm", json={"provider": "openai"})).json()
        assert st["problem"] == "llm_no_model"  # jamais de modèle deviné hors Anthropic
        assert next(p for p in st["providers"] if p["id"] == "openai")["key_source"] == "keychain"
        st = (await c.put("/api/settings/llm", json={"provider": "openai", "model": "gpt-test"})).json()
        assert st["ready"] and st["model"] == "gpt-test"
        assert (await c.delete("/api/settings/llm/key/openai")).status_code == 204
        assert (await c.get("/api/settings/llm")).json()["problem"] == "llm_key_missing"

        assert (await c.put("/api/settings/llm", json={"provider": "custom"})).json()["problem"] == "llm_no_url"
        r = await c.put("/api/settings/llm", json={"provider": "custom", "base_url": "ftp://x"})
        assert r.status_code == 422
        assert (await c.put("/api/settings/llm", json={"provider": "nimporte"})).status_code == 422


async def test_local_model_list_test_and_fallback(app_factory):
    app = app_factory()
    transport, seen = fake_server(lambda body: '```json\n{"ok": true}\n```', schema_ok=False)
    app.state.llm_transport = transport
    async with client(app) as c:
        await c.put("/api/settings/llm", json={"provider": "local", "base_url": "http://localhost:1234/v1"})
        models = (await c.get("/api/settings/llm/models", params={"provider": "local", "base_url": "http://localhost:1234/v1"})).json()
        assert models == ["llama3.2:3b", "qwen2.5:7b"]
        st = (await c.put("/api/settings/llm", json={"provider": "local", "model": "qwen2.5:7b",
                                                      "base_url": "http://localhost:1234/v1"})).json()
        assert st["ready"] and st["base_url"] == "http://localhost:1234/v1"
        r = await c.post("/api/settings/llm/test")
        assert r.status_code == 200 and r.json()["ok"] and r.json()["model"] == "qwen2.5:7b"
        # Sans sorties structurées : nouvel essai en JSON simple, schéma dans la consigne, sans clé.
        assert [b["response_format"]["type"] for b in seen] == ["json_schema", "json_object"]
        assert seen[-1]["url"] == "http://localhost:1234/v1/chat/completions" and seen[-1]["auth"] is None
        assert "JSON schema" in seen[-1]["messages"][0]["content"] and "max_tokens" in seen[-1]


async def test_local_model_unreachable(app_factory):
    app = app_factory()

    def down(req):
        raise httpx.ConnectError("refused")

    app.state.llm_transport = httpx.MockTransport(down)
    async with client(app) as c:
        await c.put("/api/settings/llm", json={"provider": "local", "model": "llama3.2:3b"})
        r = await c.post("/api/settings/llm/test")
        assert r.status_code == 502 and r.json()["error"]["code"] == "llm_unreachable"
        assert "Ollama ou LM Studio" in r.json()["error"]["message"]


async def test_openai_controls_end_to_end(app_factory):
    from tests.test_catalog import sync

    app = app_factory()
    transport, seen = fake_server(lambda body: json.dumps(ANSWER))
    app.state.llm_transport = transport
    async with client(app) as c:
        await sync(c)
        await c.put("/api/settings/llm/key", json={"provider": "openai", "api_key": "sk-proj-" + "a" * 40})
        await c.put("/api/settings/llm", json={"provider": "openai", "model": "gpt-test"})
        game = (await c.get("/api/games", params={"platform": "SFC"})).json()["items"][0]
        assert (await c.get(f"/api/games/{game['id']}/controls")).json()["can_generate"] is True
        r = await c.post(f"/api/games/{game['id']}/controls")
        assert r.status_code == 200, r.text
        assert r.json()["controls"][1]["en"] == "Punch"
        body = seen[0]
        assert body["url"] == "https://api.openai.com/v1/chat/completions" and body["auth"].startswith("Bearer sk-proj-")
        assert body["model"] == "gpt-test" and "max_completion_tokens" in body
        assert body["response_format"]["json_schema"]["strict"] is True


async def test_descriptions_with_local_model(app_factory, monkeypatch, tmp_path):
    from app.services import descriptions as d
    from tests.test_catalog import sync

    monkeypatch.setattr(d, "_state_path", lambda: tmp_path / "state.json")
    app = app_factory()

    def answer(body):
        if body["response_format"]["json_schema"]["name"] != "description":
            return "{}"
        schema = body["response_format"]["json_schema"]["schema"]
        texts = {lang: f"Texte {lang}." for lang in ("en", "fr", "es")}
        return json.dumps({**({"known": True} if "known" in schema["properties"] else {}),
                           **{k: v for k, v in texts.items() if k in schema["properties"]}})

    transport, seen = fake_server(answer)
    app.state.llm_transport = transport
    async with client(app) as c:
        await sync(c)
        await c.put("/api/settings/llm", json={"provider": "local", "model": "llama3.2:3b"})
        st = (await c.get("/api/descriptions")).json()
        assert st["credentials"] and st["local"] and not st["batch"] and st["estimate_usd"] is None
        assert st["pending"] > 0
        r = await c.post("/api/descriptions/start")
        assert r.status_code == 200, r.text
        for _ in range(100):
            st = (await c.get("/api/descriptions")).json()
            if st["batches"] and st["batches"][0]["status"] == "ended":
                break
            await asyncio.sleep(0.05)
        assert st["batches"][0]["status"] == "ended" and st["batches"][0]["imported"]
        assert st["pending"] == 0 and st["batches"][0]["result"]["games"] > 0
        assert all(b["model"] == "llama3.2:3b" for b in seen)
