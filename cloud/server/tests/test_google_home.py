"""Google Home : connexion du compte par le relais d'autorisation (PKCE vers Supabase), SYNC, QUERY, EXECUTE."""

import asyncio
import base64
import hashlib
import os
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

os.environ["ROMKADE_FETCH_CHEATS"] = "0"

from romkade_cloud import catalog  # noqa: E402
from romkade_cloud.app import create_app  # noqa: E402
from romkade_cloud.relay import ConsoleOffline, Relay  # noqa: E402
from romkade_cloud.store import Store  # noqa: E402

FILES = [["NES", "Legend of Zelda, The (USA).nes", 131088], ["MD", "Sonic The Hedgehog (USA, Europe).md", 524288]]
GOOGLE = "https://oauth-redirect.googleusercontent.com/r/romkade-home"


class FakeAuth:
    url = "https://sb.example"
    issuer = "https://sb.example/auth/v1"
    publishable_key = "pk"
    metadata_url = "https://sb.example/.well-known/oauth-authorization-server/auth/v1"

    def verify(self, token):
        return {"sub": "u-1", "email": "a@b.c", "role": "authenticated"} if token == "sb-access" else None


class FakeRelay(Relay):
    def __init__(self, online=True):
        super().__init__()
        self.calls, self.up, self.volume = [], online, 40

    def online(self, console_id):
        return self.up

    async def call(self, console_id, action, params=None, timeout=45):
        if not self.up:
            raise ConsoleOffline("offline", "endormie")
        self.calls.append((action, params))
        return {"volume": {"percent": self.volume}} if action == "status" else {"result": "ok"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ROMKADE_GOOGLE_CLIENT_ID", "google-id")
    monkeypatch.setenv("ROMKADE_GOOGLE_CLIENT_SECRET", "google-secret")
    monkeypatch.setenv("ROMKADE_GOOGLE_SUPABASE_CLIENT_ID", "sb-client")
    store, relay = Store(tmp_path / "c.sqlite3"), FakeRelay()
    store.ensure_account("sb:u-1", "a@b.c")
    c, secret = store.register_console_for("sb:u-1", {"model": "RG35xxPRO", "agent_version": "0.4.0"}, "RG35XX")
    store.replace_catalog(c.id, catalog.build(FILES), FILES, catalog.VERSION)
    app = create_app(store, relay, "https://mcp.romkade.com", FakeAuth())
    supabase_calls = []

    def supabase(request: httpx.Request):
        supabase_calls.append(dict(parse_qs(request.content.decode())))
        return httpx.Response(200, json={"access_token": "sb-access", "refresh_token": "sb-refresh", "expires_in": 3600})

    app.app.app.state.google.transport = httpx.MockTransport(supabase)  # AccountPath -> CrossOrigin -> Starlette
    return {"app": app, "store": store, "relay": relay, "console": c, "secret": secret, "supabase": supabase_calls}


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcp.romkade.com")


def test_account_linking_adds_pkce_for_supabase(env):
    asyncio.run(_test_account_linking_adds_pkce_for_supabase(env))


async def _test_account_linking_adds_pkce_for_supabase(env):
    async with client(env["app"]) as h:
        assert (await h.get("/google/authorize", params={"client_id": "other", "redirect_uri": GOOGLE})).status_code == 400
        assert (await h.get("/google/authorize", params={"client_id": "google-id",
                                                         "redirect_uri": "https://evil.example/cb"})).status_code == 400
        r = await h.get("/google/authorize", params={"client_id": "google-id", "redirect_uri": GOOGLE,
                                                      "state": "g-state", "response_type": "code"})
        assert r.status_code == 302
        to_supabase = urlparse(r.headers["location"])
        q = {k: v[0] for k, v in parse_qs(to_supabase.query).items()}
        assert to_supabase.path == "/auth/v1/oauth/authorize" and q["client_id"] == "sb-client"
        assert q["redirect_uri"] == "https://mcp.romkade.com/google/callback" and q["code_challenge_method"] == "S256"

        back = await h.get("/google/callback", params={"code": "sb-code", "state": q["state"]})
        to_google = urlparse(back.headers["location"])
        gq = {k: v[0] for k, v in parse_qs(to_google.query).items()}
        assert back.headers["location"].startswith(GOOGLE) and gq["state"] == "g-state" and gq["code"] != "sb-code"

        bad = await h.post("/google/token", data={"grant_type": "authorization_code", "code": gq["code"],
                                                  "client_id": "google-id", "client_secret": "wrong"})
        assert bad.status_code == 401
        basic = base64.b64encode(b"google-id:google-secret").decode()
        t = await h.post("/google/token", data={"grant_type": "authorization_code", "code": gq["code"]},
                         headers={"authorization": f"Basic {basic}"})
        assert t.json() == {"token_type": "Bearer", "access_token": "sb-access", "expires_in": 3600,
                            "refresh_token": "sb-refresh"}
        sent = {k: v[0] for k, v in env["supabase"][0].items()}
        assert sent["code"] == "sb-code" and sent["client_id"] == "sb-client"
        assert base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"].encode()).digest()).rstrip(b"=").decode() \
            == q["code_challenge"]
        # Code à usage unique ; le jeton se renouvelle par Supabase.
        again = await h.post("/google/token", data={"grant_type": "authorization_code", "code": gq["code"]},
                             headers={"authorization": f"Basic {basic}"})
        assert again.status_code == 400
        refresh = await h.post("/google/token", data={"grant_type": "refresh_token", "refresh_token": "sb-refresh",
                                                      "client_id": "google-id", "client_secret": "google-secret"})
        assert refresh.json()["access_token"] == "sb-access"


def test_sync_query_execute(env):
    asyncio.run(_test_sync_query_execute(env))


async def _test_sync_query_execute(env):
    c = env["console"]
    auth = {"authorization": "Bearer sb-access"}
    async with client(env["app"]) as h:
        assert (await h.post("/google/fulfillment", json={}, headers={"authorization": "Bearer x"})).status_code == 401
        sync = (await h.post("/google/fulfillment", headers=auth, json={
            "requestId": "1", "inputs": [{"intent": "action.devices.SYNC"}]})).json()
        assert sync["payload"]["agentUserId"] == "sb:u-1"
        dev = sync["payload"]["devices"][0]
        assert dev["id"] == c.id and dev["type"] == "action.devices.types.STREAMING_BOX"
        assert dev["name"]["name"] == "RG35XX" and "Console" in dev["name"]["nicknames"]
        zelda = next(a for a in dev["attributes"]["availableApplications"]
                     if "Zelda" in a["names"][0]["name_synonym"][-1])
        assert "Zelda" in zelda["names"][0]["name_synonym"]

        assert dev["attributes"]["availableApplications"][0]["key"] == "menu"   # console sur son menu
        query = (await h.post("/google/fulfillment", headers=auth, json={"requestId": "2", "inputs": [
            {"intent": "action.devices.QUERY", "payload": {"devices": [{"id": c.id}, {"id": "nope"}]}}]})).json()
        assert query["payload"]["devices"][c.id]["online"] is True
        assert query["payload"]["devices"][c.id]["currentApplication"] == "menu"   # toujours une app de la liste
        assert query["payload"]["devices"]["nope"]["errorCode"] == "deviceNotFound"

        def execute(command, params):
            return {"requestId": "3", "inputs": [{"intent": "action.devices.EXECUTE", "payload": {"commands": [
                {"devices": [{"id": c.id}], "execution": [{"command": f"action.devices.commands.{command}",
                                                           "params": params}]}]}}]}

        by_key = (await h.post("/google/fulfillment", headers=auth, json=execute("appSelect", {"newApplication": zelda["key"]}))).json()
        assert by_key["payload"]["commands"][0]["status"] == "SUCCESS"
        assert env["relay"].calls[-1] == ("launch", {"platform_dir": "NES", "relative_path": "Legend of Zelda, The (USA).nes", "slot": None})
        # Nom prononcé hors de la liste : cherché dans tout le catalogue.
        await h.post("/google/fulfillment", headers=auth, json=execute("appSelect", {"newApplicationName": "sonic"}))
        assert env["relay"].calls[-1][1]["platform_dir"] == "MD"
        none = (await h.post("/google/fulfillment", headers=auth, json=execute("appSelect", {"newApplicationName": "tetris"}))).json()
        assert none["payload"]["commands"][0]["errorCode"] == "noAvailableApp"

        await h.post("/google/fulfillment", headers=auth, json=execute("OnOff", {"on": False}))
        assert env["relay"].calls[-1] == ("quit", None)
        env["relay"].volume = 0                                                        # son à 0 : 0 + 80 = 80
        await h.post("/google/fulfillment", headers=auth, json=execute("volumeRelative", {"volumeRelativeLevel": 80}))
        assert env["relay"].calls[-1] == ("volume", {"percent": 80, "muted": False})
        env["relay"].volume = 40
        rel = (await h.post("/google/fulfillment", headers=auth, json=execute(
            "volumeRelative", {"relativeSteps": 80, "volumeRelativeLevel": 30}))).json()
        assert env["relay"].calls[-1] == ("volume", {"percent": 70, "muted": False})       # 40 + 30, pas 40 + 800
        assert rel["payload"]["commands"][0]["status"] == "SUCCESS"
        vol = (await h.post("/google/fulfillment", headers=auth, json=execute("volumeRelative", {"relativeSteps": -2}))).json()
        assert env["relay"].calls[-1] == ("volume", {"percent": 20, "muted": False})
        assert vol["payload"]["commands"][0]["states"]["currentVolume"] == 20

        env["relay"].up = False
        off = (await h.post("/google/fulfillment", headers=auth, json=execute("appSelect", {"newApplication": zelda["key"]}))).json()
        assert off["payload"]["commands"][0]["errorCode"] == "deviceOffline"



class FakeHomeGraph:
    ready = True

    def __init__(self):
        self.syncs, self.states = [], []

    async def request_sync(self, agent_user_id):
        self.syncs.append(agent_user_id)
        return True

    async def report_state(self, agent_user_id, states):
        self.states.append((agent_user_id, states))
        return True


def test_recent_games_and_automatic_updates(env, monkeypatch):
    asyncio.run(_test_recent_games_and_automatic_updates(env, monkeypatch))


async def _test_recent_games_and_automatic_updates(env, monkeypatch):
    from romkade_cloud import google_home

    monkeypatch.setattr(google_home, "SYNC_DELAY", 0)
    google = env["app"].app.app.state.google
    graph = google.homegraph = FakeHomeGraph()
    c, auth = env["console"], {"authorization": "Bearer sb-access"}
    async with client(env["app"]) as h:
        # Pas encore relié à Google : rien n'est envoyé.
        r = await h.post("/agent/recent", json={"recent": [["MD", "Sonic The Hedgehog (USA, Europe).md"]]},
                         headers={"authorization": f"Bearer {env['secret']}"})
        assert r.json() == {"recent": 1}
        await asyncio.sleep(0.05)
        assert graph.syncs == []
        sync = (await h.post("/google/fulfillment", headers=auth, json={
            "requestId": "1", "inputs": [{"intent": "action.devices.SYNC"}]})).json()
        apps = sync["payload"]["devices"][0]["attributes"]["availableApplications"]
        assert "Sonic The Hedgehog" in apps[1]["names"][0]["name_synonym"]        # joué récemment : juste après le menu
        # Relié : un favori ajouté -> Google redemande la liste ; un jeu lancé -> état signalé.
        await h.post("/agent/favorites", json={"favorites": [["NES", "Legend of Zelda, The (USA).nes"]]},
                     headers={"authorization": f"Bearer {env['secret']}"})
        await asyncio.sleep(0.05)
        assert graph.syncs == ["sb:u-1"]
        await h.post("/google/fulfillment", headers=auth, json={"requestId": "2", "inputs": [
            {"intent": "action.devices.EXECUTE", "payload": {"commands": [{"devices": [{"id": c.id}], "execution": [
                {"command": "action.devices.commands.appSelect", "params": {"newApplicationName": "zelda"}}]}]}}]})
        await asyncio.sleep(0.05)
        assert graph.states[-1][1][c.id]["online"] is True and "playbackState" in graph.states[-1][1][c.id]
        await h.post("/google/fulfillment", headers=auth, json={"requestId": "3", "inputs": [
            {"intent": "action.devices.DISCONNECT"}]})
        assert not env["store"].google_linked("sb:u-1")


def test_account_linking_survives_a_restart(env):
    asyncio.run(_test_account_linking_survives_a_restart(env))


async def _test_account_linking_survives_a_restart(env):
    async with client(env["app"]) as h:
        r = await h.get("/google/authorize", params={"client_id": "google-id", "redirect_uri": GOOGLE, "state": "s"})
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    # Serveur redéployé pendant que l'utilisateur se connecte : la connexion continue.
    restarted = create_app(env["store"], env["relay"], "https://mcp.romkade.com", FakeAuth())
    async with client(restarted) as h:
        back = await h.get("/google/callback", params={"code": "sb-code", "state": state})
        assert back.status_code == 302 and back.headers["location"].startswith(GOOGLE)
        assert (await h.get("/google/callback", params={"code": "sb-code", "state": state})).status_code == 400


def test_homegraph_signs_with_the_service_account():
    asyncio.run(_test_homegraph_signs_with_the_service_account())


async def _test_homegraph_signs_with_the_service_account():
    import json

    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from romkade_cloud.homegraph import HomeGraph

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    account = {"client_email": "home@romkade.iam.gserviceaccount.com", "private_key": pem, "private_key_id": "k1",
               "token_uri": "https://oauth2.googleapis.com/token"}
    seen = []

    def google(request: httpx.Request):
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            assertion = parse_qs(request.content.decode())["assertion"][0]
            claims = jwt.decode(assertion, key.public_key(), algorithms=["RS256"], audience=account["token_uri"])
            assert claims["iss"] == account["client_email"] and "homegraph" in claims["scope"]
            return httpx.Response(200, json={"access_token": "g-token", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer g-token"
        return httpx.Response(200, json={})

    graph = HomeGraph(base64.b64encode(json.dumps(account).encode()).decode(), httpx.MockTransport(google))
    assert await graph.request_sync("sb:u-1")
    assert await graph.report_state("sb:u-1", {"c1": {"online": True}})
    assert [r.url.path for r in seen] == ["/token", "/v1/devices:requestSync", "/v1/devices:reportStateAndNotification"]
    assert not HomeGraph().ready

    # Liaison retirée côté Google : 404 -> le compte n'est plus considéré comme relié.
    gone = []

    def unlinked(request: httpx.Request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "g-token", "expires_in": 3600})
        return httpx.Response(404, json={"error": {"message": "Third-party user cannot be found."}})

    graph = HomeGraph(base64.b64encode(json.dumps(account).encode()).decode(), httpx.MockTransport(unlinked))
    graph.on_unlinked = gone.append
    assert not await graph.report_state("sb:ancien", {"c1": {"online": True}})
    assert gone == ["sb:ancien"]


def test_offline_and_back_online_are_reported(env):
    asyncio.run(_test_offline_and_back_online_are_reported(env))


async def _test_offline_and_back_online_are_reported(env):
    google = env["app"].app.app.state.google
    graph = google.homegraph = FakeHomeGraph()
    env["store"].set_google_link("sb:u-1", True)
    c = env["console"]
    task = asyncio.create_task(google.watch_online(every=0.02))
    await asyncio.sleep(0.05)
    env["relay"].up = False                       # console en veille
    await asyncio.sleep(0.08)
    assert graph.states[-1][1][c.id] == {"online": False}
    env["relay"].up = True                        # console revenue
    await asyncio.sleep(0.08)
    assert graph.states[-1][1][c.id]["online"] is True
    task.cancel()
