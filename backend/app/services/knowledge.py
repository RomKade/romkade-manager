"""Connaissances sur les jeux, récupérées sans IA, pour l'assistant (RAG) : voir docs/STRATEGIE-IA.md.

1. Wikidata identifie le jeu : élément « jeu vidéo » (Q7889) dont le titre correspond et dont une plateforme (P400)
   est la console du jeu. Il donne les pages Wikipédia (en, fr, es) et l'identifiant StrategyWiki (P9075).
2. Le texte brut vient de l'API MediaWiki (TextExtracts) de Wikipédia et de StrategyWiki : pas de scraping HTML,
   un identifiant ROMKADE dans chaque requête et une requête à la fois, comme le demande Wikimedia.
3. Le texte est découpé en passages (une section, coupée vers 400 mots), rangés avec leur source, leur adresse et
   leur licence (CC BY-SA 4.0 pour les deux sites : à citer quand l'assistant s'en sert).

Rangement par jeu (console + titre normalisé), comme les descriptions et les commandes : une nouvelle ROM d'un jeu
déjà connu (autre région, révision) en profite sans rien récupérer. Un jeu introuvable est noté « not_found » pour
ne pas être recherché à chaque fois ; « Récupérer à nouveau » le remet en jeu.
"""

import asyncio
import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.db.models import GameKnowledge, KnowledgeChunk, Platform, RemoteFile, utcnow
from app.platforms import ALIASES, PLATFORMS, canonical
from app.services.catalog_query import GAME_KINDS_EXCLUDED
from app.services.classify import display_title
from app.services.genres import ARCADE_DIRS

log = logging.getLogger("agm.knowledge")

USER_AGENT = "ROMKADE-Manager/0.4 (https://romkade.com; game knowledge for a local retro game manager)"
WIKIDATA = "https://www.wikidata.org/w/api.php"
WIKIPEDIA = "https://{lang}.wikipedia.org/w/api.php"
STRATEGYWIKI = "https://strategywiki.org/w/api.php"
SEGARETRO = "https://segaretro.org/api.php"
LICENSE = "CC BY-SA 4.0"
# Licence de chaque source (Sega Retro : GNU FDL 1.2 ; les autres : CC BY-SA 4.0).
SOURCE_LICENSE = {"wikipedia": LICENSE, "strategywiki": LICENSE, "segaretro": "GFDL 1.2"}
LANGS = ("en", "fr", "es")
VIDEO_GAME = "Q7889"
PAUSE = 0.25           # entre deux requêtes : une à la fois, sans marteler les serveurs
MAX_GUIDE_PAGES = 25   # sous-pages de soluce StrategyWiki par jeu
CHUNK_WORDS = 400
MIN_WORDS = 12   # une section courte peut tout dire (« Continue mode » de Sega Retro)
SETTINGS_FILE = "knowledge.json"

# Sections sans intérêt pour jouer (sources, liens, notes), dans les trois langues.
SKIP_SECTIONS = {
    "notes", "references", "citations", "bibliography", "external links", "see also", "further reading",
    "sources", "footnotes", "notes et références", "références", "bibliographie", "liens externes", "voir aussi",
    "articles connexes", "notes et sources", "referencias", "enlaces externos", "véase también", "notas",
    "bibliografía", "awards", "distinctions", "premios", "galerie", "gallery",
    # Sega Retro : fiches de collection, sans intérêt pour jouer
    "production credits", "magazine articles", "physical scans", "promotional material", "artwork",
    "digital manuals", "localised names", "technical information", "versions", "external links",
}
# Catégories Sega Retro des jeux de chaque console (« 1987 Master System games ») : page trouvée par son titre
# quand Wikidata ne donne pas de lien, gardée seulement si elle est classée pour cette console.
SEGARETRO_CATEGORY = {"SMS": "Master System games", "MD": "Mega Drive games", "GG": "Game Gear games",
                      "SEGA32X": "32X games", "MDCD": "Mega-CD games", "SATURN": "Saturn games",
                      "DREAMCAST": "Dreamcast games", "SG1000": "SG-1000 games"}
