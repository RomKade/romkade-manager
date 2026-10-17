"""Façade SFTP strictement en lecture seule.

Seule interface du backend vers le système de fichiers de la console en phase 1.
Elle n'expose AUCUNE méthode d'écriture (open en écriture, remove, rename, mkdir, setstat...).
"""

import shlex
import stat as statmod
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncssh

from app import errors
from app.config import SAFE_REMOTE_PATH
from app.device.paths import is_within


@dataclass(frozen=True)
class Entry:
    name: str
    path: str
    kind: str  # "dir" | "file" | "symlink" | "other"
    size: int | None
    modified_at: datetime | None


@dataclass(frozen=True)
class Storage:
    path: str
    total_bytes: int
    free_bytes: int
    used_bytes: int
    method: str  # "sftp_statvfs" | "df"


def _kind(attrs: asyncssh.SFTPAttrs) -> str:
    perms = attrs.permissions
    if perms is not None:
        if statmod.S_ISLNK(perms):
            return "symlink"
        if statmod.S_ISDIR(perms):
            return "dir"
        if statmod.S_ISREG(perms):
            return "file"
        return "other"
    t = attrs.type
    return {
        asyncssh.FILEXFER_TYPE_DIRECTORY: "dir",
        asyncssh.FILEXFER_TYPE_REGULAR: "file",
        asyncssh.FILEXFER_TYPE_SYMLINK: "symlink",
    }.get(t, "other")


def _mtime(attrs: asyncssh.SFTPAttrs) -> datetime | None:
    return datetime.fromtimestamp(attrs.mtime, UTC) if attrs.mtime is not None else None


class ReadOnlyRemoteFS:
    def __init__(self, conn: asyncssh.SSHClientConnection, sftp: asyncssh.SFTPClient, root: str):
        self._conn = conn
        self._sftp = sftp
        self.root = root.rstrip("/")

    def _check(self, path: str) -> str:
        if not is_within(self.root, path):
            raise errors.path_forbidden(path, "hors de la racine")
        return path

    async def root_exists(self) -> bool:
        try:
            attrs = await self._sftp.stat(self.root)
        except asyncssh.SFTPNoSuchFile:
            return False
        return _kind(attrs) == "dir"

    async def listdir(self, path: str) -> list[Entry]:
        """Liste un dossier sans suivre les liens symboliques (attributs de readdir = lstat)."""
        self._check(path)
        try:
            names = await self._sftp.readdir(path)
        except asyncssh.SFTPNoSuchFile as exc:
            raise errors.remote_not_found(path) from exc
        except asyncssh.SFTPPermissionDenied as exc:
            raise errors.AppError("remote_permission_denied", "Accès refusé", 403, {"path": path}) from exc
        out: list[Entry] = []
        for n in names:
            name = n.filename if isinstance(n.filename, str) else n.filename.decode(errors="replace")
            if name in (".", ".."):
                continue
            kind = _kind(n.attrs)
            out.append(Entry(name, f"{path.rstrip('/')}/{name}", kind,
                             n.attrs.size if kind == "file" else None, _mtime(n.attrs)))
        return out

    async def lstat(self, path: str) -> Entry:
        self._check(path)
        try:
            attrs = await self._sftp.lstat(path)
        except asyncssh.SFTPNoSuchFile as exc:
            raise errors.remote_not_found(path) from exc
        kind = _kind(attrs)
        return Entry(path.rsplit("/", 1)[-1], path, kind, attrs.size if kind == "file" else None, _mtime(attrs))

    async def resolves_inside_root(self, path: str) -> bool:
        """Vrai si la cible réelle (liens résolus) reste sous la racine."""
        self._check(path)
        try:
            real = await self._sftp.realpath(path)
        except asyncssh.SFTPError:
            return False
        real_root = await self._sftp.realpath(self.root)
        return is_within(real_root, real)

    async def read_file(self, path: str, max_bytes: int) -> bytes:
        """Lecture d'un petit fichier régulier (images). Ouverture en 'rb' uniquement."""
        entry = await self.lstat(path)
        if entry.kind != "file":
            raise errors.path_forbidden(path, "pas un fichier régulier")
        if entry.size is not None and entry.size > max_bytes:
            raise errors.AppError("file_too_large", "Fichier trop volumineux", 413, {"size": entry.size})
        async with self._sftp.open(path, "rb") as fh:
            data = await fh.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise errors.AppError("file_too_large", "Fichier trop volumineux", 413)
        return data

    async def storage(self) -> Storage:
        try:
            v = await self._sftp.statvfs(self.root)
            frsize = v.frsize or v.bsize
            total, free = v.blocks * frsize, v.bavail * frsize
            return Storage(self.root, total, free, total - v.bfree * frsize, "sftp_statvfs")
        except (asyncssh.SFTPOpUnsupported, asyncssh.SFTPError):
            pass
        return await self._storage_df()

    async def _storage_df(self) -> Storage:
        # Commande fixe, chemin issu des réglages validés (regex) puis échappé. Lecture seule.
        if not SAFE_REMOTE_PATH.fullmatch(self.root):
            raise errors.path_forbidden(self.root, "racine non sûre pour df")
        result = await self._conn.run(f"df -kP {shlex.quote(self.root)}", check=False, timeout=10)
        lines = [ln for ln in str(result.stdout or "").splitlines() if ln.strip()]
        if result.exit_status != 0 or len(lines) < 2:
            raise errors.AppError("storage_unavailable", "Impossible de mesurer l'espace disque", 502,
                                  {"stderr": str(result.stderr or "")[:300]})
        cols = lines[-1].split()
        total_k, used_k, avail_k = int(cols[1]), int(cols[2]), int(cols[3])
        return Storage(self.root, total_k * 1024, avail_k * 1024, used_k * 1024, "df")
