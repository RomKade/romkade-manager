"""Copies des sauvegardes sur le Mac : instantanés datés, un dossier par copie, avec un manifeste.

<données>/save-backups/<AAAAMMJJ-HHMMSS>[-auto]/<chemin relatif à la carte>   + manifest.json
Les copies « auto » sont faites par l'application avant toute restauration ou suppression.
"""

import io
import json
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app import errors

ID_RE = re.compile(r"^\d{8}-\d{6}(-auto)?(-\d+)?$")


class SaveVault:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, snap_id: str) -> Path:
        if not ID_RE.fullmatch(snap_id):
            raise errors.AppError("backup_not_found", "Copie introuvable", 404, {"id": snap_id})
        d = self.root / snap_id
        if not (d / "manifest.json").exists():
            raise errors.AppError("backup_not_found", "Copie introuvable", 404, {"id": snap_id})
        return d

    @staticmethod
    def _safe_rel(rel: str) -> str:
        if not rel or rel.startswith("/") or any(p in ("", ".", "..") for p in rel.split("/")) or "\x00" in rel:
            raise errors.path_forbidden(rel, "chemin de copie refusé")
        return rel

    def create(self, files: list[tuple[str, bytes, dict]], auto: bool = False) -> dict:
        """files : (chemin relatif, contenu, infos). Renvoie le manifeste."""
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + ("-auto" if auto else "")
        snap_id, n = stamp, 1
        while (self.root / snap_id).exists():
            n += 1
            snap_id = f"{stamp}-{n}"
        d = self.root / snap_id
        d.mkdir(parents=True)
        entries = []
        for rel, data, info in files:
            target = d / self._safe_rel(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            entries.append({"rel": rel, "size": len(data), **info})
        manifest = {"id": snap_id, "created_at": datetime.now(UTC).isoformat(), "auto": auto,
                    "files": entries, "bytes": sum(e["size"] for e in entries)}
        (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
        return manifest

    def list(self) -> list[dict]:
        out = []
        for d in sorted(self.root.iterdir(), reverse=True):
            m = d / "manifest.json"
            if d.is_dir() and ID_RE.fullmatch(d.name) and m.exists():
                out.append(json.loads(m.read_text()))
        return out

    def manifest(self, snap_id: str) -> dict:
        return json.loads((self._dir(snap_id) / "manifest.json").read_text())

    def read(self, snap_id: str, rel: str) -> bytes:
        p = self._dir(snap_id) / self._safe_rel(rel)
        if not p.is_file():
            raise errors.AppError("backup_file_not_found", "Fichier absent de cette copie", 404, {"rel": rel})
        return p.read_bytes()

    def zip(self, snap_id: str) -> bytes:
        d = self._dir(snap_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(d).as_posix())
        return buf.getvalue()

    def delete(self, snap_id: str) -> None:
        shutil.rmtree(self._dir(snap_id))