# Sous-pages Sega Retro utiles pour jouer (« Jeu/Hidden content » : continues, niveaux cachés, codes).
SEGARETRO_SUBPAGES = ("hidden content", "hints", "walkthrough", "achievements")
# Sous-pages StrategyWiki les plus utiles d'abord (soluce, secrets, boss, objets…).
# « controls » d'abord : la page des commandes sert aussi à rédiger celles de la fiche (services/controls.py).
GUIDE_PRIORITY = ("controls", "walkthrough", "getting started", "gameplay", "basics", "secret", "boss", "tips", "strateg",
                  "items", "power-up", "power up", "characters", "enemies", "level", "world", "stage", "cheat")


class KnowledgeSettings(BaseModel):
    auto_after_sync: bool = False  # récupérer pour les nouveaux jeux à la fin de chaque synchronisation


class KnowledgeSettingsStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> KnowledgeSettings:
        try:
            return KnowledgeSettings.model_validate_json(self.path.read_text())
        except (OSError, ValueError):
            return KnowledgeSettings()

    def save(self, cfg: KnowledgeSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(cfg.model_dump_json(indent=1))


# ---------- titres et plateformes ----------

def norm(text: str) -> str:
    """Minuscules, sans accents ni ponctuation, sans article « the » : pour comparer des titres et des noms."""
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"^the ", "", s)


def platform_names(directory: str) -> set[str]:
    """Noms possibles de la console d'un dossier de ROMs, normalisés (« super nintendo », « snes »…)."""
    code = canonical(directory)
    names = {norm(code)}
    info = PLATFORMS.get(code)
    if info and info.label:
        names |= {norm(part) for part in re.split(r"[/()]", info.label) if part.strip()}
    names |= {k for k, v in ALIASES.items() if v == code}
    if code in ARCADE_DIRS:  # Wikidata : « arcade video game machine »
        names.add("arcade")
    return {n for n in names if len(n) >= 2}


def _compact(s: str) -> str:
    return s.replace(" ", "")


def platform_matches(ours: set[str], wikidata_names: list[str]) -> bool:
    """Une plateforme de Wikidata (libellés et alias) est-elle la console du jeu ?"""
    compact = {_compact(n) for n in ours}
    for raw in wikidata_names:
        w = norm(raw)
        if not w:
            continue
        if _compact(w) in compact:
            return True
        # « super nintendo » dans « super nintendo entertainment system », « arcade » dans « arcade video game »
        if any(len(n) >= 6 and (n in w or w in n) for n in ours):
            return True
    return False


def title_score(ours: str, names: list[str]) -> float:
    target = norm(ours)
    return max((difflib.SequenceMatcher(None, target, norm(n)).ratio() for n in names if n), default=0.0)


# ---------- découpage ----------

