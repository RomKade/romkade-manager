"""Correspondance dossier -> plateforme.

`label_status` :
- "confirmed"  : correspondance donnée par l'utilisateur (tableau du cahier des charges)
- "assumed"    : déduite du nom de dossier, à confirmer sur la console
- "unknown"    : signification non établie
Un dossier absent de cette table reste listé, avec known=False.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformInfo:
    label: str | None
    kind: str  # "emulated" | "apps" | "ports" | "engine" | "unknown"
    label_status: str


_C, _A, _U = "confirmed", "assumed", "unknown"

PLATFORMS: dict[str, PlatformInfo] = {
    "A2600": PlatformInfo("Atari 2600", "emulated", _A),
    "A5200": PlatformInfo("Atari 5200", "emulated", _A),
    "A7800": PlatformInfo("Atari 7800", "emulated", _A),
    "A800": PlatformInfo("Atari 800", "emulated", _A),
    "AMIGA": PlatformInfo("Commodore Amiga", "emulated", _A),
    "APPS": PlatformInfo("Applications", "apps", _A),
    "ATARIST": PlatformInfo("Atari ST", "emulated", _A),
    "ATOMISWAVE": PlatformInfo("Sammy Atomiswave", "emulated", _A),
    "C64": PlatformInfo("Commodore 64", "emulated", _A),
    "CPS1": PlatformInfo("Capcom CPS-1", "emulated", _A),
    "CPS2": PlatformInfo("Capcom CPS-2", "emulated", _A),
    "CPS3": PlatformInfo("Capcom CPS-3", "emulated", _A),
    "DOS": PlatformInfo("MS-DOS", "emulated", _A),
    "DREAMCAST": PlatformInfo("Sega Dreamcast", "emulated", _C),
    "EASYRPG": PlatformInfo("EasyRPG (RPG Maker)", "engine", _A),
    "FBNEO": PlatformInfo("FinalBurn Neo (arcade)", "emulated", _C),
    "FC": PlatformInfo("NES / Famicom", "emulated", _C),
    "FDS": PlatformInfo("Famicom Disk System", "emulated", _A),
    "GB": PlatformInfo("Game Boy", "emulated", _A),
    "GBA": PlatformInfo("Game Boy Advance", "emulated", _C),
    "GBC": PlatformInfo("Game Boy Color", "emulated", _A),
    "GG": PlatformInfo("Sega Game Gear", "emulated", _A),
    "GW": PlatformInfo("Game & Watch", "emulated", _A),
    "HBMAME": PlatformInfo("HBMAME (arcade homebrew)", "emulated", _A),
    "JAVA": PlatformInfo("Java ME", "emulated", _A),
    "LYNX": PlatformInfo("Atari Lynx", "emulated", _A),
    "MAME": PlatformInfo("Arcade (MAME)", "emulated", _C),
    "MD": PlatformInfo("Mega Drive / Genesis", "emulated", _C),
    "MDCD": PlatformInfo("Mega-CD", "emulated", _A),
    "MSX": PlatformInfo("MSX", "emulated", _A),
    "N64": PlatformInfo("Nintendo 64", "emulated", _C),
    "NAOMI": PlatformInfo("Sega NAOMI", "emulated", _A),
    "NDS": PlatformInfo("Nintendo DS", "emulated", _A),
    "NEOCD": PlatformInfo("Neo Geo CD", "emulated", _A),
    "NEOGEO": PlatformInfo("Neo Geo", "emulated", _A),
    "NGP": PlatformInfo("Neo Geo Pocket", "emulated", _A),
    "ONS": PlatformInfo("ONScripter", "engine", _A),
    "OPENBOR": PlatformInfo("OpenBOR", "engine", _A),
    "PCE": PlatformInfo("PC Engine", "emulated", _A),
    "PCECD": PlatformInfo("PC Engine CD", "emulated", _A),
    "PGM2": PlatformInfo("IGS PGM2", "emulated", _A),
    "PICO": PlatformInfo("PICO-8", "engine", _A),
    "POKE": PlatformInfo("Pokémon Mini", "emulated", _A),
    "PORTS": PlatformInfo("Ports", "ports", _A),
    "PS": PlatformInfo("PlayStation", "emulated", _C),
    "PSP": PlatformInfo("PlayStation Portable", "emulated", _C),
    "SATURN": PlatformInfo("Sega Saturn", "emulated", _C),
    "SCUMMVM": PlatformInfo("ScummVM", "engine", _A),
    "SEGA32X": PlatformInfo("Sega 32X", "emulated", _A),
    "SFC": PlatformInfo("Super Nintendo", "emulated", _C),
    "SMS": PlatformInfo("Sega Master System", "emulated", _A),
    "VARCADE": PlatformInfo(None, "unknown", _U),
    "VB": PlatformInfo("Virtual Boy", "emulated", _A),
    "VIC20": PlatformInfo("Commodore VIC-20", "emulated", _A),
    "WS": PlatformInfo("WonderSwan", "emulated", _A),
}

IMAGE_DIR_NAMES = {"imgs"}  # comparaison insensible à la casse
# Dossiers du dossier des ROMs qui ne sont pas des consoles (ROCKNIX, Batocera, Knulli, ArkOS…).
NOT_PLATFORM_DIRS = {"savestates", "bios", "screenshots", "saves", "themes", "lost+found", "system volume information"}
# Médias rangés à côté des ROMs par les autres firmwares (Batocera, Knulli, ROCKNIX, muOS, ES-DE…) : pas des jeux.
MEDIA_DIR_NAMES = {"images", "videos", "manuals", "media", "snap", "snaps", "screenshots", "titles", "marquees",
                   "wheel", "boxart", "box2dfront", "thumbnails", "downloaded_images", "downloaded_videos"}
# Seuls ces fichiers des dossiers Imgs sont des images (exclut Thumbs.db, desktop.ini...).
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}

# Extensions qui ne sont pas des jeux : servent seulement à marquer role="auxiliary".
# Tout le reste est "candidate" : un fichier candidat n'est PAS affirmé jouable.
AUXILIARY_EXTENSIONS = {
    "txt", "nfo", "xml", "dat", "md5", "sfv", "cfg", "ini", "json", "log",
    "png", "jpg", "jpeg", "gif", "bmp", "webp",
    "srm", "sav", "state", "auto", "rtc", "mcr",
    "mp4", "mkv", "avi", "webm", "pdf",
}


def lookup(directory: str) -> PlatformInfo | None:
    return PLATFORMS.get(canonical(directory))


# ---------- dossiers des autres systèmes ----------
# Chaque firmware nomme ses dossiers de ROMs à sa façon : « snes » (Batocera, Knulli, ROCKNIX, ArkOS),
# « SFC » (Anbernic, Onion), « Super Nintendo Entertainment System (SFC) » (MinUI, NextUI), noms libres (muOS).
# Le code canonique (clé de PLATFORMS) sert aux genres, jaquettes, bandes-annonces et illustrations.
# Clés : nom en minuscules, sans espaces ni ponctuation.
ALIASES: dict[str, str] = {
    "atari2600": "A2600", "atari": "A2600", "atari5200": "A5200", "atari7800": "A7800", "atari800": "A800",
    "amiga500": "AMIGA", "amiga1200": "AMIGA", "commodoreamiga": "AMIGA",
    "c20": "VIC20", "commodore64": "C64",
    "pc": "DOS", "msdos": "DOS", "dc": "DREAMCAST", "segadreamcast": "DREAMCAST",
    "fba": "FBNEO", "fbalpha": "FBNEO", "finalburnneo": "FBNEO",
    "nes": "FC", "famicom": "FC", "nintendoentertainmentsystem": "FC", "nintendones": "FC",
    "famicomdisksystem": "FDS",
    "gameboy": "GB", "nintendogameboy": "GB", "gameboycolor": "GBC", "nintendogameboycolor": "GBC",
    "gameboyadvance": "GBA", "nintendogameboyadvance": "GBA", "mgba": "GBA",
    "gamegear": "GG", "segagamegear": "GG", "gameandwatch": "GW",
    "j2me": "JAVA", "atarilynx": "LYNX",
    "arcade": "MAME", "mame2003": "MAME", "mame2003plus": "MAME", "mame2010": "MAME",
    "megadrive": "MD", "genesis": "MD", "segagenesis": "MD", "segamegadrive": "MD",
    "segacd": "MDCD", "megacd": "MDCD", "segamegacd": "MDCD",
    "msx1": "MSX", "msx2": "MSX", "nintendo64": "N64", "nintendods": "NDS",
    "neogeocd": "NEOCD", "snkneogeo": "NEOGEO", "ngpc": "NGP", "neogeopocket": "NGP", "neogeopocketcolor": "NGP",
    "onscripter": "ONS",
    "pcengine": "PCE", "tg16": "PCE", "turbografx": "PCE", "turbografx16": "PCE", "necpcengine": "PCE",
    "pcenginecd": "PCECD", "tg16cd": "PCECD", "turbografxcd": "PCECD",
    "pico8": "PICO", "pokemini": "POKE", "pkm": "POKE",
    "psx": "PS", "ps1": "PS", "playstation": "PS", "sonyplaystation": "PS",
    "playstationportable": "PSP", "sonyplaystationportable": "PSP",
    "segasaturn": "SATURN", "32x": "SEGA32X", "sega32x": "SEGA32X",
    "snes": "SFC", "superfamicom": "SFC", "supernintendo": "SFC", "supernintendoentertainmentsystem": "SFC", "supa": "SFC",
    "mastersystem": "SMS", "ms": "SMS", "segamastersystem": "SMS",
    "virtualboy": "VB", "nintendovirtualboy": "VB",
    "wonderswan": "WS", "wonderswancolor": "WS", "wsc": "WS", "bandaiwonderswan": "WS",
}
_TAG = re.compile(r"\(([^()]+)\)\s*$")


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def canonical(directory: str) -> str:
    """Code de console (clé de PLATFORMS) d'un dossier de ROMs, quel que soit le firmware ; à défaut, le nom
    du dossier en majuscules."""
    up = directory.upper()
    if up in PLATFORMS:
        return up
    m = _TAG.search(directory)  # MinUI / NextUI : « Game Boy (GB) »
    if m and m.group(1).strip().upper() != up:
        tagged = canonical(m.group(1).strip())
        if tagged in PLATFORMS:
            return tagged
    key = _key(directory)
    if key.upper() in PLATFORMS:
        return key.upper()
    return ALIASES.get(key) or _LABELS.get(key) or up


_LABELS = {_key(i.label): code for code, i in PLATFORMS.items() if i.label and "(" not in i.label and "/" not in i.label}
