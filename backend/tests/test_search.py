import os
import shutil
import subprocess
import time

import httpx
import pytest

from app.services import search as se
from tests.test_catalog import games, sync


def test_filter_and_sort_building():
    f = se.build_filter(platforms=["MD", "SFC"], genres=["sport", "none"], regions=["Europe"], extensions=[".ZIP"])
    assert f == "platform:=[`MD`,`SFC`] && extension:=[`zip`] && regions:=[`Europe`] && genre:=[`sport`,`none`] && present:=true"
    assert se.build_filter(include_removed=True) == ""
    assert se.build_filter(platforms=["a`b"]) == "platform:=[`ab`] && present:=true"  # pas d'injection de filtre
    assert se.build_sort("name", "asc", True) == "_text_match:desc,sort_title:asc"
    assert se.build_sort("name", "asc", False) == "sort_title:asc"
    assert se.build_sort("size", "desc", True) == "size:desc"


async def test_library_falls_back_to_sqlite_without_typesense(client):
    await sync(client)
    assert (await client.get("/api/search/status")).json()["engine"] == "sqlite"
    assert [g["title"] for g in (await games(client, q="mario"))["items"]] == ["Super Mario World"]
    r = (await client.get("/api/search", params={"q": "sonic"})).json()
    assert r["engine"] == "sqlite" and [g["title"] for g in r["items"]] == ["Sonic The Hedgehog"]


IT = os.environ.get("AGM_TYPESENSE_IT") == "1" and shutil.which("docker")


@pytest.fixture
def typesense(tmp_path, monkeypatch):
    if not IT:
        pytest.skip("AGM_TYPESENSE_IT=1 et Docker requis")
    name, port, key = "agm-typesense-test", 8119, "test-key"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:8108", se.IMAGE,
                    "--data-dir", "/tmp", "--api-key", key], check=True, capture_output=True)
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    monkeypatch.setenv("AGM_TYPESENSE_URL", url)
    monkeypatch.setenv("AGM_TYPESENSE_KEY", key)
    yield url
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


async def test_typesense_typos_prefix_and_filters(typesense, app_factory):
    app = app_factory()
    app.state.search = se.SearchService(app.state.sessions, app.state.save_vault.root.parent)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
        assert await app.state.search.reindex() == 5
        titles = lambda r: [g["title"] for g in r["items"]]  # noqa: E731
        assert titles(await games(c, q="maro wrld")) == ["Super Mario World"]      # fautes de frappe
        assert titles(await games(c, q="son")) == ["Sonic The Hedgehog"]            # préfixe
        assert titles(await games(c, q="sonic", platform="SFC")) == []             # filtre console
        assert titles(await games(c, q="mario", genre="plateforme")) == ["Super Mario World"]
        r = (await c.get("/api/search", params={"q": "ridge racr"})).json()
        assert r["engine"] == "typesense" and titles(r) == ["Ridge Racer"]


async def test_typesense_reindex_swaps_alias_without_gap(typesense, app_factory):
    app = app_factory()
    search = se.SearchService(app.state.sessions, app.state.save_vault.root.parent)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await sync(c)
    headers = {"X-TYPESENSE-API-KEY": "test-key"}
    # Index d'une version précédente : une vraie collection « games », remplacée par l'alias.
    httpx.post(f"{typesense}/collections", json={**se.SCHEMA}, headers=headers).raise_for_status()
    assert await search.reindex() == 5
    assert await search.reindex() == 5
    names = [x["name"] for x in httpx.get(f"{typesense}/collections", headers=headers).json()]
    alias = httpx.get(f"{typesense}/aliases/{se.COLLECTION}", headers=headers).json()["collection_name"]
    assert names == [alias] and alias.startswith("games_")
    assert (await search.search("sonic"))[1] == 1
