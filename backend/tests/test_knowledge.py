import asyncio
from urllib.parse import parse_qs, urlparse

import httpx

from app.services import knowledge as kn
from tests.test_catalog import games, sync

WIKI_TEXT = """Super Mario World is a 1990 platform game.

== Gameplay ==
""" + "Mario runs and jumps through Dinosaur Land, rides Yoshi and finds secret exits. " * 40 + """

== References ==
""" + "Some citation. " * 80

GUIDE_TEXT = "== Walkthrough ==\n" + "Take the pipe, then use the cape to fly over the castle wall in Vanilla Dome. " * 30


def entity(qid, p31, platforms, sitelinks=None, label="Super Mario World", guide=None):
    claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": p31}}}}],
              "P400": [{"mainsnak": {"datavalue": {"value": {"id": p}}}} for p in platforms]}
    if guide:
        claims["P9075"] = [{"mainsnak": {"datavalue": {"value": guide}}}]
    return {"id": qid, "claims": claims, "labels": {"en": {"value": label}}, "aliases": {},
            "sitelinks": {k: {"title": v} for k, v in (sitelinks or {}).items()}}


def wiki_mock(calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        calls.append((url.netloc, q.get("action"), q.get("titles") or q.get("search") or q.get("ids")))
        assert request.headers["User-Agent"].startswith("ROMKADE-Manager")
        if url.netloc == "www.wikidata.org":
            if q["action"] == "wbsearchentities":
                hits = [{"id": "Q9080572"}, {"id": "Q853143"}, {"id": "Q7642607"}] if "Mario" in q["search"] else []
                return httpx.Response(200, json={"search": hits})
            ids = q["ids"].split("|")
            if "Q183259" in ids:  # libellés des plateformes
                return httpx.Response(200, json={"entities": {
                    "Q183259": {"labels": {"en": {"value": "Super Nintendo Entertainment System"}},
                                "aliases": {"en": [{"value": "SNES"}]}},
                    "Q10676": {"labels": {"en": {"value": "Mega Drive"}}, "aliases": {}}}})
            return httpx.Response(200, json={"entities": {
                "Q9080572": entity("Q9080572", "Q2910554", ["Q10676"]),             # jeu pirate
                "Q853143": entity("Q853143", "Q7889", ["Q183259"], {"enwiki": "Super Mario World",
                                                                    "frwiki": "Super Mario World"},
                                  guide="Super_Mario_World"),
                "Q7642607": entity("Q7642607", "Q5398426", []),                      # série télé
            }})
        if url.netloc.endswith("wikipedia.org"):
            return httpx.Response(200, json={"query": {"pages": [{"title": q["titles"], "extract": WIKI_TEXT}]}})
        if url.netloc == "strategywiki.org":
            if q.get("list") == "allpages":
                return httpx.Response(200, json={"query": {"allpages": [
                    {"title": "Super Mario World/Controls"}, {"title": "Super Mario World/Vanilla Dome"},
                    {"title": "Super Mario World/Walkthrough"}]}})
            return httpx.Response(200, json={"query": {"pages": [{"title": q["titles"], "extract": GUIDE_TEXT}]}})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_chunks_skip_references_and_split():
    chunks = kn.chunk_extract(WIKI_TEXT, "Super Mario World")
    # introduction trop courte, références ignorées, section de 560 mots coupée en deux passages
    assert [s for s, _ in chunks] == ["Gameplay", "Gameplay"]
    assert all(len(t.split()) <= kn.CHUNK_WORDS for _, t in chunks)


def test_platform_and_title_matching():
    ours = kn.platform_names("SFC")
    assert {"snes", "super nintendo"} <= ours
    assert kn.platform_matches(ours, ["Super Nintendo Entertainment System"])
    assert not kn.platform_matches(ours, ["Mega Drive", "Sega Genesis"])
    assert kn.platform_matches(kn.platform_names("FBNEO"), ["arcade video game machine"])
    assert kn.title_score("Super Mario World", ["Super Mario World"]) == 1.0


async def test_fetch_one_game_then_search(app_factory, monkeypatch):
    monkeypatch.setattr(kn, "PAUSE", 0)
    calls = []
    app = app_factory()
    app.state.knowledge.fetcher.transport = wiki_mock(calls)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        mario = next(g for g in (await games(c, platform="SFC"))["items"] if g["title"] == "Super Mario World")
        assert (await c.get(f"/api/games/{mario['id']}/knowledge")).json()["status"] == "none"

        r = await c.post(f"/api/games/{mario['id']}/knowledge")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "found"
        assert {(s["source"], s["lang"]) for s in body["sources"]} >= {("wikipedia", "en"), ("wikipedia", "fr"),
                                                                       ("strategywiki", "en")}
        assert all(s["license"] == "CC BY-SA 4.0" for s in body["sources"])
        assert any("Controls" in (t or "") for _, _, t in calls)  # page des commandes : sert aussi à la fiche
        assert "Gameplay" in body["sections"]

        hits = (await c.get(f"/api/games/{mario['id']}/knowledge/search", params={"q": "castle Vanilla Dome cape"})).json()
        assert hits and hits[0]["source"] == "strategywiki" and "Vanilla Dome" in hits[0]["excerpt"]

        status = (await c.get("/api/knowledge")).json()
        assert status["found"] == 1 and status["chunks"] == body["chunks"] and status["pending"] == status["games"] - 1


async def test_unknown_game_is_not_found_then_batch_and_auto(app_factory, monkeypatch):
    monkeypatch.setattr(kn, "PAUSE", 0)
    app = app_factory()
    app.state.knowledge.fetcher.transport = wiki_mock([])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        sonic = next(g for g in (await games(c))["items"] if g["title"].startswith("Sonic"))
        assert (await c.post(f"/api/games/{sonic['id']}/knowledge")).json()["status"] == "not_found"

        assert (await c.put("/api/knowledge/settings", json={"auto_after_sync": True})).json()["auto_after_sync"]
        await app.state.knowledge.after_sync()  # comme à la fin d'une synchronisation
        for _ in range(100):
            if not app.state.knowledge.running():
                break
            await asyncio.sleep(0.02)
        status = (await c.get("/api/knowledge")).json()
        assert status["pending"] == 0 and status["found"] >= 1 and not status["job"]["running"]
