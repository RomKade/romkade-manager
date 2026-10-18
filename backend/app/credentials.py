"""Stockage des secrets (mot de passe SSH, clés d'API).

- Sur l'ordinateur : le trousseau du système via keyring (macOS : Trousseau ; Windows : Gestionnaire
  d'identification ; Linux : Secret Service), jamais en clair sur disque.
- Dans le conteneur Docker (ROMKADE_SECRETS=file), ou sans trousseau utilisable : un fichier secrets.json dans le
  dossier de données, lisible par son seul propriétaire (0600), comme le font les applications auto-hébergées.
"""

import json
import os
from pathlib import Path
from typing import Protocol

SERVICE = "anbernic-game-manager"


class CredentialStore(Protocol):
    def get_password(self, host: str, username: str) -> str | None: ...
    def set_password(self, host: str, username: str, password: str) -> None: ...
    def delete_password(self, host: str, username: str) -> None: ...


def _account(host: str, username: str) -> str:
    return f"{username}@{host}"


class KeyringStore:
    def get_password(self, host: str, username: str) -> str | None:
        import keyring

        return keyring.get_password(SERVICE, _account(host, username))

    def set_password(self, host: str, username: str, password: str) -> None:
        import keyring

        keyring.set_password(SERVICE, _account(host, username), password)

    def delete_password(self, host: str, username: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(SERVICE, _account(host, username))
        except PasswordDeleteError:
            pass


class FileStore:
    """Secrets dans un fichier JSON du dossier de données (droits 0600), écrit de façon atomique."""

    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)

    def get_password(self, host: str, username: str) -> str | None:
        return self._read().get(_account(host, username))

    def set_password(self, host: str, username: str, password: str) -> None:
        data = self._read()
        data[_account(host, username)] = password
        self._write(data)

    def delete_password(self, host: str, username: str) -> None:
        data = self._read()
        if data.pop(_account(host, username), None) is not None:
            self._write(data)


def default_store() -> CredentialStore:
    """Trousseau du système, sauf avec ROMKADE_SECRETS=file ou quand keyring n'a aucun trousseau utilisable
    (conteneur, serveur sans session graphique) : fichier secrets.json du dossier de données."""
    from app.config import data_dir

    if os.environ.get("ROMKADE_SECRETS") != "file":
        try:
            import keyring
            from keyring.backends import fail, null

            if not isinstance(keyring.get_keyring(), (fail.Keyring, null.Keyring)):
                return KeyringStore()
        except Exception:  # noqa: BLE001 — keyring absent ou mal configuré : fichier
            pass
    return FileStore(data_dir() / "secrets.json")


class MemoryStore:
    """Pour les tests uniquement."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get_password(self, host: str, username: str) -> str | None:
        return self._data.get(_account(host, username))

    def set_password(self, host: str, username: str, password: str) -> None:
        self._data[_account(host, username)] = password

    def delete_password(self, host: str, username: str) -> None:
        self._data.pop(_account(host, username), None)
