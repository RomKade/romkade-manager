"""Télécharge les illustrations de consoles (retroarch-assets, thème XMB « systematic », CC-BY 4.0)
et les écrit en WebP 160 px dans frontend/public/consoles/<DOSSIER>.webp.

Usage (depuis backend/) :
    .venv/bin/python scripts/build_console_icons.py

À lancer seulement pour ajouter une console : l'interface sert les fichiers produits, sans réseau.
Crédit : libretro/retroarch-assets, https://github.com/libretro/retroarch-assets (CC-BY 4.0).
"""

import io
import sys
import urllib.parse
from pathlib import Path

import httpx  # dépendance de dev : fournit les certificats (certifi), absents du Python python.org
from PIL import Image

BASE = "https://raw.githubusercontent.com/libretro/retroarch-assets/master/xmb/systematic/png/{}.png"
OUT = Path(__file__).resolve().parents[2] / "frontend" / "public" / "consoles"
SIZE = 160

# Dossier de la carte -> noms d'icônes essayés dans l'ordre.
ICONS: dict[str, list[str]] = {
    "A2600": ["Atari - 2600"], "A5200": ["Atari - 5200"], "A7800": ["Atari - 7800"], "A800": ["Atari - 8-bit Family"],
    "LYNX": ["Atari - Lynx"], "ATARIST": ["Atari - ST"], "AMIGA": ["Commodore - Amiga"], "C64": ["Commodore - 64"],
    "VIC20": ["Commodore - VIC-20"], "DOS": ["DOS"],
    "MAME": ["MAME"], "HBMAME": ["HBMAME"], "FBNEO": ["FBNeo - Arcade Games"],
    "CPS1": ["Capcom - CP System I"], "CPS2": ["Capcom - CP System II"], "CPS3": ["Capcom - CP System III"],
    "NAOMI": ["Sega - Naomi"], "ATOMISWAVE": ["Atomiswave"], "PGM2": ["IGS - PGM2", "MAME"], "VARCADE": ["MAME"],
    "NEOGEO": ["SNK - Neo Geo"], "NEOCD": ["SNK - Neo Geo CD"], "NGP": ["SNK - Neo Geo Pocket Color", "SNK - Neo Geo Pocket"],
    "FC": ["Nintendo - Nintendo Entertainment System"], "FDS": ["Nintendo - Family Computer Disk System"],
    "SFC": ["Nintendo - Super Nintendo Entertainment System"], "N64": ["Nintendo - Nintendo 64"],
    "GB": ["Nintendo - Game Boy"], "GBC": ["Nintendo - Game Boy Color"], "GBA": ["Nintendo - Game Boy Advance"],
    "NDS": ["Nintendo - Nintendo DS"], "VB": ["Nintendo - Virtual Boy"], "GW": ["Nintendo - Game & Watch"],
    "POKE": ["Nintendo - Pokemon Mini"],
    "SMS": ["Sega - Master System - Mark III"], "MD": ["Sega - Mega Drive - Genesis"], "MDCD": ["Sega - Mega-CD - Sega CD"],
    "SEGA32X": ["Sega - 32X"], "GG": ["Sega - Game Gear"], "SATURN": ["Sega - Saturn"], "DREAMCAST": ["Sega - Dreamcast"],
    "PS": ["Sony - PlayStation"], "PSP": ["Sony - PlayStation Portable"],
    "PCE": ["NEC - PC Engine - TurboGrafx 16"], "PCECD": ["NEC - PC Engine CD - TurboGrafx-CD"],
    "WS": ["Bandai - WonderSwan", "Bandai - WonderSwan Color"], "MSX": ["Microsoft - MSX", "Microsoft - MSX2"],
    "PICO": ["PICO-8", "Lexaloffle - PICO-8"], "OPENBOR": ["OpenBOR"], "SCUMMVM": ["ScummVM"],
    "EASYRPG": ["EasyRPG", "RPG Maker"], "JAVA": ["J2ME", "Java ME"], "ONS": ["ONScripter"],
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = []
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        for directory, names in ICONS.items():
            for name in names:
                r = http.get(BASE.format(urllib.parse.quote(name)))
                if r.status_code == 200:
                    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                    img.thumbnail((SIZE, SIZE), Image.LANCZOS)
                    img.save(OUT / f"{directory}.webp", "WEBP", quality=88, method=6)
                    print(f"{directory:<11} {name}")
                    break
            else:
                missing.append(directory)
    if missing:
        print("\nSans icône (l'interface affiche le code du dossier) :", ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
