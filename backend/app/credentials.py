"""Stockage du mot de passe SSH : trousseau macOS via keyring, jamais en clair sur disque."""

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
