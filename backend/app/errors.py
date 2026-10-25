"""Erreurs applicatives avec codes stables, sérialisées en JSON structuré."""

from typing import Any


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


# Erreurs de réseau : console éteinte ou introuvable, SSH refusé, réseau local bloqué par macOS (voir diagnose.py).
NETWORK_CODES = frozenset({"device_unreachable", "device_ssh_refused", "local_network_blocked"})


def device_unreachable(host: str, port: int, reason: str) -> AppError:
    return AppError("device_unreachable", f"Console injoignable sur {host}:{port}", 503, {"reason": reason})


def auth_failed() -> AppError:
    return AppError("device_auth_failed", "Authentification SSH refusée par la console", 502)


def credentials_missing() -> AppError:
    return AppError("credentials_missing", "Aucun mot de passe enregistré dans le trousseau", 409)


def console_not_configured() -> AppError:
    return AppError("console_not_configured", "Aucune console indiquée : saisis son adresse dans Paramètres > Connexion.", 409)


def host_key_unknown(fingerprint: str | None = None) -> AppError:
    return AppError(
        "host_key_unknown",
        "La clé de cette console n'est pas encore approuvée : vérifie son empreinte et approuve-la dans "
        "Paramètres > Connexion.",
        409,
        {"fingerprint": fingerprint},
    )


def host_key_mismatch() -> AppError:
    return AppError(
        "host_key_mismatch",
        "La clé d'hôte ne correspond pas à celle enregistrée. Connexion bloquée.",
        409,
    )


def sftp_unavailable(reason: str) -> AppError:
    return AppError("sftp_unavailable", "Le sous-système SFTP n'est pas disponible sur la console", 502, {"reason": reason})


def path_forbidden(path: str, reason: str) -> AppError:
    return AppError("path_forbidden", "Chemin refusé", 400, {"path": path, "reason": reason})


def remote_not_found(path: str) -> AppError:
    return AppError("remote_not_found", "Chemin introuvable sur la console", 404, {"path": path})
