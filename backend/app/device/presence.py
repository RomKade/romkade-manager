"""Console en veille plutôt qu'« injoignable » : si elle a répondu à cette adresse il y a peu (12 h), une console
qui ne répond plus est le plus souvent en veille (sommeil profond : son Wi-Fi est coupé) ou éteinte. Le message
le dit et invite à la réveiller ; la connexion revient seule (l'état est revérifié toutes les 12 s)."""

import time

from app.errors import AppError

ASLEEP_WINDOW = 12 * 3600


class Presence:
    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def seen(self, host: str) -> None:
        self._seen[host] = time.monotonic()

    def recently(self, host: str) -> bool:
        t = self._seen.get(host)
        return t is not None and time.monotonic() - t < ASLEEP_WINDOW

    def explain(self, exc: AppError, host: str) -> AppError:
        """« injoignable » d'une console vue récemment -> « en veille », même statut HTTP."""
        if exc.code != "device_unreachable" or not self.recently(host):
            return exc
        return AppError("device_asleep", "La console ne répond plus : elle est sans doute en veille (ou éteinte). "
                        "Réveille-la : ROMKADE Manager la retrouve tout seul.", exc.status, {**exc.details, "host": host})
