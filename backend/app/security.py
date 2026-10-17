"""Protection du serveur local contre les autres sites ouverts dans le navigateur.

Le serveur n'écoute que sur 127.0.0.1, mais une page web quelconque peut quand même envoyer des
requêtes à http://127.0.0.1:8765 depuis le navigateur de l'utilisateur. Deux contrôles :
- en-tête Host : seul localhost / 127.0.0.1 est accepté (bloque le « DNS rebinding ») ;
- en-tête Origin : une requête qui modifie quelque chose (POST, PUT, DELETE…) venant d'une autre
  origine que l'interface elle-même est refusée.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _hostname(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[: value.find("]") + 1]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp, extra_hosts: set[str] | None = None):
        self.app = app
        self.hosts = LOCAL_HOSTS | (extra_hosts or set())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        host = _hostname(headers.get("host", ""))
        if host not in self.hosts:
            return await self._deny(scope, receive, send, "host_not_allowed", "Accès réservé à ce Mac (localhost)")
        origin = headers.get("origin")
        if scope["method"] not in SAFE_METHODS and origin and origin != "null":
            o = origin.split("://", 1)[-1]
            if _hostname(o) not in self.hosts:
                return await self._deny(scope, receive, send, "origin_not_allowed",
                                        "Requête refusée : elle ne vient pas de l'interface de l'application")
        if scope["method"] not in SAFE_METHODS and origin == "null":
            return await self._deny(scope, receive, send, "origin_not_allowed", "Requête refusée : origine opaque")
        return await self.app(scope, receive, send)

    @staticmethod
    async def _deny(scope, receive, send, code: str, message: str) -> None:
        resp = JSONResponse({"error": {"code": code, "message": message, "details": {}}}, status_code=403)
        await resp(scope, receive, send)
