"""Recherche des jeux avec Typesense : tolérante aux fautes de frappe, par préfixe, classée par pertinence.

Game Manager a son propre serveur Typesense, dans un conteneur Docker (CONTAINER), joignable seulement depuis
ce Mac (127.0.0.1:PORT), données et clé d'API dans le dossier de données de l'application. Variables pour
utiliser un autre serveur : AGM_TYPESENSE_URL et AGM_TYPESENSE_KEY ; AGM_TYPESENSE=0 pour s'en passer.

L'index « games » reprend les jeux du catalogue (fichiers candidats, hors APPS/PORTS). Il est reconstruit au
démarrage puis dès que le catalogue change (synchronisation, ajout de jeux, veille de la carte, genres), vérifié
toutes les VERSION_SECONDS. « games » est un alias : chaque reconstruction remplit une nouvelle collection
(games_<n>) puis bascule l'alias dessus, si bien que la recherche n'est jamais coupée pendant la mise à jour.
Serveur absent : nouvel essai toutes les CHECK_SECONDS ; la bibliothèque garde alors la recherche SQLite d'origine.
"""

import asyncio
import json
import logging
import os
import secrets
import time
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.db.models import KnowledgeChunk, Platform, RemoteFile, ScanRun
from app.services.classify import display_title
from app.services.genres import GENRES, UNCLASSIFIED
from app.services.subgenres import LABELS as SUB_LABELS
from app.services.subgenres import OTHER_LABELS as SUB_OTHER

log = logging.getLogger("agm.search")
IMAGE = "typesense/typesense:27.1"
CONTAINER = "agm-typesense"
PORT = 8118
COLLECTION = "games"
KNOWLEDGE = "knowledge"
THEME_POSITIONS = 3  # passages d'un article retenus pour un thème : introduction et présentation du jeu
KNOWLEDGE_SETTLE = 15  # secondes sans changement avant de reconstruire l'index des connaissances
KNOWLEDGE_SCHEMA = {
    "fields": [
        {"name": "game", "type": "string", "facet": True},   # « plateforme:titre normalisé »
        {"name": "source", "type": "string", "facet": True},
        {"name": "lang", "type": "string", "facet": True},
        {"name": "page", "type": "string"},
        {"name": "section", "type": "string"},
        {"name": "text", "type": "string"},
        {"name": "position", "type": "int32"},
    ],
    "default_sorting_field": "position",
}
CHECK_SECONDS = 30
VERSION_SECONDS = 2  # une requête d'agrégats sur le catalogue : quelques millisecondes
EXCLUDED_KINDS = ("apps", "ports")

SCHEMA = {
    "name": COLLECTION,
    "fields": [
        {"name": "title", "type": "string"},
        {"name": "full_title", "type": "string", "optional": True},
        {"name": "filename", "type": "string"},
        {"name": "platform", "type": "string", "facet": True},
        {"name": "platform_label", "type": "string", "optional": True},
        {"name": "genre", "type": "string", "facet": True},
        {"name": "genre_label", "type": "string", "optional": True},
        {"name": "regions", "type": "string[]", "facet": True, "optional": True},
        {"name": "extension", "type": "string", "facet": True, "optional": True},
        # Informations du jeu (gameinfo.py) et libellés en français, anglais, espagnol : on cherche « 1991 »,
        # « Capcom », « Japon » / « Japan » / « Japón », « Sports » / « Deportes ».
        {"name": "year", "type": "int32", "facet": True, "optional": True},
        {"name": "year_text", "type": "string", "optional": True},
        {"name": "developer", "type": "string", "facet": True, "optional": True},
        {"name": "publisher", "type": "string", "facet": True, "optional": True},
        {"name": "franchise", "type": "string", "optional": True},
        {"name": "region_names", "type": "string[]", "optional": True},
        {"name": "genre_names", "type": "string[]", "optional": True},
        {"name": "subgenre", "type": "string", "facet": True, "optional": True},
        {"name": "subgenre_names", "type": "string[]", "optional": True},
        {"name": "present", "type": "bool"},
        {"name": "sort_title", "type": "string", "sort": True},
        {"name": "size", "type": "int64"},
        {"name": "mtime", "type": "int64"},
        {"name": "first_seen", "type": "int64"},
    ],
    "default_sorting_field": "first_seen",
    "token_separators": ["-", "_", ".", ":", "'"],
}
QUERY_BY = ("title,full_title,filename,platform_label,genre_label,franchise,publisher,developer,year_text,"
            "region_names,genre_names,subgenre_names")
