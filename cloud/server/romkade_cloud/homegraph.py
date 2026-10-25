"""Home Graph de Google (Google Home) : prévenir Google sans attendre « Hey Google, synchronise mes appareils ».

- request_sync : la liste des jeux a changé (favori ajouté, jeu joué) : Google redemande SYNC au serveur ;
- report_state : la console est allumée, éteinte, tel jeu tourne : Google le sait sans interroger (QUERY).

Accès par un compte de service du projet Google Cloud de l'intégration (API « HomeGraph » activée), dont la clé
JSON est passée encodée en base64 dans ROMKADE_GOOGLE_SERVICE_ACCOUNT_B64 (fichier secret de la droplet). Sans
elle, tout reste muet : Google se met à jour à la prochaine synchronisation demandée par l'utilisateur.
"""

import base64
import json
import logging
import time
import uuid

import httpx
import jwt

log = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/homegraph"
API = "https://homegraph.googleapis.com/v1/devices"


class HomeGraph:
    def __init__(self, service_account_b64: str = "", transport: httpx.AsyncBaseTransport | None = None):
        self.account = None
        if service_account_b64:
            try:
                self.account = json.loads(base64.b64decode(service_account_b64))
            except ValueError:
                log.warning("Home Graph : clé de compte de service illisible, désactivé")
        self.transport = transport
        self._token: tuple[str, float] | None = None

    @property
    def ready(self) -> bool:
        return bool(self.account)

    async def _access_token(self, http: httpx.AsyncClient) -> str:
        if self._token and self._token[1] > time.time() + 60:
            return self._token[0]
        now = int(time.time())
        uri = self.account.get("token_uri", "https://oauth2.googleapis.com/token")
        assertion = jwt.encode({"iss": self.account["client_email"], "scope": SCOPE, "aud": uri, "iat": now,
                                "exp": now + 3600}, self.account["private_key"], algorithm="RS256",
                               headers={"kid": self.account.get("private_key_id")})
        r = await http.post(uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                       "assertion": assertion})
        r.raise_for_status()
        body = r.json()
        self._token = (body["access_token"], time.time() + int(body.get("expires_in", 3600)))
        return self._token[0]

    async def _post(self, path: str, body: dict) -> bool:
        if not self.ready:
            return False
        try:
            async with httpx.AsyncClient(timeout=15, transport=self.transport) as http:
                token = await self._access_token(http)
                r = await http.post(f"{API}:{path}", json=body, headers={"Authorization": f"Bearer {token}"})
            if r.status_code >= 400:
                log.warning("Home Graph %s refusé (%s) : %s", path, r.status_code, r.text[:200])
                return False
            return True
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("Home Graph %s impossible : %s", path, exc)
            return False

    async def request_sync(self, agent_user_id: str) -> bool:
        return await self._post("requestSync", {"agentUserId": agent_user_id, "async": True})

    async def report_state(self, agent_user_id: str, states: dict[str, dict]) -> bool:
        return await self._post("reportStateAndNotification", {
            "requestId": str(uuid.uuid4()), "agentUserId": agent_user_id, "payload": {"devices": {"states": states}}})
