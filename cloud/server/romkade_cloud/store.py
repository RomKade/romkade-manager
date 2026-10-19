"""Données du cloud ROMKADE : comptes, consoles appairées, catalogue de chaque console (SQLite).

Les secrets (jeton du compte, secret de la console) ne sont gardés que sous forme d'empreinte SHA-256 : la base
seule ne permet ni de parler au MCP au nom d'un compte, ni de se faire passer pour une console.
"""

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
    relative_path TEXT NOT NULL, title TEXT NOT NULL, normalized TEXT NOT NULL, region TEXT, size INTEGER,
    UNIQUE(console_id, platform_dir, relative_path));
CREATE INDEX IF NOT EXISTS games_console ON games(console_id, platform_code);
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
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    # ---------- comptes ----------
    def create_account(self, label: str | None = None) -> tuple[str, str]:
        """(identifiant, jeton) d'un nouveau compte. Le jeton n'est montré qu'une fois."""
        account_id, token = secrets.token_hex(8), new_secret()
        with self._lock, self._db:
            self._db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?)", (account_id, digest(token), label, time.time()))
        return account_id, token

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
    def replace_catalog(self, console_id: str, games: list[dict]) -> int:
        with self._lock, self._db:
            self._db.execute("DELETE FROM games WHERE console_id = ?", (console_id,))
            self._db.executemany(
                "INSERT OR IGNORE INTO games (console_id, platform_dir, platform_code, platform_label, relative_path, "
                "title, normalized, region, size) VALUES (:console_id, :platform_dir, :platform_code, "
                ":platform_label, :relative_path, :title, :normalized, :region, :size)",
                [{**g, "console_id": console_id} for g in games])
            self._db.execute("UPDATE consoles SET catalog_at = ? WHERE id = ?", (time.time(), console_id))
        return len(games)

    def game(self, game_id: int, account_id: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT g.* FROM games g JOIN consoles c ON c.id = g.console_id "
                                "WHERE g.id = ? AND c.account_id = ?", (game_id, account_id)).fetchone()

    @staticmethod
    def _filter(console_ids: list[str], words: list[str], platform_codes: list[str] | None) -> tuple[str, list]:
        sql = f"FROM games WHERE console_id IN ({','.join('?' * len(console_ids))})"
        args: list = list(console_ids)
        for w in words:
            sql += " AND normalized LIKE ?"
            args.append(f"%{w}%")
        if platform_codes:
            sql += f" AND platform_code IN ({','.join('?' * len(platform_codes))})"
            args += platform_codes
        return sql, args

    def search(self, console_ids: list[str], words: list[str], platform_codes: list[str] | None,
               limit: int) -> tuple[list[sqlite3.Row], int]:
        """(jeux trouvés, les plus courts d'abord ; nombre total de résultats)."""
        if not console_ids:
            return [], 0
        where, args = self._filter(console_ids, words, platform_codes)
        rows = self._db.execute(f"SELECT * {where} ORDER BY length(normalized), title LIMIT ?", [*args, limit])
        return rows.fetchall(), self._db.execute(f"SELECT count(*) {where}", args).fetchone()[0]

    def platforms(self, console_id: str) -> list[sqlite3.Row]:
        return self._db.execute("SELECT platform_code, platform_label, count(*) AS games FROM games "
                                "WHERE console_id = ? GROUP BY platform_code ORDER BY games DESC",
                                (console_id,)).fetchall()

    def game_by_path(self, console_id: str, platform_dir: str, relative_path: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM games WHERE console_id = ? AND platform_dir = ? AND relative_path = ?",
                                (console_id, platform_dir, relative_path)).fetchone()