QUERY_WEIGHTS = "6,5,2,1,1,3,2,2,2,1,1,1"

# Régions (libellés du catalogue, classify.REGION_TAGS) et genres, dans les trois langues de l'interface,
# avec les variantes courantes, pour la recherche.
REGION_NAMES: dict[str, list[str]] = {
    "USA": ["USA", "États-Unis", "Etats-Unis", "Amérique", "United States", "America", "EE. UU.", "Estados Unidos"],
    "Europe": ["Europe", "Europa"],
    "Japon": ["Japon", "Japan", "Japón"],
    "Monde": ["Monde", "World", "Mundo"],
    "France": ["France", "Francia"],
    "Allemagne": ["Allemagne", "Germany", "Alemania"],
    "Espagne": ["Espagne", "Spain", "España"],
    "Italie": ["Italie", "Italy", "Italia"],
    "Corée": ["Corée", "Korea", "Corea"],
    "Brésil": ["Brésil", "Brazil", "Brasil"],
    "Asie": ["Asie", "Asia"],
    "Australie": ["Australie", "Australia"],
    "Chine": ["Chine", "China"],
}
GENRE_NAMES: dict[str, list[str]] = {
    "action": ["Action", "Acción"], "aventure": ["Aventure", "Adventure", "Aventura"],
    "beat": ["Beat'em up", "Beat 'em up"], "combat": ["Combat", "Fighting", "Lucha"],
    "course": ["Course", "Racing", "Carreras"], "plateforme": ["Plateforme", "Platformer", "Plataformas"],
    "rpg": ["Jeu de rôle", "RPG", "Role-playing", "Rol"], "shmup": ["Shoot'em up", "Shoot 'em up", "Shmup"],
    "tir": ["Tir", "Shooter", "Disparos"], "sport": ["Sport", "Sports", "Deportes"],
    "reflexion": ["Réflexion", "Puzzle", "Puzle"], "labyrinthe": ["Labyrinthe", "Maze", "Laberinto"],
    "strategie": ["Stratégie", "Strategy", "Estrategia"], "simulation": ["Simulation", "Simulación"],
    "flipper": ["Flipper", "Pinball"], "societe": ["Société", "Casino", "Board", "Mesa"],
    "quiz": ["Quiz", "Preguntas"], "musique": ["Musique", "Rythme", "Music", "Rhythm", "Música", "Ritmo"],
    "educatif": ["Éducatif", "Educational", "Educativo"], "compilation": ["Compilation", "Recopilación"],
    "autre": ["Autre", "Other", "Otros"],
}
SORT_FIELDS = {"name": "sort_title", "size": "size", "date": "mtime", "added": "first_seen", "year": "year"}


def _quote(value: str) -> str:
    return "`" + value.replace("`", "") + "`"


def build_filter(*, platforms=None, extensions=None, regions=None, genres=None, subgenres=None,
                 include_removed=False) -> str:
    parts = []
    if platforms:
        parts.append(f"platform:=[{','.join(_quote(p) for p in platforms)}]")
    if extensions:
        parts.append(f"extension:=[{','.join(_quote(e.lower().lstrip('.')) for e in extensions)}]")
    if regions:
        parts.append(f"regions:=[{','.join(_quote(r) for r in regions)}]")
    if genres:
        parts.append(f"genre:=[{','.join(_quote(g) for g in genres)}]")
    if subgenres:
        parts.append(f"subgenre:=[{','.join(_quote(g) for g in subgenres)}]")
    if not include_removed:
        parts.append("present:=true")
    return " && ".join(parts)


def build_sort(sort: str, order: str, has_query: bool) -> str:
    # Avec une recherche et le tri par défaut (titre A→Z), la pertinence passe d'abord.
    if has_query and sort == "name" and order == "asc":
        return "_text_match:desc,sort_title:asc"
    if sort == "year":  # jeux sans année connue à la fin, puis A→Z dans une même année
        return f"year(missing_values: last):{order},sort_title:asc"
    return f"{SORT_FIELDS.get(sort, 'sort_title')}:{order}"


