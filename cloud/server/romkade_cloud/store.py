"""Données du cloud ROMKADE : comptes, consoles appairées, catalogue et favoris de chaque console (SQLite).

Les secrets (jeton du compte, secret de la console) ne sont gardés que sous forme d'empreinte SHA-256 : la base
seule ne permet ni de parler au MCP au nom d'un compte, ni de se faire passer pour une console.
"""

import gzip
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ni 0/O ni 1/I : lu sur un petit écran
PAIRING_LENGTH = 6
PAIRING_TTL = 15 * 60
MAX_CONSOLES = 1  # consoles par compte, pour l'instant

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, label TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS consoles (
    id TEXT PRIMARY KEY, secret_hash TEXT UNIQUE NOT NULL, account_id TEXT REFERENCES accounts(id),
    name TEXT, info TEXT NOT NULL DEFAULT '{}', pairing_code TEXT, pairing_expires REAL,
    catalog_at REAL, last_seen REAL, created REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS consoles_pairing ON consoles(pairing_code) WHERE pairing_code IS NOT NULL;
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY, console_id TEXT NOT NULL REFERENCES consoles(id) ON DELETE CASCADE,
    platform_dir TEXT NOT NULL, platform_code TEXT NOT NULL, platform_label TEXT NOT NULL,
    relative_path TEXT NOT NULL, title TEXT NOT NULL, full_title TEXT, normalized TEXT NOT NULL, search TEXT NOT NULL,
    region TEXT, size INTEGER, genre TEXT, year INTEGER, developer TEXT, publisher TEXT, description TEXT,
    art_key TEXT NOT NULL,
    UNIQUE(console_id, platform_dir, relative_path));
CREATE INDEX IF NOT EXISTS games_console ON games(console_id, platform_code);
CREATE INDEX IF NOT EXISTS games_art ON games(art_key);
CREATE TABLE IF NOT EXISTS catalogs (
    console_id TEXT PRIMARY KEY REFERENCES consoles(id) ON DELETE CASCADE, version INTEGER NOT NULL,
    files BLOB NOT NULL, received REAL NOT NULL);
CREATE TABLE IF NOT EXISTS favorites (
    console_id TEXT NOT NULL REFERENCES consoles(id) ON DELETE CASCADE, platform_dir TEXT NOT NULL,
    relative_path TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (console_id, platform_dir, relative_path));
CREATE TABLE IF NOT EXISTS recent (
    console_id TEXT NOT NULL REFERENCES consoles(id) ON DELETE CASCADE, platform_dir TEXT NOT NULL,
    relative_path TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (console_id, platform_dir, relative_path));
