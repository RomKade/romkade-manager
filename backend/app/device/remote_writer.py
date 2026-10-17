"""Seule porte d'écriture vers la console.

Périmètre strict :
- écriture uniquement dans un dossier de plateforme existant, directement sous la racine des ROMs,
  qui n'est pas un lien symbolique et n'est ni APPS ni PORTS ;
- un fichier est d'abord écrit sous un nom temporaire `.agm-<jeton>.part`, puis renommé ;
- un fichier existant n'est jamais écrasé : il est déplacé dans `<racine>/.agm-backups/<plateforme>/` ;
- la seule suppression possible concerne nos propres fichiers temporaires (motif vérifié) ;
- aucun chemin venant du navigateur n'entre dans une commande shell : le calcul d'empreinte porte
  sur le fichier temporaire, dont le nom est généré ici.
"""

import posixpath
import re
import shlex
import stat as statmod
from collections.abc import Callable
from datetime import UTC, datetime

import asyncssh

from app import errors
from app.device.paths import is_within
from app.services.staging import validate_filename

TEMP_RE = re.compile(r"^\.agm-[0-9a-f]{32}\.part$")
BACKUP_DIR = ".agm-backups"
FORBIDDEN_TARGETS = {"APPS", "PORTS"}
BLOCK_SIZE = 256 * 1024
MAX_REQUESTS = 32


class RemoteWriter:
    def __init__(self, conn: asyncssh.SSHClientConnection, sftp: asyncssh.SFTPClient, root: str):
        self._conn = conn
        self._sftp = sftp
        self.root = root.rstrip("/")
        self._sha256_available: bool | None = None

    # ---------- garde ----------

    async def platform_dir(self, platform: str) -> str:
        """Chemin d'un dossier de plateforme autorisé, vérifié sur la console."""
        if not platform or "/" in platform or platform.startswith(".") or platform in FORBIDDEN_TARGETS:
            raise errors.AppError("platform_not_allowed", "Ce dossier ne peut pas recevoir de fichiers", 400,
                                  {"platform": platform})
        path = f"{self.root}/{platform}"
        try:
            attrs = await self._sftp.lstat(path)
        except asyncssh.SFTPNoSuchFile as exc:
            raise errors.AppError("platform_not_found", "Dossier de plateforme introuvable sur la console", 404,
                                  {"platform": platform}) from exc
        if attrs.permissions is None or not statmod.S_ISDIR(attrs.permissions):
            raise errors.AppError("platform_not_allowed", "Ce dossier est un lien ou n'est pas un dossier", 400,
                                  {"platform": platform})
        return path

    def final_path(self, platform_path: str, filename: str) -> str:
        name = validate_filename(filename)
        path = posixpath.join(platform_path, name)
        if posixpath.dirname(path) != platform_path or not is_within(self.root, path):
            raise errors.path_forbidden(path, "hors du dossier de plateforme")
        return path

    def temp_path(self, platform_path: str, token: str) -> str:
        name = f".agm-{token}.part"
        if not TEMP_RE.fullmatch(name):
            raise errors.path_forbidden(name, "jeton invalide")
        return f"{platform_path}/{name}"

    # ---------- lectures utiles au plan ----------

    async def names_in(self, platform_path: str) -> dict[str, int | None]:
        """Noms présents dans le dossier (tous types), avec leur taille pour les fichiers."""
        out: dict[str, int | None] = {}
        for n in await self._sftp.readdir(platform_path):
            name = n.filename if isinstance(n.filename, str) else n.filename.decode(errors="replace")
            if name not in (".", ".."):
                out[name] = n.attrs.size
        return out

    async def free_bytes(self) -> int | None:
        """Espace libre (statvfs SFTP, sinon df). None seulement si aucune des deux méthodes ne répond."""
        from app.device.remote_fs import ReadOnlyRemoteFS
        try:
            return (await ReadOnlyRemoteFS(self._conn, self._sftp, self.root).storage()).free_bytes
        except errors.AppError:
            return None

    async def exists(self, path: str) -> int | None:
        """Taille si le chemin existe, None sinon."""
        try:
            return (await self._sftp.lstat(path)).size
        except asyncssh.SFTPNoSuchFile:
            return None

    # ---------- écritures ----------

    async def upload_temp(self, local_path: str, platform_path: str, token: str,
                          progress: Callable[[int, int], None]) -> str:
        temp = self.temp_path(platform_path, token)
        await self._sftp.put(local_path, temp, block_size=BLOCK_SIZE, max_requests=MAX_REQUESTS,
                             progress_handler=lambda _s, _d, done, total: progress(done, total))
        return temp

    async def sha256(self, temp_path: str) -> str | None:
        """Empreinte calculée sur la console, None si `sha256sum` n'y est pas disponible."""
        if not TEMP_RE.fullmatch(posixpath.basename(temp_path)):
            raise errors.path_forbidden(temp_path, "seul un fichier temporaire peut être vérifié ainsi")
        if self._sha256_available is False:
            return None
        r = await self._conn.run(f"sha256sum {shlex.quote(temp_path)}", check=False, timeout=1800)
        if r.exit_status != 0:
            self._sha256_available = False if r.exit_status == 127 else self._sha256_available
            return None
        self._sha256_available = True
        out = str(r.stdout or "").split()
        return out[0].lower() if out and re.fullmatch(r"[0-9a-fA-F]{64}", out[0]) else None

    async def move_to_backup(self, platform: str, existing_path: str) -> str:
        """Déplace un fichier existant vers le dossier de sauvegarde (même carte : aucun espace consommé)."""
        backup_root = f"{self.root}/{BACKUP_DIR}"
        backup_dir = f"{backup_root}/{platform}"
        for d in (backup_root, backup_dir):
            try:
                await self._sftp.mkdir(d)
            except asyncssh.SFTPFailure:
                if await self.exists(d) is None:
                    raise
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        target = f"{backup_dir}/{posixpath.basename(existing_path)}.{stamp}"
        await self._sftp.rename(existing_path, target)
        return target

    async def restore_backup(self, backup_path: str, original_path: str) -> None:
        if await self.exists(original_path) is None:
            await self._sftp.rename(backup_path, original_path)

    async def finalize(self, temp_path: str, final_path: str) -> None:
        if not TEMP_RE.fullmatch(posixpath.basename(temp_path)):
            raise errors.path_forbidden(temp_path, "pas un fichier temporaire")
        if await self.exists(final_path) is not None:
            raise errors.AppError("conflict_appeared", "Un fichier du même nom est apparu entre-temps", 409,
                                  {"path": final_path})
        await self._sftp.rename(temp_path, final_path)

    async def remove_temp(self, temp_path: str) -> bool:
        """Supprime un de nos fichiers temporaires. Refuse tout autre chemin."""
        if not TEMP_RE.fullmatch(posixpath.basename(temp_path)) or not is_within(self.root, temp_path):
            raise errors.path_forbidden(temp_path, "seuls les fichiers temporaires de l'application peuvent être supprimés")
        try:
            await self._sftp.remove(temp_path)
            return True
        except asyncssh.SFTPNoSuchFile:
            return False

    async def sweep_temps(self, platform_path: str) -> int:
        """Nettoie les fichiers temporaires laissés par un transfert interrompu."""
        removed = 0
        for name in await self.names_in(platform_path):
            if TEMP_RE.fullmatch(name):
                removed += await self.remove_temp(f"{platform_path}/{name}")
        return removed
