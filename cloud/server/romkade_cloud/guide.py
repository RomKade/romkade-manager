"""Soluces des jeux : outil MCP game_guide (ChatGPT, Claude…) et /api/guide (assistant de ROMKADE Manager).

Mêmes sources que les connaissances du Manager (app/services/knowledge.py, sans IA) : Wikidata identifie le jeu,
puis StrategyWiki, Sega Retro et Wikipédia donnent le texte, découpé en passages avec leur adresse et leur licence
(CC BY-SA 4.0, GFDL 1.2 pour Sega Retro : à citer). Récupérée à la première demande, la soluce est gardée par jeu
(console + titre normalisé) pour tous les comptes : un jeu déjà demandé répond tout de suite.

Les passages sont choisis par mots en commun avec la recherche (« boss niveau 3 », « clé du donjon ») : c'est à
l'assistant d'en tirer un indice ou la solution, en citant la source.
"""

import asyncio
import logging
import time

import httpx

from app.platforms import canonical
from app.services import knowledge as kn

from .store import Store

log = logging.getLogger("romkade.guide")

PASSAGES = 4
MAX_PASSAGES = 8
REFRESH_FOUND = 90 * 86400    # soluce trouvée : relue tous les trois mois (pages mises à jour)
REFRESH_MISSING = 14 * 86400  # jeu introuvable : recherché de nouveau au bout de deux semaines
# À score égal, les soluces avant l'encyclopédie (qui raconte le jeu plus qu'elle n'aide à avancer).
SOURCE_RANK = {"strategywiki": 0, "segaretro": 1, "wikipedia": 2}


class GuideUnavailable(Exception):
    """Sources injoignables et aucune soluce gardée pour ce jeu."""


def key(platform_dir: str, title: str) -> str:
    return f"{canonical(platform_dir)}:{kn.norm(title)}"


def pick(chunks: list[dict], query: str, platform_dir: str, limit: int = PASSAGES) -> list[dict]:
    """Passages pour une recherche : mots en commun (page, section et texte), soluces d'abord ; sans recherche
    ou sans mot en commun, le début de la soluce. Plus le passage sur la version de la console du joueur, s'il y en a
    un (« Master System version »)."""
    words = {w for w in kn.norm(query).split() if len(w) > 2}

    def score(i: int, c: dict) -> tuple:
        hits = sum(w in kn.norm(f"{c.get('page', '')} {c.get('section', '')} {c.get('text', '')}") for w in words)
        return (-hits, SOURCE_RANK.get(c.get("source"), 3), i)

    ranked = sorted(enumerate(chunks), key=lambda x: score(*x))
    picked = [c for i, c in ranked if words and score(i, c)[0] < 0][:limit]
    if not picked:
        picked = [c for _, c in sorted(enumerate(chunks), key=lambda x: (SOURCE_RANK.get(x[1].get("source"), 3), x[0]))][:min(limit, 2)]
    names = {m for n in kn.platform_names(platform_dir) for m in (n, n.removeprefix("sega "), n.removeprefix("nintendo "))
             if (" " in m and len(m) >= 5) or len(m) >= 6}
    version = next((c for c in chunks if c not in picked and any(n in kn.norm(c.get("section", "")) for n in names)), None)
    return picked + ([version] if version and len(picked) < MAX_PASSAGES else [])


def passage_out(c: dict) -> dict:
    return {"source": c.get("source"), "page": c.get("page"), "section": c.get("section"), "url": c.get("url"),
            "lang": c.get("lang"), "license": c.get("license") or kn.SOURCE_LICENSE.get(c.get("source"), kn.LICENSE),
            "text": c.get("text")}


class Guides:
    """Soluces gardées dans la base du cloud ; une récupération à la fois par jeu, deux en tout (Wikimedia demande
    de ne pas multiplier les requêtes)."""

    def __init__(self, store: Store, fetcher: kn.Fetcher | None = None):
        self.store = store
        self.fetcher = fetcher or kn.Fetcher()
        self._locks: dict[str, asyncio.Lock] = {}
        self._fetching = asyncio.Semaphore(2)

    @staticmethod
    def _fresh(row: dict | None) -> bool:
        if row is None:
            return False
        ttl = REFRESH_FOUND if row["status"] == "found" else REFRESH_MISSING
        return time.time() - row["fetched"] < ttl

    def cached(self, platform_dir: str, title: str) -> bool:
        return self._fresh(self.store.guide(key(platform_dir, title)))

    async def chunks(self, title: str, platform_dir: str) -> dict:
        """{status: found | not_found, sources, chunks} du jeu, récupérés au besoin."""
        k = key(platform_dir, title)
        row = await asyncio.to_thread(self.store.guide, k)
        if self._fresh(row):
            return row
        async with self._locks.setdefault(k, asyncio.Lock()):
            row = await asyncio.to_thread(self.store.guide, k)
            if self._fresh(row):
                return row
            try:
                async with self._fetching:
                    result = await self.fetcher.fetch(title, platform_dir)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log.warning("soluce de %s (%s) : %s", title, platform_dir, exc)
                if row is not None:  # ancienne soluce plutôt que rien
                    return row
                raise GuideUnavailable(str(exc)) from exc
            finally:
                self._locks.pop(k, None)
            row = {"status": result.status, "sources": result.sources, "chunks": result.chunks, "fetched": time.time()}
            await asyncio.to_thread(self.store.put_guide, k, row)
            log.info("soluce de %s (%s) : %s, %s passages", title, platform_dir, result.status, len(result.chunks))
            return row

    async def search(self, title: str, platform_dir: str, query: str = "", limit: int = PASSAGES) -> dict:
        """Passages de la soluce pour une recherche, avec les pages sources (adresse, licence)."""
        row = await self.chunks(title, platform_dir)
        passages = pick(row["chunks"], query, platform_dir, max(1, min(limit, MAX_PASSAGES)))
        pages: dict[str, dict] = {}
        for c in row["chunks"]:
            p = pages.setdefault(c.get("url") or "", {"source": c.get("source"), "page": c.get("page"),
                                                       "url": c.get("url"), "lang": c.get("lang"),
                                                       "license": passage_out(c)["license"]})
            p["passages"] = p.get("passages", 0) + 1
        return {"status": row["status"], "passages": [passage_out(c) for c in passages],
                "sources": [p for u, p in pages.items() if u][:12], "total": len(row["chunks"])}
