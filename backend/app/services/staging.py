"""Zone d'attente locale : les fichiers envoyés par le navigateur y sont écrits avant le transfert SFTP.

Chaque envoi a son dossier `<data_dir>/staging/<id>/` contenant `data` et `meta.json`.
L'empreinte SHA-256 est calculée pendant la réception, sans relire le fichier.
"""

import hashlib
import json
import os
import re
import shutil
import unicodedata
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app import errors

MAX_UPLOAD_BYTES = 16 * 1024**3  # 16 Gio, au-delà de toute ROM réaliste
UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")

# Caractères interdits par exFAT/FAT32 (carte microSD) et par la prudence.
FORBIDDEN_CHARS = set('<>:"/\\|?*')


def validate_filename(name: str) -> str:
    """Valide un nom de fichier destiné à la carte. Lève AppError(invalid_filename) avec la raison."""
    def bad(reason: str) -> errors.AppError:
        return errors.AppError("invalid_filename", f"Nom de fichier refusé : {reason}", 400, {"filename": name})

    n = unicodedata.normalize("NFC", name or "")
    if not n or n.strip() != n:
        raise bad("vide ou entouré d'espaces")
    if n.startswith("."):
        raise bad("commence par un point (fichier caché)")
    if n.endswith("."):
        raise bad("se termine par un point")
    if any(c in FORBIDDEN_CHARS for c in n):
        raise bad('contient un caractère interdit sur la carte (< > : " / \\ | ? *)')
    if any(ord(c) < 32 or ord(c) == 127 for c in n):
        raise bad("contient un caractère de contrôle")
    if len(n.encode()) > 240:
        raise bad("trop long (240 octets maximum)")
    if n in (".", ".."):
        raise bad("nom réservé")
    return n


@dataclass
class Upload:
    id: str
    filename: str
    size: int
    sha256: str
    received_at: str

    def public(self) -> dict:
        return asdict(self)


class StagingStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, upload_id: str) -> Path:
        if not UPLOAD_ID.fullmatch(upload_id):
            raise errors.AppError("upload_not_found", "Envoi introuvable", 404, {"id": upload_id})
        return self.root / upload_id

    def data_path(self, upload_id: str) -> Path:
        return self._dir(upload_id) / "data"

    async def receive(self, filename: str, chunks: AsyncIterator[bytes]) -> Upload:
        name = validate_filename(filename)
        upload_id = uuid.uuid4().hex
        d = self.root / upload_id
        d.mkdir()
        h, size = hashlib.sha256(), 0
        try:
            with open(d / "data.part", "wb") as fh:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise errors.AppError("file_too_large", "Fichier trop volumineux (16 Gio maximum)", 413)
                    h.update(chunk)
                    fh.write(chunk)
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
        if size == 0:
            shutil.rmtree(d, ignore_errors=True)
            raise errors.AppError("empty_file", "Le fichier est vide", 400, {"filename": name})
        os.replace(d / "data.part", d / "data")
        up = Upload(upload_id, name, size, h.hexdigest(), datetime.now(UTC).isoformat())
        (d / "meta.json").write_text(json.dumps(asdict(up)))
        return up

    def get(self, upload_id: str) -> Upload:
        d = self._dir(upload_id)
        try:
            return Upload(**json.loads((d / "meta.json").read_text()))
        except FileNotFoundError as exc:
            raise errors.AppError("upload_not_found", "Envoi introuvable (déjà transféré ou supprimé)", 404,
                                  {"id": upload_id}) from exc

    def list(self) -> list[Upload]:
        out = []
        for d in sorted(self.root.iterdir()):
            if UPLOAD_ID.fullmatch(d.name) and (d / "meta.json").exists():
                out.append(Upload(**json.loads((d / "meta.json").read_text())))
        return out

    def delete(self, upload_id: str) -> None:
        shutil.rmtree(self._dir(upload_id), ignore_errors=True)