CREATE TABLE IF NOT EXISTS google_links (
    account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE, linked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS google_oauth (
    key TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL, at REAL NOT NULL);
"""


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class Console:
    id: str
    account_id: str | None
    name: str | None
    info: dict
    pairing_code: str | None
    pairing_expires: float | None
    catalog_at: float | None
    last_seen: float | None

    @property
    def label(self) -> str:
        return self.name or self.info.get("model") or self.info.get("hostname") or "Console"


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(games)")}
        if cols and "art_key" not in cols:  # ancien schéma du prototype : recalculé depuis la liste brute
            self._db.execute("DROP TABLE games")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    # ---------- comptes ----------
    def create_account(self, label: str | None = None) -> tuple[str, str]:
        """(identifiant, jeton) d'un nouveau compte. Le jeton n'est montré qu'une fois."""
        account_id, token = secrets.token_hex(8), new_secret()
        with self._lock, self._db:
            self._db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?)", (account_id, digest(token), label, time.time()))
        return account_id, token

    def ensure_account(self, account_id: str, label: str | None = None) -> str:
        """Compte d'un utilisateur Supabase (« sb:<id> »), créé à sa première connexion par OAuth.
        Sans jeton dans l'adresse : l'empreinte enregistrée est celle d'un secret jeté aussitôt."""
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO accounts VALUES (?, ?, ?, ?)",
                             (account_id, digest(new_secret()), label, time.time()))
            if label:
                self._db.execute("UPDATE accounts SET label = ? WHERE id = ? AND label IS NOT ?", (label, account_id, label))
        return account_id

    def move_consoles(self, from_account: str, to_account: str) -> int:
        """Rattache les consoles d'un compte à un autre (passage d'un compte à jeton à un compte ROMKADE)."""
        with self._lock, self._db:
            return self._db.execute("UPDATE consoles SET account_id = ? WHERE account_id = ?",
                                    (to_account, from_account)).rowcount

    def accounts(self) -> list[sqlite3.Row]:
        return self._db.execute("SELECT a.id, a.label, a.created, count(c.id) AS consoles FROM accounts a "
                                "LEFT JOIN consoles c ON c.account_id = a.id GROUP BY a.id ORDER BY a.created").fetchall()

    def account_for_token(self, token: str) -> str | None:
        row = self._db.execute("SELECT id FROM accounts WHERE token_hash = ?", (digest(token),)).fetchone()
        return row["id"] if row else None

    # ---------- consoles ----------
    def _console(self, row: sqlite3.Row | None) -> Console | None:
        if row is None:
            return None
        return Console(row["id"], row["account_id"], row["name"], json.loads(row["info"] or "{}"),
                       row["pairing_code"], row["pairing_expires"], row["catalog_at"], row["last_seen"])

    def register_console(self, info: dict) -> tuple[Console, str]:
        """Nouvelle console (pas encore appairée) et son secret, que l'agent garde sur la carte."""
        console_id, secret = secrets.token_hex(8), new_secret()
        with self._lock, self._db:
            self._db.execute("INSERT INTO consoles (id, secret_hash, info, last_seen, created) VALUES (?, ?, ?, ?, ?)",
                             (console_id, digest(secret), json.dumps(info), time.time(), time.time()))
        return self.console(console_id), secret

    def register_console_for(self, account_id: str, info: dict, name: str | None = None) -> tuple[Console, str]:
        """Console déjà rattachée à un compte (liaison depuis le Manager, sans code d'appairage) et son secret."""
        c, secret = self.register_console(info)
        with self._lock, self._db:
            self._db.execute("UPDATE consoles SET account_id = ?, name = ? WHERE id = ?", (account_id, name, c.id))
        return self.console(c.id), secret

    def claim(self, console_id: str, account_id: str, name: str | None = None) -> None:
        """Rattache une console existante à un compte (code d'appairage effacé)."""
        with self._lock, self._db:
            self._db.execute("UPDATE consoles SET account_id = ?, name = COALESCE(?, name), pairing_code = NULL, "
                             "pairing_expires = NULL WHERE id = ?", (account_id, name, console_id))

    def delete_account(self, account_id: str) -> int:
        """Supprime un compte, ses consoles et leurs catalogues. Renvoie le nombre de consoles supprimées."""
        with self._lock, self._db:
            n = self._db.execute("DELETE FROM consoles WHERE account_id = ?", (account_id,)).rowcount
            self._db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        return n

    def console_for_secret(self, secret: str) -> Console | None:
        return self._console(self._db.execute("SELECT * FROM consoles WHERE secret_hash = ?",
                                              (digest(secret),)).fetchone())

    def console(self, console_id: str) -> Console | None:
        return self._console(self._db.execute("SELECT * FROM consoles WHERE id = ?", (console_id,)).fetchone())

    def consoles_of(self, account_id: str) -> list[Console]:
        rows = self._db.execute("SELECT * FROM consoles WHERE account_id = ? ORDER BY created", (account_id,))
        return [self._console(r) for r in rows]

    def update_info(self, console_id: str, info: dict) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE consoles SET info = ?, last_seen = ? WHERE id = ?",
                             (json.dumps(info), time.time(), console_id))

    def touch(self, console_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE consoles SET last_seen = ? WHERE id = ?", (time.time(), console_id))

    def pairing_code(self, console_id: str) -> str:
        """Code d'appairage en cours de la console, renouvelé s'il a expiré."""
        c = self.console(console_id)
        if c and c.pairing_code and (c.pairing_expires or 0) > time.time():
            return c.pairing_code
        with self._lock, self._db:
            while True:
                code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_LENGTH))
                try:
                    self._db.execute("UPDATE consoles SET pairing_code = ?, pairing_expires = ? WHERE id = ?",
                                     (code, time.time() + PAIRING_TTL, console_id))
                    return code
                except sqlite3.IntegrityError:  # code déjà pris par une autre console : on en tire un autre
                    continue

    def pair(self, code: str, account_id: str, name: str | None = None) -> Console | None:
        code = code.strip().upper().replace(" ", "").replace("-", "")
        with self._lock, self._db:
            row = self._db.execute("SELECT id FROM consoles WHERE pairing_code = ? AND pairing_expires > ?",
                                   (code, time.time())).fetchone()
            if row is None:
                return None
            self._db.execute("UPDATE consoles SET account_id = ?, name = COALESCE(?, name), pairing_code = NULL, "
                             "pairing_expires = NULL WHERE id = ?", (account_id, name, row["id"]))
        return self.console(row["id"])

    def rename(self, console_id: str, name: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE consoles SET name = ? WHERE id = ?", (name, console_id))

    def unpair(self, console_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM consoles WHERE id = ?", (console_id,))

    # ---------- catalogue ----------
    def replace_catalog(self, console_id: str, games: list[dict], files: list | None = None,
                        version: int | None = None) -> int:
        """Remplace les jeux d'une console ; garde aussi la liste brute pour les recalculer plus tard."""
        cols = ("platform_dir", "platform_code", "platform_label", "relative_path", "title", "full_title",
                "normalized", "search", "region", "size", "genre", "year", "developer", "publisher", "description",
                "art_key")
        with self._lock, self._db:
            self._db.execute("DELETE FROM games WHERE console_id = ?", (console_id,))
            self._db.executemany(
                f"INSERT OR IGNORE INTO games (console_id, {', '.join(cols)}) "
                f"VALUES (:console_id, {', '.join(':' + c for c in cols)})",
                [{**{c: g.get(c) for c in cols}, "console_id": console_id} for g in games])
            if files is not None:
                self._db.execute("INSERT OR REPLACE INTO catalogs VALUES (?, ?, ?, ?)",
                                 (console_id, version or 0, gzip.compress(json.dumps(files).encode()), time.time()))
            elif version is not None:
                self._db.execute("UPDATE catalogs SET version = ? WHERE console_id = ?", (version, console_id))
            self._db.execute("UPDATE consoles SET catalog_at = ? WHERE id = ?", (time.time(), console_id))
        return len(games)

    def raw_catalogs(self, older_than: int) -> list[tuple[str, list]]:
        """(console, liste brute) des catalogues calculés par une version plus ancienne que `older_than`."""
        rows = self._db.execute("SELECT console_id, files FROM catalogs WHERE version < ?", (older_than,)).fetchall()
        return [(r["console_id"], json.loads(gzip.decompress(r["files"]))) for r in rows]

    def has_raw_catalog(self, console_id: str) -> bool:
        return self._db.execute("SELECT 1 FROM catalogs WHERE console_id = ?", (console_id,)).fetchone() is not None

    def game(self, game_id: int, account_id: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT g.* FROM games g JOIN consoles c ON c.id = g.console_id "
                                "WHERE g.id = ? AND c.account_id = ?", (game_id, account_id)).fetchone()

    @staticmethod
    def _filter(console_ids: list[str], words: list[str], platform_codes: list[str] | None,
                genre: str | None = None) -> tuple[str, list]:
        sql = f"FROM games WHERE console_id IN ({','.join('?' * len(console_ids))})"
        args: list = list(console_ids)
        for w in words:
            sql += " AND (normalized LIKE ? OR search LIKE ?)"
            args += [f"%{w}%", f"%{w}%"]
        if platform_codes:
            sql += f" AND platform_code IN ({','.join('?' * len(platform_codes))})"
            args += platform_codes
        if genre:
            sql += " AND genre = ?"
            args.append(genre)
        return sql, args

    def search(self, console_ids: list[str], words: list[str], platform_codes: list[str] | None,
               limit: int, genre: str | None = None) -> tuple[list[sqlite3.Row], int]:
        """(jeux trouvés, les plus courts d'abord ; nombre total de résultats)."""
        if not console_ids:
            return [], 0
        where, args = self._filter(console_ids, words, platform_codes, genre)
        rows = self._db.execute(f"SELECT * {where} ORDER BY length(normalized), title LIMIT ?", [*args, limit])
        return rows.fetchall(), self._db.execute(f"SELECT count(*) {where}", args).fetchone()[0]

    def platforms(self, console_id: str) -> list[sqlite3.Row]:
        return self._db.execute("SELECT platform_code, platform_label, count(*) AS games FROM games "
                                "WHERE console_id = ? GROUP BY platform_code ORDER BY games DESC",
                                (console_id,)).fetchall()

    def game_by_path(self, console_id: str, platform_dir: str, relative_path: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM games WHERE console_id = ? AND platform_dir = ? AND relative_path = ?",
                                (console_id, platform_dir, relative_path)).fetchone()

    def game_for_art(self, key: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT platform_dir, relative_path, full_title FROM games WHERE art_key = ? LIMIT 1",
                                (key,)).fetchone()

    # ---------- favoris (posés par le Manager sur la carte, envoyés par l'agent) ----------
    def _replace_list(self, table: str, console_id: str, items: list[list[str]]) -> int:
        rows = {(str(d), str(p)): i for i, (d, p) in reversed(list(enumerate(items)))}
        with self._lock, self._db:
            self._db.execute(f"DELETE FROM {table} WHERE console_id = ?", (console_id,))
            self._db.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?)",
                                 [(console_id, d, p, i) for (d, p), i in rows.items()])
        return len(rows)

    def _list(self, table: str, console_id: str, limit: int) -> tuple[list[sqlite3.Row], int]:
        where = (f"FROM {table} f JOIN games g ON g.console_id = f.console_id AND g.platform_dir = f.platform_dir "
                 "AND g.relative_path = f.relative_path WHERE f.console_id = ?")
        rows = self._db.execute(f"SELECT g.* {where} ORDER BY f.position LIMIT ?", (console_id, limit)).fetchall()
        return rows, self._db.execute(f"SELECT count(*) {where}", (console_id,)).fetchone()[0]

    def replace_favorites(self, console_id: str, favorites: list[list[str]]) -> int:
        """Favoris de la console, le dernier ajouté en tête. Gardés par chemin : ils survivent au recalcul du
        catalogue et reviennent si le jeu réapparaît sur la carte."""
        return self._replace_list("favorites", console_id, favorites)

    def favorites(self, console_id: str, limit: int) -> tuple[list[sqlite3.Row], int]:
        """(favoris présents dans le catalogue, le dernier ajouté en tête ; leur nombre)."""
        return self._list("favorites", console_id, limit)

    def replace_recent(self, console_id: str, recent: list[list[str]]) -> int:
        """Jeux joués récemment sur la console (historique de RetroArch, envoyé par l'app ROMKADE), le dernier en tête."""
        return self._replace_list("recent", console_id, recent)

    def recent(self, console_id: str, limit: int) -> tuple[list[sqlite3.Row], int]:
        return self._list("recent", console_id, limit)

    # ---------- Google Home ----------
    def set_google_link(self, account_id: str, linked: bool) -> None:
        """Compte relié à Google Home (SYNC reçu) : on prévient alors Google des changements (Home Graph)."""
        with self._lock, self._db:
            if linked:
                self._db.execute("INSERT OR IGNORE INTO google_links VALUES (?, ?)", (account_id, time.time()))
            else:
                self._db.execute("DELETE FROM google_links WHERE account_id = ?", (account_id,))

    def google_linked(self, account_id: str) -> bool:
        return self._db.execute("SELECT 1 FROM google_links WHERE account_id = ?", (account_id,)).fetchone() is not None

    def oauth_put(self, key: str, kind: str, data: dict) -> None:
        """Connexion Google en cours (état ou code à usage unique), gardée en base : survit à un redémarrage."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM google_oauth WHERE at < ?", (time.time() - 3600,))
            self._db.execute("INSERT OR REPLACE INTO google_oauth VALUES (?, ?, ?, ?)",
                             (key, kind, json.dumps(data), time.time()))

    def oauth_pop(self, key: str, kind: str, ttl: float) -> dict | None:
        """Lit et efface (usage unique) ; None si absent, d'un autre type ou plus vieux que ttl secondes."""
        with self._lock, self._db:
            row = self._db.execute("SELECT kind, data, at FROM google_oauth WHERE key = ?", (key,)).fetchone()
            self._db.execute("DELETE FROM google_oauth WHERE key = ?", (key,))
        if row is None or row[0] != kind or time.time() - row[2] > ttl:
            return None
        return json.loads(row[1])

    def is_favorite(self, console_id: str, platform_dir: str, relative_path: str) -> bool:
        return self._db.execute("SELECT 1 FROM favorites WHERE console_id = ? AND platform_dir = ? AND relative_path = ?",
                                (console_id, platform_dir, relative_path)).fetchone() is not None

    def genres(self, console_id: str) -> list[sqlite3.Row]:
        return self._db.execute("SELECT genre, count(*) AS games FROM games WHERE console_id = ? AND genre IS NOT NULL "
                                "GROUP BY genre ORDER BY games DESC", (console_id,)).fetchall()