def to_document(f: RemoteFile) -> dict:
    ts = lambda d: int(d.timestamp()) if d else 0  # noqa: E731
    doc = {
        "id": str(f.id),
        "title": display_title(f.full_title) if f.full_title else f.title,
        "filename": f.filename,
        "platform": f.platform.directory,
        "genre": f.genre or UNCLASSIFIED,
        "present": f.deleted_at is None,
        "sort_title": f.normalized_title or f.title.lower(),
        "size": f.size or 0,
        "mtime": ts(f.mtime),
        "first_seen": ts(f.first_seen_at),
    }
    if f.full_title:
        doc["full_title"] = f.full_title
    if f.platform.label:
        doc["platform_label"] = f.platform.label
    if f.genre:
        doc["genre_label"] = GENRES.get(f.genre, f.genre)
    if f.region:
        doc["regions"] = f.region.split(", ")
    if f.extension:
        doc["extension"] = f.extension
    if f.release_year:
        doc["year"] = f.release_year
        doc["year_text"] = str(f.release_year)
    for field in ("developer", "publisher", "franchise"):
        if value := getattr(f, field):
            doc[field] = value
    if f.region:
        doc["region_names"] = [n for r in f.region.split(", ") for n in REGION_NAMES.get(r, [r])]
    if f.genre in GENRE_NAMES:
        doc["genre_names"] = GENRE_NAMES[f.genre]
    if f.subgenre in SUB_LABELS:
        doc["subgenre"] = f.subgenre
        doc["subgenre_names"] = [SUB_LABELS[f.subgenre], *SUB_OTHER.get(f.subgenre, ())]
    return doc


def catalog_version(s: Session) -> tuple:
    """Change dès que le catalogue change (nombre, fichiers, genres, informations, synchronisations)."""
    q = select(func.count(RemoteFile.id), func.max(RemoteFile.id), func.count(RemoteFile.genre),
               func.count(RemoteFile.release_year), func.count(RemoteFile.publisher), func.count(RemoteFile.subgenre),
               func.count(RemoteFile.deleted_at), func.max(RemoteFile.last_seen_at))
    return tuple(s.execute(q).one()) + (s.scalar(select(func.max(ScanRun.id))),)


