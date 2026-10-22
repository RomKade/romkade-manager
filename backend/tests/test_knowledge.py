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


def entity(qid, p31, platforms, sitelinks=None, label="Super Mario World", guide=None, sega=None):
    claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": p31}}}}],
              "P400": [{"mainsnak": {"datavalue": {"value": {"id": p}}}} for p in platforms]}
    if guide:
        claims["P9075"] = [{"mainsnak": {"datavalue": {"value": guide}}}]
    if sega:
        claims["P7517"] = [{"mainsnak": {"datavalue": {"value": sega}}}]
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
                                  guide="Super_Mario_World", sega="Super_Mario_World"),
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
        if url.netloc == "segaretro.org":
            if q.get("list") == "allpages":
                return httpx.Response(200, json={"query": {"allpages": [
                    {"title": "Super Mario World/Hidden content"}, {"title": "Super Mario World/Magazine articles"}]}})
            html = ("<h2>Items</h2><table><tr><th>Cape Feather</th><td>Lets Mario fly over the castle wall in "
                    "Vanilla Dome and glide across long gaps between platforms.</td></tr></table>"
                    if "/" not in q["page"] else
                    "<h2>Continue mode</h2><p>On the Game Over screen, hold <img alt=\"Up\" src=\"u.png\"> and "
                    "press Start to continue from the last castle reached.</p>")
            return httpx.Response(200, json={"parse": {"title": q["page"], "text": html}})
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
        assert all(s["license"] == "CC BY-SA 4.0" for s in body["sources"] if s["source"] != "segaretro")
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


async def test_sega_retro_source_and_refresh_all(app_factory, monkeypatch):
    """Sega Retro (Wikidata P7517) : page du jeu et sous-pages utiles, licence GFDL ; « tout à nouveau »."""
    monkeypatch.setattr(kn, "PAUSE", 0)
    calls = []
    app = app_factory()
    app.state.knowledge.fetcher.transport = wiki_mock(calls)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        mario = next(g for g in (await games(c))["items"] if g["title"].startswith("Super Mario World"))
        body = (await c.post(f"/api/games/{mario['id']}/knowledge")).json()
        sega = [s for s in body["sources"] if s["source"] == "segaretro"]
        assert [s["page"] for s in sega] == ["Super Mario World", "Super Mario World/Hidden content"]
        assert {s["license"] for s in sega} == {"GFDL 1.2"}
        assert not any("Magazine" in str(x) for x in calls if x[0] == "segaretro.org" and x[1] == "parse")

        total = (await c.get("/api/knowledge")).json()["games"]
        r = await c.post("/api/knowledge/start", params={"refresh": "true"})
        assert r.status_code == 200 and r.json()["job"]["running"]  # en cours dès la réponse : bouton masqué
        again = await c.post("/api/knowledge/start")
        assert again.status_code == 409 and again.json()["error"]["code"] == "knowledge_running"
        for _ in range(200):
            if not app.state.knowledge.running():
                break
            await asyncio.sleep(0.02)
        assert app.state.knowledge.state["total"] == total and app.state.knowledge.state["done"] == total


async def test_fallbacks_when_wikidata_lacks_console_and_sega_retro_link(monkeypatch):
    """« Wonder Boy » : la fiche Wikidata ne cite pas la Master System et n'a pas de lien Sega Retro. Seul jeu à
    porter exactement ce titre : retenu ; page Sega Retro trouvée par son titre, classée Master System."""
    monkeypatch.setattr(kn, "PAUSE", 0)
    parsed = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.netloc == "www.wikidata.org":
            if q["action"] == "wbsearchentities":
                return httpx.Response(200, json={"search": [{"id": "Q780496"}, {"id": "Q864340"}]})
            if "Q780496" in q["ids"]:
                return httpx.Response(200, json={"entities": {
                    "Q780496": entity("Q780496", "Q7889", ["Q192851"], label="Wonder Boy"),
                    "Q864340": entity("Q864340", "Q7889", ["Q192851"], label="Wonder Boy in Monster Land")}})
            return httpx.Response(200, json={"entities": {"Q192851": {"labels": {"en": {"value": "arcade game"}},
                                                                       "aliases": {}}}})
        if url.netloc == "segaretro.org":
            if q.get("prop") == "categories":
                return httpx.Response(200, json={"query": {"pages": [{"title": "Wonder Boy", "categories": [
                    {"title": "Category:1987 Master System games"}]}]}})
            if q.get("list") == "allpages":
                return httpx.Response(200, json={"query": {"allpages": []}})
            parsed.append(q["page"])
            return httpx.Response(200, json={"parse": {"text": "<h2>Gameplay</h2><p>" + "Tom-Tom eats fruit to keep "
                                                       "his vitality meter from running out. " * 3 + "</p>"}})
        return httpx.Response(404)

    fetcher = kn.Fetcher(transport=httpx.MockTransport(handler))
    found = await fetcher.fetch("Wonder Boy", "SMS")
    assert found.status == "found" and found.wikidata == "Q780496" and found.sources["segaretro"] == "Wonder_Boy"
    assert parsed == ["Wonder Boy"] and found.chunks[0]["license"] == "GFDL 1.2"
