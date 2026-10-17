import httpx

from app.services.videos import rank_videos
from tests.test_catalog import games, sync

KEY = "AIza" + "x" * 35


def item(vid: str, title: str, channel: str = "Retro") -> dict:
    return {"id": {"videoId": vid}, "snippet": {"title": title, "channelTitle": channel}}


def test_rank_prefers_matching_trailer_and_drops_other_games():
    items = [
        item("a", "TOP 10 SNES games REVIEW"),
        item("b", "Super Mario World - SNES Gameplay"),
        item("c", "Super Mario World (SNES) Trailer &amp; commercial"),
        item("d", "Zelda: A Link to the Past longplay"),
    ]
    out = rank_videos(items, "Super Mario World", "SNES")
    assert [v.id for v in out] == ["c", "b"]
    assert out[0].title == "Super Mario World (SNES) Trailer & commercial"


async def test_video_lookup_without_key_gives_search_link(client):
    await sync(client)
    gid = (await games(client, q="mario"))["items"][0]["id"]
    r = (await client.get(f"/api/games/{gid}/video")).json()
    assert r["status"] == "no_key" and r["videos"] == []
    assert r["query"] == "Super Mario World SNES gameplay"
    assert r["search_url"].startswith("https://www.youtube.com/results?search_query=Super+Mario+World")


async def test_video_lookup_searches_once_then_uses_cache(app_factory):
    calls = []

    def youtube(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json={"items": [item("m1", "Super Mario World SNES trailer")]})

    app = app_factory()
    app.state.youtube_transport = httpx.MockTransport(youtube)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.put("/api/settings/youtube", json={"api_key": "trop court"})).status_code == 422
        assert (await c.put("/api/settings/youtube", json={"api_key": KEY})).status_code == 204
        assert (await c.get("/api/settings/youtube")).json() == {"configured": True}
        await sync(c)
        gid = (await games(c, q="mario"))["items"][0]["id"]
        first = (await c.get(f"/api/games/{gid}/video")).json()
        assert first["status"] == "found" and first["videos"][0]["id"] == "m1"
        again = (await c.get(f"/api/games/{gid}/video")).json()
        assert again["videos"] == first["videos"] and len(calls) == 1
        assert calls[0].params["videoEmbeddable"] == "true" and calls[0].params["key"] == KEY
        await c.get(f"/api/games/{gid}/video", params={"refresh": True})
        assert len(calls) == 2
        assert (await c.delete("/api/settings/youtube")).status_code == 204
        assert (await c.get("/api/settings/youtube")).json() == {"configured": False}


async def test_video_quota_and_bad_key_are_explained(app_factory):
    reason = {"value": "quotaExceeded"}

    def youtube(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"errors": [{"reason": reason["value"]}]}})

    app = app_factory()
    app.state.youtube_transport = httpx.MockTransport(youtube)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await c.put("/api/settings/youtube", json={"api_key": KEY})
        await sync(c)
        gid = (await games(c, q="mario"))["items"][0]["id"]
        r = await c.get(f"/api/games/{gid}/video")
        assert r.status_code == 429 and r.json()["error"]["code"] == "youtube_quota"
        reason["value"] = "keyInvalid"
        r = await c.get(f"/api/games/{gid}/video")
        assert r.status_code == 400 and r.json()["error"]["code"] == "youtube_key_invalid"
