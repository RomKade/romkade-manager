"""Classification des fichiers d'un dossier et normalisation des titres.

Rôles :
- candidate : fichier susceptible d'être un jeu (non affirmé jouable)
- component : piste/disque rattaché à un index (.cue, .gdi, .ccd, .mds) ou à une playlist .m3u
- auxiliary : texte, image, sauvegarde, métadonnées
- program   : contenu des dossiers APPS / PORTS (programmes, pas des ROMs)
"""

import re
import unicodedata

from app.platforms import AUXILIARY_EXTENSIONS

TRACK_INDEX_EXT = {"cue", "gdi", "ccd", "mds"}
TRACK_EXT = {"bin", "img", "raw", "wav", "sub", "mdf", "iso", "ape", "flac", "ogg"}
PLAYLIST_EXT = {"m3u"}
DISC_EXT = {"chd", "cue", "gdi", "ccd", "mds", "bin", "img", "iso", "pbp", "cso"} | TRACK_EXT

PROGRAM_KINDS = {"apps", "ports"}

REGION_TAGS = {
    "usa": "USA", "us": "USA", "u": "USA",
    "europe": "Europe", "eu": "Europe", "e": "Europe",
    "japan": "Japon", "jp": "Japon", "j": "Japon",
    "world": "Monde", "w": "Monde",
    "france": "France", "fr": "France", "f": "France",
    "germany": "Allemagne", "de": "Allemagne", "g": "Allemagne",
    "spain": "Espagne", "es": "Espagne", "s": "Espagne",
    "italy": "Italie", "it": "Italie", "i": "Italie",
    "korea": "Corée", "k": "Corée",
    "brazil": "Brésil", "b": "Brésil",
    "asia": "Asie", "australia": "Australie", "china": "Chine",
}


def extension_of(name: str) -> str | None:
    if "." not in name.lstrip("."):
        return None
    return name.rsplit(".", 1)[1].lower() or None


def stem_of(name: str) -> str:
    return name.rsplit(".", 1)[0] if extension_of(name) else name


def classify_directory(kind: str, filenames: list[str]) -> dict[str, str]:
    if kind in PROGRAM_KINDS:
        return {n: "program" for n in filenames}
    roles: dict[str, str] = {}
    lower_stems = {n: stem_of(n).lower() for n in filenames}
    exts = {n: extension_of(n) for n in filenames}
    playlists = [lower_stems[n] for n in filenames if exts[n] in PLAYLIST_EXT]
    indexes = [lower_stems[n] for n in filenames if exts[n] in TRACK_INDEX_EXT]

    for n in filenames:
        ext, stem = exts[n], lower_stems[n]
        if ext in AUXILIARY_EXTENSIONS:
            roles[n] = "auxiliary"
        elif ext in DISC_EXT and any(stem.startswith(p) for p in playlists):
            roles[n] = "component"
        elif ext in TRACK_EXT and any(stem.startswith(i) for i in indexes):
            roles[n] = "component"
        else:
            roles[n] = "candidate"
    return roles


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def display_title(stem: str) -> str:
    s = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", stem).replace("_", " ")
    return re.sub(r"\s+", " ", s).strip() or stem


def normalize_title(stem: str) -> str:
    s = _strip_accents(display_title(stem)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"^the ", "", s)
    s = re.sub(r", the$", "", s)
    return s


def search_key(filename: str) -> str:
    s = _strip_accents(filename).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def region_of(stem: str) -> str | None:
    found: list[str] = []
    for group in re.findall(r"\(([^)]*)\)", stem):
        for tok in re.split(r"\s*,\s*", group):
            label = REGION_TAGS.get(tok.strip().lower())
            if label and label not in found:
                found.append(label)
    return ", ".join(found) or None
