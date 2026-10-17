"""Écritures dans les dossiers de sauvegarde de la console : restaurer et supprimer une sauvegarde.

Périmètre strict, distinct de remote_writer (qui n'écrit que dans le dossier des ROMs) :
- seuls les chemins acceptés par saves.is_save_path (emplacements de sauvegarde connus, nom de fichier
  de sauvegarde) sont touchés ;
- aucun dossier du chemin n'est un lien symbolique ;
- une restauration écrit d'abord `.agm-<jeton>.part` dans le même dossier, puis renomme ;
- l'appelant garde une copie sur le Mac de tout fichier remplacé ou supprimé (SaveVault).
"""

import posixpath
import secrets
import stat as statmod

import asyncssh

from app import errors
from app.services.saves import SOURCES, is_save_path


class SaveWriter:
    def __init__(self, sftp: asyncssh.SFTPClient, base: str, roms_root: str, sources=SOURCES, rom_states: bool = False):
        self._sftp = sftp
        self.sources = sources
        self.rom_states = rom_states
        self.base = base.rstrip("/")
        self.roms_root = roms_root.rstrip("/")

    async def _guard(self, path: str) -> None:
        if not is_save_path(path, self.base, self.roms_root, self.sources, self.rom_states):
            raise errors.path_forbidden(path, "pas un emplacement de sauvegarde")
        # Aucun lien symbolique sur le chemin, depuis la carte jusqu'au fichier.
        parts = path[len(self.base) + 1:].split("/")
        cur = self.base
        for part in parts:
            cur = f"{cur}/{part}"
            try:
                attrs = await self._sftp.lstat(cur)
            except asyncssh.SFTPNoSuchFile:
                return  # la suite n'existe pas encore : pas de lien possible
            if attrs.permissions is not None and statmod.S_ISLNK(attrs.permissions):
                raise errors.path_forbidden(cur, "lien symbolique")

    async def _makedirs(self, directory: str) -> None:
        cur = self.base
        for part in directory[len(self.base) + 1:].split("/"):
            cur = f"{cur}/{part}"
            try:
                await self._sftp.mkdir(cur)
            except asyncssh.SFTPFailure:
                pass  # existe déjà

    async def exists(self, path: str) -> bool:
        try:
            await self._sftp.lstat(path)
            return True
        except asyncssh.SFTPNoSuchFile:
            return False

    async def write(self, path: str, data: bytes) -> None:
        await self._guard(path)
        directory = posixpath.dirname(path)
        await self._makedirs(directory)
        temp = f"{directory}/.agm-{secrets.token_hex(16)}.part"
        async with self._sftp.open(temp, "wb") as fh:
            await fh.write(data)
        try:
            if await self.exists(path):
                await self._sftp.remove(path)
            await self._sftp.rename(temp, path)
        except Exception:
            try:
                await self._sftp.remove(temp)
            except asyncssh.SFTPError:
                pass
            raise

    async def remove(self, path: str) -> None:
        await self._guard(path)
        try:
            await self._sftp.remove(path)
        except asyncssh.SFTPNoSuchFile as exc:
            raise errors.remote_not_found(path) from exc
