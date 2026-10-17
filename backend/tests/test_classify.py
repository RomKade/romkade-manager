import pytest

from app.services.classify import classify_directory, display_title, normalize_title, region_of, search_key


def test_cue_tracks_are_components():
    r = classify_directory("emulated", ["Game (USA).cue", "Game (USA) (Track 1).bin", "Game (USA) (Track 2).bin", "Other.bin"])
    assert r == {"Game (USA).cue": "candidate", "Game (USA) (Track 1).bin": "component",
                 "Game (USA) (Track 2).bin": "component", "Other.bin": "candidate"}


def test_m3u_discs_are_components():
    r = classify_directory("emulated", ["FF7.m3u", "FF7 (Disc 1).chd", "FF7 (Disc 2).chd", "Crash.chd"])
    assert r["FF7.m3u"] == "candidate" and r["FF7 (Disc 1).chd"] == "component" and r["Crash.chd"] == "candidate"


def test_megadrive_bin_without_index_stays_candidate():
    assert classify_directory("emulated", ["Sonic.bin"]) == {"Sonic.bin": "candidate"}


def test_auxiliary_and_programs():
    assert classify_directory("emulated", ["a.sav", "b.txt", "c.gba"]) == {"a.sav": "auxiliary", "b.txt": "auxiliary", "c.gba": "candidate"}
    assert classify_directory("ports", ["x.sh", "y.pxm"]) == {"x.sh": "program", "y.pxm": "program"}


@pytest.mark.parametrize("stem,title,norm", [
    ("Super Mario World (USA)", "Super Mario World", "super mario world"),
    ("Legend of Zelda, The - A Link to the Past (Europe) [!]", "Legend of Zelda, The - A Link to the Past",
     "legend of zelda the a link to the past"),
    ("The Lion King (Europe)", "The Lion King", "lion king"),
    ("Pokémon_Rouge (France)", "Pokémon Rouge", "pokemon rouge"),
])
def test_titles(stem, title, norm):
    assert display_title(stem) == title
    assert normalize_title(stem) == norm


@pytest.mark.parametrize("stem,region", [
    ("Game (USA, Europe)", "USA, Europe"), ("Game (Japan) (Rev 1)", "Japon"), ("Game (E)", "Europe"),
    ("Game [b]", None), ("Game", None),
])
def test_region(stem, region):
    assert region_of(stem) == region


def test_search_key_ignores_case_and_accents():
    assert search_key("Pokémon - Édition Rouge.gb") == "pokemon edition rouge gb"