class _HtmlText(HTMLParser):
    """HTML d'une page MediaWiki -> texte à titres « == Section == », tableaux et listes compris (le résumé
    TextExtracts les perd, or les objets, ennemis et niveaux de Sega Retro sont en tableaux)."""
    SKIP_TAGS = {"script", "style", "sup", "figure", "noscript"}
    SKIP_CLASSES = {"mw-editsection", "toc", "navbox", "reference", "mw-references-wrap", "gallery", "thumb",
                    "infobox", "noprint", "metadata", "references"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.skip = 0
        self.stack: list[tuple[str, bool]] = []
        self.heading: int | None = None
        self.cells: list[str] | None = None

    def _flush(self):
        text = " ".join("".join(self.buf).split())
        self.buf.clear()
        if not text:
            return
        if self.heading:
            self.lines.append(f"{'=' * self.heading} {text} {'=' * self.heading}")
        elif self.cells is not None:
            self.cells.append(text)
        else:
            self.lines.append(text)

    def handle_starttag(self, tag, attrs):
        classes = set((dict(attrs).get("class") or "").split())
        skipping = tag in self.SKIP_TAGS or bool(classes & self.SKIP_CLASSES)
        self.stack.append((tag, skipping))
        if skipping:
            self.skip += 1
        if self.skip:
            return
        if tag == "img":  # boutons de manette en images (« appuie sur [1] ») : leur texte de remplacement
            alt = (dict(attrs).get("alt") or "").strip()
            if alt and len(alt) <= 30 and not alt.lower().endswith((".png", ".jpg", ".gif", ".svg")):
                self.buf.append(f" {alt} ")
        elif tag in ("h2", "h3", "h4"):
            self._flush()
            self.heading = int(tag[1])
        elif tag == "tr":
            self._flush()
            self.cells = []
        elif tag in ("td", "th", "p", "li", "div", "dd", "dt", "br"):
            self._flush()
            if tag == "li" and self.cells is None:
                self.buf.append("- ")

    def handle_endtag(self, tag):
        while self.stack:
            t, skipping = self.stack.pop()
            if skipping:
                self.skip -= 1
            if t == tag:
                break
        if self.skip:
            return
        if tag in ("h2", "h3", "h4"):
            self._flush()
            self.heading = None
        elif tag == "tr" and self.cells is not None:
            self._flush()
            row, self.cells = self.cells, None
            if row:
                self.lines.append(" · ".join(row))
        elif tag in ("td", "th", "p", "li", "div", "dd", "dt"):
            self._flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


def html_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    parser._flush()
    return "\n".join(parser.lines)


def chunk_extract(text: str, page: str) -> list[tuple[str, str]]:
    """Texte brut d'une page (titres « == Section == ») -> passages (section, texte) d'environ 400 mots."""
    out: list[tuple[str, str]] = []
    section = page
    skipping = False
    buf: list[str] = []

    def flush():
        words = " ".join(buf).split()
        buf.clear()
        for i in range(0, len(words), CHUNK_WORDS):
            part = words[i:i + CHUNK_WORDS]
            if len(part) >= MIN_WORDS:
                out.append((section, " ".join(part)))

    for line in text.splitlines():
        m = re.match(r"^(=+)\s*(.*?)\s*=+\s*$", line)
        if m:
            if not skipping:
                flush()
            buf.clear()
            title = m.group(2)
            level = len(m.group(1))
            if level <= 2:
                skipping = norm(title) in {norm(s) for s in SKIP_SECTIONS}
                section = title
            elif not skipping:
                section = title
            continue
        if not skipping and line.strip():
            buf.append(line.strip())
    if not skipping:
        flush()
    return out


# ---------- récupération ----------

@dataclass
class Fetched:
    status: str                       # found | not_found
    wikidata: str | None = None
    sources: dict = field(default_factory=dict)  # {wikipedia: {lang: titre}, strategywiki: id}
    chunks: list[dict] = field(default_factory=list)


class Fetcher:
    """Appels aux API de Wikidata, Wikipédia et StrategyWiki. `transport` : remplaçable dans les tests."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=20, transport=self.transport, headers={"User-Agent": USER_AGENT},
                                 follow_redirects=True)

    async def _get(self, http: httpx.AsyncClient, url: str, params: dict) -> dict:
        await asyncio.sleep(PAUSE)
        r = await http.get(url, params={**params, "format": "json", "formatversion": "2"})
        r.raise_for_status()
        return r.json()

    async def find(self, http: httpx.AsyncClient, title: str, directory: str) -> tuple[str, dict] | None:
        """Élément Wikidata du jeu : (QID, entité), ou None. Titre complet, puis titre principal (avant « : » ou
        « - ») : « Street Fighter II' Turbo: Hyper Fighting » n'est trouvé que par « Street Fighter II' Turbo »."""
        tries = list(dict.fromkeys(t.strip() for t in (title, re.split(r":| - ", title)[0]) if t.strip()))
        for query in tries:
            found = await self._find(http, query, title, directory)
            if found:
                return found
        return None

    async def _find(self, http: httpx.AsyncClient, query: str, title: str, directory: str) -> tuple[str, dict] | None:
        hits = (await self._get(http, WIKIDATA, {"action": "wbsearchentities", "search": query, "language": "en",
                                                 "type": "item", "limit": "8"})).get("search", [])
        if not hits:
            return None
        ids = "|".join(h["id"] for h in hits)
        ents = (await self._get(http, WIKIDATA, {"action": "wbgetentities", "ids": ids,
                                                 "props": "claims|sitelinks|labels|aliases",
                                                 "languages": "en|mul|fr|es",
                                                 "sitefilter": "enwiki|frwiki|eswiki"})).get("entities", {})
        games = {q: e for q, e in ents.items() if VIDEO_GAME in _claim_ids(e, "P31")}
        if not games:
            return None
        platform_ids = sorted({p for e in games.values() for p in _claim_ids(e, "P400")})
        plabels: dict[str, list[str]] = {}
        for i in range(0, len(platform_ids), 40):
            batch = "|".join(platform_ids[i:i + 40])
            pents = (await self._get(http, WIKIDATA, {"action": "wbgetentities", "ids": batch,
                                                      "props": "labels|aliases", "languages": "en|mul"}))
            for q, e in pents.get("entities", {}).items():
                plabels[q] = _names(e)
        ours = platform_names(directory)
        best: tuple[float, str] | None = None
        for q, e in games.items():
            if not any(platform_matches(ours, plabels.get(p, [])) for p in _claim_ids(e, "P400")):
                continue
            score = title_score(title, _names(e))
            if score >= 0.88 and (best is None or score > best[0]):
                best = (score, q)
        if best is None:
            # Fiche sans la bonne console (Wikidata incomplet : « Wonder Boy » n'y cite pas la Master System) :
            # retenue seulement si c'est le seul jeu qui porte exactement ce titre.
            exact = [q for q, e in games.items() if title_score(title, _names(e)) >= 0.999]
            if len(exact) == 1:
                return exact[0], games[exact[0]]
        return (best[1], games[best[1]]) if best else None

    async def segaretro_page(self, http: httpx.AsyncClient, names: list[str], directory: str) -> str | None:
        """Page Sega Retro du jeu cherchée par son titre, si elle est classée dans les jeux de cette console."""
        suffix = SEGARETRO_CATEGORY.get(canonical(directory))
        if not suffix:
            return None
        for name in dict.fromkeys(n for n in names if n):
            data = await self._get(http, SEGARETRO, {"action": "query", "prop": "categories", "titles": name,
                                                     "cllimit": "500", "redirects": "1"})
            for page in data.get("query", {}).get("pages", []):
                if page.get("missing") or page.get("title", "").startswith("Category:"):
                    continue
                if any(c["title"].endswith(suffix) for c in page.get("categories", [])):
                    return page["title"].replace(" ", "_")
        return None

    async def wikipedia(self, http: httpx.AsyncClient, lang: str, page: str) -> list[dict]:
        data = await self._get(http, WIKIPEDIA.format(lang=lang), {"action": "query", "prop": "extracts",
                                                                     "explaintext": "1", "titles": page})
        pages = data.get("query", {}).get("pages", [])
        text = pages[0].get("extract", "") if pages else ""
        url = f"https://{lang}.wikipedia.org/wiki/{quote(page.replace(' ', '_'))}"
        return [{"source": "wikipedia", "lang": lang, "page": page, "section": s, "url": url, "text": t}
                for s, t in chunk_extract(text, page)]

    async def strategywiki(self, http: httpx.AsyncClient, guide: str) -> list[dict]:
        main = guide.replace("_", " ")
        listing = await self._get(http, STRATEGYWIKI, {"action": "query", "list": "allpages",
                                                       "apprefix": f"{main}/", "aplimit": "200"})
        subpages = [p["title"] for p in listing.get("query", {}).get("allpages", [])]

        def rank(title: str) -> int:
            low = title.lower()
            return next((i for i, k in enumerate(GUIDE_PRIORITY) if k in low), len(GUIDE_PRIORITY))

        pages = [main] + sorted(subpages, key=rank)[:MAX_GUIDE_PAGES - 1]
        chunks: list[dict] = []
        for page in pages:
            data = await self._get(http, STRATEGYWIKI, {"action": "query", "prop": "extracts", "explaintext": "1",
                                                        "titles": page})
            found = data.get("query", {}).get("pages", [])
            text = found[0].get("extract", "") if found else ""
            url = f"https://strategywiki.org/wiki/{quote(page.replace(' ', '_'))}"
            chunks += [{"source": "strategywiki", "lang": "en", "page": page, "section": s, "url": url, "text": t}
                       for s, t in chunk_extract(text, page.split("/")[-1])]
        return chunks

    async def segaretro(self, http: httpx.AsyncClient, page_id: str) -> list[dict]:
        """Sega Retro (jeux Sega) : page du jeu (histoire, objets, ennemis, boss, niveaux, astuces) et sous-pages
        utiles (contenu caché…), lues en HTML pour garder les tableaux."""
        main = page_id.replace("_", " ")
        listing = await self._get(http, SEGARETRO, {"action": "query", "list": "allpages", "apprefix": f"{main}/",
                                                    "aplimit": "100"})
        subpages = [p["title"] for p in listing.get("query", {}).get("allpages", [])
                    if any(k in p["title"].split("/")[-1].lower() for k in SEGARETRO_SUBPAGES)]
        chunks: list[dict] = []
        for page in [main, *subpages]:
            data = await self._get(http, SEGARETRO, {"action": "parse", "page": page, "prop": "text",
                                                     "disabletoc": "1", "redirects": "1"})
            html = (data.get("parse") or {}).get("text") or ""
            if isinstance(html, dict):  # formatversion 1
                html = html.get("*", "")
            url = f"https://segaretro.org/{quote(page.replace(' ', '_'))}"
            chunks += [{"source": "segaretro", "lang": "en", "page": page, "url": url, "section": sec, "text": t,
                        "license": SOURCE_LICENSE["segaretro"]}
                       for sec, t in chunk_extract(html_text(html), page.split("/")[-1])]
        return chunks

    async def fetch(self, title: str, directory: str) -> Fetched:
        async with self._client() as http:
            found = await self.find(http, title, directory)
            if not found:
                return Fetched("not_found")
            qid, ent = found
            wiki = {lang: ent["sitelinks"][f"{lang}wiki"]["title"] for lang in LANGS
                    if f"{lang}wiki" in ent.get("sitelinks", {})}
            guide = next((v for v in _claim_values(ent, "P9075") if isinstance(v, str)), None)
            chunks: list[dict] = []
            for lang, page in wiki.items():
                chunks += await self.wikipedia(http, lang, page)
            if guide:
                chunks += await self.strategywiki(http, guide)
            sega = next((v for v in _claim_values(ent, "P7517") if isinstance(v, str)), None)  # Sega Retro ID
            if not sega:
                sega = await self.segaretro_page(http, [ent.get("labels", {}).get("en", {}).get("value"), title],
                                                 directory)
            if sega:
                chunks += await self.segaretro(http, sega)
            sources = {"wikipedia": wiki, **({"strategywiki": guide} if guide else {}),
                       **({"segaretro": sega} if sega else {})}
            return Fetched("found" if chunks else "not_found", qid, sources, chunks)


def _claim_values(entity: dict, prop: str) -> list:
    return [c.get("mainsnak", {}).get("datavalue", {}).get("value") for c in entity.get("claims", {}).get(prop, [])]


def _claim_ids(entity: dict, prop: str) -> list[str]:
    return [v["id"] for v in _claim_values(entity, prop) if isinstance(v, dict) and "id" in v]


def _names(entity: dict) -> list[str]:
    names = [v["value"] for v in entity.get("labels", {}).values()]
    names += [a["value"] for vals in entity.get("aliases", {}).values() for a in vals]
    return names


# ---------- base ----------

def game_key(platform_id: int, normalized_title: str) -> str:
    return f"{platform_id}:{normalized_title}"


def _games_query():
    return (select(RemoteFile.platform_id, RemoteFile.normalized_title).join(Platform)
            .where(RemoteFile.role == "candidate", RemoteFile.deleted_at.is_(None),
                   Platform.kind.not_in(GAME_KINDS_EXCLUDED))
            .distinct())


def coverage(s: Session) -> dict:
    games = s.scalar(select(func.count()).select_from(_games_query().subquery())) or 0
    rows = dict(s.execute(select(GameKnowledge.status, func.count()).group_by(GameKnowledge.status)).all())
    chunks = s.scalar(select(func.count(KnowledgeChunk.id))) or 0
    found, not_found = rows.get("found", 0), rows.get("not_found", 0)
    return {"games": games, "found": found, "not_found": not_found, "errors": rows.get("error", 0),
            "pending": max(0, games - found - not_found - rows.get("error", 0)), "chunks": chunks}


def pending_games(s: Session, limit: int | None = None) -> list[tuple[int, str]]:
    """Jeux de la carte jamais recherchés (ni trouvés, ni introuvables, ni en erreur)."""
    rows = s.execute(_games_query().order_by(RemoteFile.platform_id, RemoteFile.normalized_title)).all()
    known = set(s.execute(select(GameKnowledge.platform_id, GameKnowledge.normalized_title)).all())
    out = [(p, t) for p, t in rows if (p, t) not in known]
    return out[:limit] if limit else out


def representative(s: Session, platform_id: int, normalized_title: str) -> RemoteFile | None:
    return s.scalars(select(RemoteFile).options(joinedload(RemoteFile.platform)).where(
        RemoteFile.platform_id == platform_id, RemoteFile.normalized_title == normalized_title,
        RemoteFile.role == "candidate").order_by(RemoteFile.deleted_at.is_not(None), RemoteFile.id)).first()


def search_title(f: RemoteFile) -> str:
    return display_title(f.full_title) if f.full_title else f.title


def store(s: Session, platform_id: int, normalized_title: str, result: Fetched, error: str | None = None) -> GameKnowledge:
    row = s.scalar(select(GameKnowledge).where(GameKnowledge.platform_id == platform_id,
                                               GameKnowledge.normalized_title == normalized_title))
    row = row or GameKnowledge(platform_id=platform_id, normalized_title=normalized_title)
    s.execute(delete(KnowledgeChunk).where(KnowledgeChunk.platform_id == platform_id,
                                           KnowledgeChunk.normalized_title == normalized_title))
    row.status = "error" if error else result.status
    row.wikidata_id, row.sources, row.error, row.fetched_at = result.wikidata, result.sources, error, utcnow()
    row.chunks = len(result.chunks)
    s.add(row)
    for i, c in enumerate(result.chunks):
        c = dict(c)
        lic = c.pop("license", None) or SOURCE_LICENSE.get(c["source"], LICENSE)
        s.add(KnowledgeChunk(platform_id=platform_id, normalized_title=normalized_title, position=i,
                             license=lic, **c))
    return row


def game_out(s: Session, platform_id: int, normalized_title: str) -> dict:
    row = s.scalar(select(GameKnowledge).where(GameKnowledge.platform_id == platform_id,
                                               GameKnowledge.normalized_title == normalized_title))
    if row is None:
        return {"status": "none", "sources": [], "chunks": 0, "sections": [], "fetched_at": None, "error": None}
    pages = s.execute(select(KnowledgeChunk.source, KnowledgeChunk.lang, KnowledgeChunk.page, KnowledgeChunk.url,
                             func.count(KnowledgeChunk.id))
                      .where(KnowledgeChunk.platform_id == platform_id,
                             KnowledgeChunk.normalized_title == normalized_title)
                      .group_by(KnowledgeChunk.source, KnowledgeChunk.lang, KnowledgeChunk.page, KnowledgeChunk.url)
                      .order_by(func.min(KnowledgeChunk.position))).all()
    sections = s.scalars(select(KnowledgeChunk.section).where(
        KnowledgeChunk.platform_id == platform_id, KnowledgeChunk.normalized_title == normalized_title)
        .order_by(KnowledgeChunk.position).limit(12)).all()
    return {"status": row.status, "fetched_at": row.fetched_at, "error": row.error, "chunks": row.chunks,
            "sources": [{"source": src, "lang": lang, "page": page, "url": url, "chunks": n,
                         "license": SOURCE_LICENSE.get(src, LICENSE)}
                        for src, lang, page, url, n in pages],
            "sections": list(dict.fromkeys(sections))}


def best_chunks(s: Session, platform_id: int, normalized_title: str, question: str, limit: int = 4,
                ids: list[int] | None = None) -> list[KnowledgeChunk]:
    """Passages pour une question : ceux choisis par Typesense (`ids`), sinon classés ici par mots en commun
    (repli sans Typesense), en gardant toujours l'introduction quand rien ne ressort."""
    chunks = chunks_for(s, platform_id, normalized_title)
    if ids:
        by_id = {c.id: c for c in chunks}
        return [by_id[i] for i in ids if i in by_id][:limit]
    words = {w for w in norm(question).split() if len(w) > 2}
    scored = sorted(((sum(w in norm(c.text + " " + c.section) for w in words), -c.position, c) for c in chunks),
                    key=lambda x: (x[0], x[1]), reverse=True)
    picked = [c for score, _, c in scored if score > 0][:limit]
    return picked or chunks[:min(limit, 2)]


def chunks_for(s: Session, platform_id: int, normalized_title: str) -> list[KnowledgeChunk]:
    return list(s.scalars(select(KnowledgeChunk).where(KnowledgeChunk.platform_id == platform_id,
                                                        KnowledgeChunk.normalized_title == normalized_title)
                          .order_by(KnowledgeChunk.position)))


# ---------- tâche de fond ----------

class KnowledgeJobs:
    """Une récupération à la fois (tous les jeux en attente), suivie par GET /api/knowledge."""

    def __init__(self, sessions: sessionmaker[Session], fetcher: Fetcher, settings: KnowledgeSettingsStore):
        self.sessions = sessions
        self.fetcher = fetcher
        self.settings = settings
        self.task: asyncio.Task | None = None
        self.state = {"running": False, "total": 0, "done": 0, "found": 0, "current": None, "stopping": False}

    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def fetch_one(self, platform_id: int, normalized_title: str) -> str:
        def ref():
            with self.sessions() as s:
                f = representative(s, platform_id, normalized_title)
                return (search_title(f), f.platform.directory) if f else (None, None)

        title, directory = await asyncio.to_thread(ref)
        if title is None:
            return "not_found"
        try:
            result = await self.fetcher.fetch(title, directory)
            error = None
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("connaissances : %s (%s) : %s", title, directory, exc)
            result, error = Fetched("not_found"), f"{type(exc).__name__}: {exc}"[:300]

        def save():
            with self.sessions.begin() as s:
                return store(s, platform_id, normalized_title, result, error).status

        return await asyncio.to_thread(save)

    def start(self, refresh: bool = False) -> bool:
        """Jeux jamais recherchés ; avec `refresh`, tous les jeux à nouveau (nouvelle source, pages mises à jour)."""
        if self.running():
            return False
        self.task = asyncio.create_task(self._run(refresh))
        return True

    def stop(self) -> None:
        if self.running():
            self.state["stopping"] = True

    async def _run(self, refresh: bool = False) -> None:
        def todo():
            with self.sessions() as s:
                if refresh:  # les jamais recherchés d'abord, puis les autres
                    pending = pending_games(s)
                    return pending + [g for g in s.execute(_games_query().order_by(
                        RemoteFile.platform_id, RemoteFile.normalized_title)).all() if tuple(g) not in set(pending)]
                return pending_games(s)

        games = await asyncio.to_thread(todo)
        self.state.update(running=True, total=len(games), done=0, found=0, current=None, stopping=False)
        try:
            for platform_id, title in games:
                if self.state["stopping"]:
                    break
                self.state["current"] = title
                if await self.fetch_one(platform_id, title) == "found":
                    self.state["found"] += 1
                self.state["done"] += 1
        except Exception:  # noqa: BLE001 — la tâche s'arrête, ce qui est fait reste fait
            log.exception("connaissances")
        finally:
            self.state.update(running=False, current=None, stopping=False)

    async def after_sync(self) -> None:
        """Appelé à la fin d'une synchronisation : récupère pour les nouveaux jeux si l'option est active."""
        if not self.settings.load().auto_after_sync:
            return

        def count():
            with self.sessions() as s:
                return coverage(s)["pending"]

        if await asyncio.to_thread(count):
            self.start()


def settings_store(data_dir: Path) -> KnowledgeSettingsStore:
    return KnowledgeSettingsStore(data_dir / SETTINGS_FILE)
