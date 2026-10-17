from app.services.genres import (
    CATVER_RULES, GENRES, LIBRETRO_MAP, GenreIndex, catver_genre, libretro_genre, load_index,
)
from tests.test_catalog import games, sync


def test_source_categories_map_to_unified_genres():
    assert libretro_genre("Sports") == "sport"
    assert libretro_genre("Shoot'em Up") == "shmup"
    assert libretro_genre("Lightgun Shooter") == "tir"
    assert libretro_genre("Adult") is None
    assert catver_genre("Shooter / Flying Vertical") == "shmup"
    assert catver_genre("Shooter / Gallery") == "tir"
    assert catver_genre("Platform / Shooter Scrolling") == "tir"
    assert catver_genre("Platform / Fighter Scrolling") == "beat"
    assert catver_genre("Fighter / Versus * Mature *") == "combat"
    assert catver_genre("Sports / Soccer") == "sport"
    assert catver_genre("Slot Machine / Video Slot") is None
    assert catver_genre("Board Game / Chess Machine") is None
    assert {*LIBRETRO_MAP.values(), *(g for _, g in CATVER_RULES if g)} <= set(GENRES)


def test_lookup_exact_then_by_title():
    idx = GenreIndex({
        "systems": {"Sega - Mega Drive - Genesis": {
            "sonic the hedgehog (usa, europe)": "plateforme|Platform",
            "ren & stimpy show, the - stimpy's invention (usa)": "action|Action",
        }},
        "arcade": {"sf2": "combat|Fighter / Versus"},
    })
    assert idx.lookup("MD", "Sonic The Hedgehog (USA, Europe).md") == ("plateforme", "Platform")
    # Autre région, même titre
    assert idx.lookup("MD", "Sonic The Hedgehog (Japan) (Rev 1).bin") == ("plateforme", "Platform")
    assert idx.lookup("MD", "The Ren & Stimpy Show - Stimpy's Invention (Europe).md") == ("action", "Action")
    assert idx.lookup("FBNEO", "SF2.zip") == ("combat", "Fighter / Versus")
    assert idx.lookup("MD", "Inconnu (USA).md") is None
    # pas de source pour PS : le même jeu sur une autre console sert de repli
    assert idx.lookup("PS", "Sonic The Hedgehog (USA, Europe).chd") == ("plateforme", "Platform")
    assert idx.lookup("XYZ", "Inconnu.bin") is None


def test_bundled_table_loads():
    idx = load_index()
    assert len(idx.arcade) > 5000 and "Sega - Mega Drive - Genesis" in idx.systems
    assert idx.lookup("SFC", "Super Mario World (USA).smc")[0] == "plateforme"


async def test_genre_filter_and_facets(client):
    await sync(client)
    by_title = {g["title"]: g for g in (await games(client))["items"]}
    mario = by_title["Super Mario World"]
    assert mario["genre"] == "plateforme" and mario["genre_label"] == "Plateforme" and mario["genre_detail"]
    assert by_title["Ridge Racer"]["genre"] == "course"  # PlayStation : OpenVGDB
    assert by_title["mystery"]["genre"] is None

    facets = (await client.get("/api/catalog/facets")).json()["genres"]
    values = {f["value"]: f for f in facets}
    assert values["plateforme"]["label"] == "Plateforme" and values["plateforme"]["count"] >= 1
    assert values["none"]["label"] == "Non classé" and facets[-1]["value"] == "none"

    assert [g["title"] for g in (await games(client, genre="plateforme"))["items"]] == ["Super Mario World"]
    unclassified = {g["title"] for g in (await games(client, genre="none"))["items"]}
    assert "mystery" in unclassified and "Super Mario World" not in unclassified
    both = {g["title"] for g in (await games(client, genre=["plateforme", "none"]))["items"]}
    assert both == unclassified | {"Super Mario World"}
    ps = (await client.get("/api/catalog/facets", params={"platform": "SFC"})).json()["genres"]
    assert [f["value"] for f in ps] == ["plateforme"]


def test_arcade_full_title():
    idx = GenreIndex({"arcade_titles": {"sf2": "Street Fighter II: The World Warrior (World 910522)"}})
    assert idx.full_title("FBNEO", "sf2.zip") == "Street Fighter II: The World Warrior (World 910522)"
    assert idx.full_title("SFC", "sf2.zip") is None
    assert load_index().full_title("MAME", "1941.zip").startswith("1941")


def test_openvgdb_and_fuzzy_names():
    from app.services.genres import ovgdb_genre
    assert ovgdb_genre("Action,Fighting,3D") == "combat"
    assert ovgdb_genre("Action,Shooter,Scrolling") == "shmup"
    assert ovgdb_genre("Sports,Traditional,Soccer,Sim") == "sport"
    idx = GenreIndex({"ovgdb": {"PS": {"R4 - Ridge Racer Type 4 (USA)": "course|Driving / Racing",
                                       "Crash Team Racing (USA)": "course|Racing"},
                                "SATURN": {"Clockwork Knight (USA)": "plateforme|Platformer"},
                                "N64": {"Bomberman 64 (USA)": "action|Action"}}})
    assert idx.lookup("PS", "R4 Ridge Racer Type 4.PBP")[0] == "course"       # titre souple
    assert idx.lookup("SATURN", "SS-Clockwork Knight.chd")[0] == "plateforme"  # préfixe « SS- »
    assert idx.lookup("N64", "Bomberman64.z64")[0] == "action"                 # titre collé
    assert idx.lookup("PS", "Crash Team Raci.PBP")[0] == "course"              # titre tronqué


def test_subgenres():
    from app.services.subgenres import classify
    assert classify("sport", ["Sports"], "NBA Jam") == "sport.basket"
    assert classify("sport", ["Sports"], "Tecmo Super Bowl") == "sport.foot_us"  # pas du bowling
    assert classify("sport", ["Sports", "Sports,Traditional,Soccer,Sim"], "International Superstar Soccer") == "sport.football"
    assert classify("sport", ["Sports"], "California Games") == "sport.autres"
    assert classify("course", ["Driving / Racing / Formula One"], "x") == "course.f1"
    assert classify("combat", ["Fighter / 2.5D"], "Fatal Fury") == "combat.2d"
    assert classify("shmup", ["Shooter / Flying Vertical"], "1942") == "shmup.vertical"
    assert classify("plateforme", ["Platform"], "Super Mario World") is None
