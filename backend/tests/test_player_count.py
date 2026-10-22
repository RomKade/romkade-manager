import httpx

from app.services import gameinfo
from tests.test_catalog import sync


def test_player_count_completed_from_other_editions():
    """Le nombre de joueurs n'est souvent connu que pour une édition : complété par le titre."""
    idx = gameinfo.InfoIndex({"consoles": {"SMS": {
        "Wonder Boy (USA, Europe)": [1987, None, "Escape", "Sega", None, None, None],
        "Wonder Boy (USA, Europe, Brazil) (Rev 1)": [None, None, None, None, None, None, None, 2]}}})
    assert idx.lookup("SMS", "Wonder Boy (USA, Europe).sms")["players"] == 2
    assert idx.lookup("SMS", "Wonder Boy (USA, Europe).sms")["release_year"] == 1987


async def test_players_field_and_filter(app_factory):
    """Super Mario World : 2 joueurs (base libretro) ; Sonic : 1. Filtre « Joueurs » de la bibliothèque."""
    app = app_factory()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        items = {g["title"]: g for g in (await c.get("/api/games")).json()["items"]}
        mario = next(g for t, g in items.items() if t.startswith("Super Mario World"))
        sonic = next(g for t, g in items.items() if t.startswith("Sonic"))
        assert mario["players"] == 2 and mario["players_link"] is False and sonic["players"] == 1

        two = {g["id"] for g in (await c.get("/api/games", params={"players": "2"})).json()["items"]}
        solo = {g["id"] for g in (await c.get("/api/games", params={"players": "solo"})).json()["items"]}
        link = {g["id"] for g in (await c.get("/api/games", params={"players": "link"})).json()["items"]}
        assert mario["id"] in two and sonic["id"] not in two
        assert sonic["id"] in solo and mario["id"] not in solo and link == set()
        assert (await c.get("/api/games", params={"players": "3"})).status_code == 422
