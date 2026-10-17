"""Jaquettes (boîtes des jeux) depuis libretro-thumbnails, la banque d'images de RetroArch.

Les images du dossier Imgs de la carte sont souvent des montages (capture, petite boîte, logo) faits pour le
menu de la console. Ici on récupère la vraie boîte : https://thumbnails.libretro.com/<Système>/Named_Boxarts/
<Nom No-Intro>.png. Pour l'arcade, le nom est le titre complet MAME/FBNeo.

Téléchargée une fois au premier affichage, gardée dans le cache du Mac. Rien n'est écrit sur la console.
Une jaquette introuvable est notée (fichier .missing) et n'est redemandée qu'après MISSING_RETRY.
"""

import asyncio
import hashlib
import json
import re
import time
import urllib.parse
from pathlib import Path

import httpx

from app import errors
from app.db.models import RemoteFile
from app.services.classify import stem_of
from app.services.genres import ARCADE_DIRS, CONSOLE_SOURCES, GenreIndex, loose_title
from app.services.images import _make_thumb, _write_atomic
from app.platforms import canonical

BASE = "https://thumbnails.libretro.com"
MAX_BYTES = 8 * 1024 * 1024
MISSING_RETRY = 30 * 24 * 3600
PARALLEL = 6
LISTING_MAX_AGE = 30 * 24 * 3600
_HREF = re.compile(r'href="([^"?/][^"]*\.png)"')

# Systèmes sans table de genres mais présents dans libretro-thumbnails (jeux sur CD surtout).
EXTRA_SOURCES = {
    "PS": ["Sony - PlayStation"], "DREAMCAST": ["Sega - Dreamcast"], "SATURN": ["Sega - Saturn"],
    "MDCD": ["Sega - Mega-CD - Sega CD"], "PCECD": ["NEC - PC Engine CD - TurboGrafx-CD"],
    "NEOCD": ["SNK - Neo Geo CD"], "A800": ["Atari - 8-bit"], "C64": ["Commodore - 64"],
    "AMIGA": ["Commodore - Amiga"], "POKE": ["Nintendo - Pokemon Mini"], "GW": ["Handheld Electronic Game"],
}
# Caractères que libretro remplace par « _ » dans les noms de fichiers.
_FORBIDDEN = str.maketrans({c: "_" for c in '&*/:`<>?\\|"'})


def has_source(platform_dir: str) -> bool:
    d = canonical(platform_dir)
    return d in ARCADE_DIRS or d in CONSOLE_SOURCES or d in EXTRA_SOURCES


def candidates(f: RemoteFile, index: GenreIndex) -> list[tuple[str, str]]:
    """(système libretro, nom de fichier sans extension) à essayer dans l'ordre."""
    d = canonical(f.platform.directory)
    out: list[tuple[str, str]] = []
    if d in ARCADE_DIRS:
        if f.full_title:
            repos = ["FBNeo - Arcade Games", "MAME"] if d == "FBNEO" else ["MAME", "FBNeo - Arcade Games"]
            out += [(r, f.full_title) for r in repos]
    else:
        stem = stem_of(f.filename)
        sources = CONSOLE_SOURCES.get(d, []) + EXTRA_SOURCES.get(d, [])
        out += [(src, stem) for src in sources[:1]]
        for src in sources:  # nom exact connu de la base (casse corrigée), puis autre édition du même titre
            exact = index.names.get(src, {}).get(stem.lower())
            if exact:
                out.append((src, exact))
        title = loose_title(stem)
        for src in sources:
            other = index.names_by_title.get(src, {}).get(title)
            if other:
                out.append((src, other))
    seen, unique = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def compact(name: str) -> str:
    """Titre souple sans espaces : « NewZealand Story, The » = « New Zealand Story, The »."""
    return loose_title(name.replace("_", " ")).replace(" ", "")