class SearchService:
    def __init__(self, sessions: sessionmaker[Session], data_dir: Path, transport: httpx.AsyncBaseTransport | None = None):
        self.sessions = sessions
        self.data_dir = data_dir
        self.url = os.environ.get("AGM_TYPESENSE_URL", f"http://127.0.0.1:{PORT}")
        self.managed = "AGM_TYPESENSE_URL" not in os.environ
        self.key = os.environ.get("AGM_TYPESENSE_KEY") or self._load_key()
        self.transport = transport
        self.ready = False
        self.status = "starting"
        self._version: tuple | None = None
        self._kversion: tuple | None = None
        self._kseen: tuple | None = None  # (version vue, depuis quand)
        self._task: asyncio.Task | None = None

    def _load_key(self) -> str:
        path = self.data_dir / "typesense.key"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secrets.token_hex(24))
            path.chmod(0o600)
        return path.read_text().strip()

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.url, timeout=10, transport=self.transport,
                                 headers={"X-TYPESENSE-API-KEY": self.key})

    # ---------- serveur ----------

    def start(self) -> None:
        if os.environ.get("AGM_TYPESENSE") == "0":
            self.status = "disabled"
            return
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _docker(self, *args: str) -> tuple[int, str]:
        try:
            p = await asyncio.create_subprocess_exec("docker", *args, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.STDOUT)
        except FileNotFoundError:
            return 127, "docker introuvable"
        out, _ = await p.communicate()
        return p.returncode or 0, out.decode(errors="replace").strip()

    async def ensure_server(self) -> bool:
        if await self.healthy():
            if await self.authorized():
                return True
            if not self.managed:
                log.warning("Typesense : clé d'API refusée par %s", self.url)
                return False
            # Conteneur créé avec une autre clé (dossier de données différent) : on le recrée.
            log.warning("Typesense : clé refusée, conteneur %s recréé", CONTAINER)
            await self._docker("rm", "-f", CONTAINER)
        if not self.managed:
            # Serveur externe (service Typesense du compose.yaml) : il peut démarrer après l'application.
            for _ in range(30):
                await asyncio.sleep(1)
                if await self.healthy():
                    return await self.authorized()
            return False
        code, out = await self._docker("inspect", "-f", "{{.State.Running}}", CONTAINER)
        if code == 0 and out != "true":
            await self._docker("start", CONTAINER)
        elif code != 0:
            data = self.data_dir / "typesense"
            data.mkdir(parents=True, exist_ok=True)
            code, out = await self._docker(
                "run", "-d", "--name", CONTAINER, "--restart", "unless-stopped",
                "-p", f"127.0.0.1:{PORT}:8108", "-v", f"{data}:/data", IMAGE,
                "--data-dir", "/data", "--api-key", self.key)
            if code != 0:
                log.warning("Typesense : conteneur non créé (%s)", out[-300:])
                return False
        for _ in range(30):
            if await self.healthy():
                return await self.authorized()
            await asyncio.sleep(1)
        return False

    async def authorized(self) -> bool:
        try:
            async with self._http() as http:
                return (await http.get("/collections")).status_code == 200
        except httpx.HTTPError:
            return False

    async def healthy(self) -> bool:
        try:
            async with self._http() as http:
                r = await http.get("/health")
                return r.status_code == 200 and r.json().get("ok") is True
        except (httpx.HTTPError, ValueError):
            return False

    async def _loop(self) -> None:
        while True:
            try:
                if not self.ready:
                    if await self.ensure_server():
                        await self.reindex()
                    else:
                        self.status = "unavailable"
                else:
                    version = await asyncio.to_thread(self._version_now)
                    if version != self._version:
                        await self.reindex()
                    # Connaissances : reconstruites quand la base n'a plus bougé depuis 15 s (pas à chaque jeu
                    # d'une récupération en lot).
                    kversion = await asyncio.to_thread(self._knowledge_version)
                    if kversion == self._kversion:
                        self._kseen = None
                    elif self._kseen is None or self._kseen[0] != kversion:
                        self._kseen = (kversion, time.monotonic())
                    elif time.monotonic() - self._kseen[1] >= KNOWLEDGE_SETTLE or self._kversion is None:
                        await self.reindex_knowledge()
                        self._kseen = None
            except Exception:  # noqa: BLE001 — la recherche SQLite prend le relais
                log.exception("Typesense")
                self.ready, self.status = False, "unavailable"
            await asyncio.sleep(VERSION_SECONDS if self.ready else CHECK_SECONDS)

    def _version_now(self) -> tuple:
        with self.sessions() as s:
            return catalog_version(s)

    # ---------- index ----------

    def _documents(self) -> tuple[list[dict], tuple]:
        with self.sessions() as s:
            version = catalog_version(s)
            rows = s.scalars(select(RemoteFile).join(Platform).options(joinedload(RemoteFile.platform))
                             .where(RemoteFile.role == "candidate", Platform.kind.not_in(EXCLUDED_KINDS)))
            return [to_document(f) for f in rows], version

    async def _publish(self, alias: str, schema: dict, docs: list[dict]) -> None:
        """Nouvelle collection remplie, puis bascule de l'alias : la recherche n'est jamais coupée."""
        name = f"{alias}_{time.time_ns()}"
        async with self._http() as http:
            r = await http.post("/collections", json={**schema, "name": name})
            if r.status_code not in (200, 201):
                raise RuntimeError(f"création de l'index : {r.status_code} {r.text[:200]}")
            try:
                if docs:
                    body = "\n".join(json.dumps(d, ensure_ascii=False) for d in docs)
                    r = await http.post(f"/collections/{name}/documents/import", params={"action": "create"},
                                        content=body.encode(), headers={"Content-Type": "text/plain"}, timeout=120)
                    failed = [line for line in r.text.splitlines() if '"success":false' in line]
                    if failed:
                        log.warning("Typesense : %d documents refusés (%s)", len(failed), failed[0][:200])
                if (await http.get(f"/aliases/{alias}")).status_code != 200:
                    # Index d'une version précédente : une vraie collection de ce nom, sans alias.
                    await http.delete(f"/collections/{alias}")
                r = await http.put(f"/aliases/{alias}", json={"collection_name": name})
                if r.status_code != 200:
                    raise RuntimeError(f"bascule de l'index : {r.status_code} {r.text[:200]}")
            except BaseException:
                await http.delete(f"/collections/{name}")
                raise
            # Anciennes collections (la précédente, ou celles d'une reconstruction interrompue).
            r = await http.get("/collections")
            for c in r.json() if r.status_code == 200 else []:
                if c["name"].startswith(f"{alias}_") and c["name"] != name:
                    await http.delete(f"/collections/{c['name']}")

    async def reindex(self) -> int:
        docs, version = await asyncio.to_thread(self._documents)
        await self._publish(COLLECTION, SCHEMA, docs)
        self._version, self.ready, self.status = version, True, "ready"
        log.info("Typesense : %d jeux indexés", len(docs))
        return len(docs)

    # ---------- connaissances (assistant) ----------

    def _knowledge_version(self) -> tuple:
        with self.sessions() as s:
            return tuple(s.execute(select(func.count(KnowledgeChunk.id), func.max(KnowledgeChunk.id))).one())

    def _knowledge_documents(self) -> tuple[list[dict], tuple]:
        with self.sessions() as s:
            version = tuple(s.execute(select(func.count(KnowledgeChunk.id), func.max(KnowledgeChunk.id))).one())
            docs = [{"id": str(c.id), "game": f"{c.platform_id}:{c.normalized_title}", "source": c.source,
                     "lang": c.lang, "page": c.page, "section": c.section, "text": c.text, "position": c.position}
                    for c in s.scalars(select(KnowledgeChunk))]
        return docs, version

    async def reindex_knowledge(self) -> int:
        docs, version = await asyncio.to_thread(self._knowledge_documents)
        await self._publish(KNOWLEDGE, KNOWLEDGE_SCHEMA, docs)
        self._kversion = version
        log.info("Typesense : %d passages de connaissances indexés", len(docs))
        return len(docs)

    async def search_knowledge(self, game: str, q: str, limit: int = 4) -> list[int]:
        """Passages d'un jeu (« plateforme:titre normalisé ») les plus proches de la question."""
        params = {"q": q or "*", "query_by": "text,section,page", "query_by_weights": "3,2,1",
                  "filter_by": f"game:=`{game.replace('`', '')}`", "per_page": str(limit),
                  "prefix": "false", "num_typos": "1", "drop_tokens_threshold": "10", "include_fields": "id"}
        async with self._http() as http:
            r = await http.get(f"/collections/{KNOWLEDGE}/documents/search", params=params)
        if r.status_code != 200:
            raise RuntimeError(f"recherche Typesense : {r.status_code} {r.text[:200]}")
        return [int(h["document"]["id"]) for h in r.json().get("hits", [])]

    async def search_knowledge_games(self, phrase: str, limit: int = 20) -> list[str]:
        """Jeux (« plateforme:titre normalisé ») dont la présentation parle d'un thème (« wild west »), pour les thèmes
        qui ne sont pas des genres du catalogue. Seuls les premiers passages des encyclopédies comptent (introduction,
        présentation du jeu) : plus loin, « western » est le côté ouest d'un château ou la version occidentale."""
        params = {"q": f'"{phrase.replace(chr(34), "")}"', "query_by": "text", "group_by": "game", "group_limit": "1",
                  "filter_by": f"source:=[wikipedia,segaretro] && position:<={THEME_POSITIONS}",
                  "per_page": str(limit), "prefix": "false", "num_typos": "0", "drop_tokens_threshold": "0",
                  "include_fields": "game", "highlight_fields": "none"}
        async with self._http() as http:
            r = await http.get(f"/collections/{KNOWLEDGE}/documents/search", params=params)
        if r.status_code != 200:
            raise RuntimeError(f"recherche Typesense : {r.status_code} {r.text[:200]}")
        return [g["group_key"][0] for g in r.json().get("grouped_hits", []) if g.get("group_key")]

    # ---------- recherche ----------

    async def search(self, q: str, *, platforms=None, extensions=None, regions=None, genres=None, subgenres=None,
                     include_removed=False, sort="name", order="asc", offset=0, limit=60) -> tuple[list[int], int]:
        """(identifiants des jeux dans l'ordre, total). Pagination Typesense : page = offset/limit + 1."""
        params = {
            "q": q or "*", "query_by": QUERY_BY, "query_by_weights": QUERY_WEIGHTS,
            "prefix": "true", "num_typos": "2", "typo_tokens_threshold": "1",
            "per_page": str(limit), "page": str(offset // limit + 1),
            "sort_by": build_sort(sort, order, bool(q and q.strip())),
            "include_fields": "id", "highlight_fields": "none",
        }
        flt = build_filter(platforms=platforms, extensions=extensions, regions=regions, genres=genres,
                           subgenres=subgenres, include_removed=include_removed)
        if flt:
            params["filter_by"] = flt
        async with self._http() as http:
            r = await http.get(f"/collections/{COLLECTION}/documents/search", params=params)
        if r.status_code != 200:
            raise RuntimeError(f"recherche Typesense : {r.status_code} {r.text[:200]}")
        data = r.json()
        return [int(h["document"]["id"]) for h in data.get("hits", [])], int(data.get("found", 0))