def best_in_listing(listing: list[str], title: str) -> str | None:
    """Nom de la banque qui correspond au titre : même titre, sinon titre qui le prolonge (« X / Minigolf »)."""
    key = compact(title)
    if len(key) < 3:
        return None
    exact = [n for n in listing if compact(n) == key]
    longer = [n for n in listing if len(key) >= 6 and compact(n).startswith(key)] if not exact else []
    pool = exact or longer
    if not pool:
        return None
    def rank(name: str) -> tuple:
        tags = name.lower()
        region = 0 if "(usa" in tags or "(us" in tags else 1 if "europe" in tags else 2 if "world" in tags else 3
        bad = any(w in tags for w in ("beta", "proto", "bootleg", "hack", "demo", "sample"))
        return (bad, len(compact(name)) - len(key), region, name)
    return min(pool, key=rank)


def url_for(system: str, name: str) -> str:
    return f"{BASE}/{urllib.parse.quote(system)}/Named_Boxarts/{urllib.parse.quote(name.translate(_FORBIDDEN))}.png"


class BoxartStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[Path, asyncio.Lock] = {}
        self._sem = asyncio.Semaphore(PARALLEL)
        self.transport: httpx.AsyncBaseTransport | None = None  # les tests y branchent un faux serveur

    def path_for(self, f: RemoteFile) -> Path:
        key = hashlib.sha1(f"{f.platform.directory}/{f.filename}|{f.full_title or ''}".encode()).hexdigest()
        return self.root / f.platform.directory / f"{key}.png"

    async def get(self, f: RemoteFile, index: GenreIndex) -> Path | None:
        target = self.path_for(f)
        missing = target.with_suffix(".missing")
        if target.exists():
            return target
        if missing.exists() and time.time() - missing.stat().st_mtime < MISSING_RETRY:
            return None
        lock = self._locks.setdefault(target, asyncio.Lock())
        async with lock:
            if target.exists():
                return target
            async with self._sem:
                data = await self._download(candidates(f, index))
            if data is None:
                await asyncio.to_thread(_write_atomic, missing, b"")
                return None
            await asyncio.to_thread(_write_atomic, target, data)
            missing.unlink(missing_ok=True)
            return target

    async def _download(self, tries: list[tuple[str, str]]) -> bytes | None:
        try:
            async with httpx.AsyncClient(timeout=15, transport=self.transport, follow_redirects=True) as http:
                for system, name in tries:
                    if data := await self._fetch_image(http, system, name):
                        return data
                # Nom exact inconnu de la banque : on cherche le titre le plus proche dans sa liste de fichiers.
                for system in dict.fromkeys(s for s, _ in tries):
                    listing = await self._listing(http, system)
                    for _, name in tries:
                        hit = best_in_listing(listing, name)
                        if hit and (data := await self._fetch_image(http, system, hit)):
                            return data
        except httpx.HTTPError as exc:
            # Réseau absent : on ne note pas la jaquette comme introuvable, on réessaiera.
            raise errors.AppError("boxart_unreachable", "Banque de jaquettes injoignable (connexion Internet ?)",
                                  502, {"error": type(exc).__name__}) from exc
        return None

    @staticmethod
    async def _fetch_image(http: httpx.AsyncClient, system: str, name: str) -> bytes | None:
        r = await http.get(url_for(system, name))
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") and 0 < len(r.content) <= MAX_BYTES:
            return r.content
        return None

    async def _listing(self, http: httpx.AsyncClient, system: str) -> list[str]:
        """Noms des jaquettes d'un système (sans .png), lus dans l'index du serveur et gardés 30 jours."""
        path = self.root / "_index" / f"{hashlib.sha1(system.encode()).hexdigest()}.json"
        if path.exists() and time.time() - path.stat().st_mtime < LISTING_MAX_AGE:
            return json.loads(path.read_text())
        lock = self._locks.setdefault(path, asyncio.Lock())
        async with lock:
            if path.exists() and time.time() - path.stat().st_mtime < LISTING_MAX_AGE:
                return json.loads(path.read_text())
            r = await http.get(f"{BASE}/{urllib.parse.quote(system)}/Named_Boxarts/", timeout=60)
            if r.status_code != 200:
                return []
            names = sorted({urllib.parse.unquote(h)[:-4] for h in _HREF.findall(r.text)})
            await asyncio.to_thread(_write_atomic, path, json.dumps(names).encode())
            return names

    async def thumbnail(self, original: Path) -> Path:
        thumb = original.with_name(original.stem + ".thumb.webp")
        if thumb.exists():
            return thumb
        return await asyncio.to_thread(_make_thumb, original, thumb) or original
