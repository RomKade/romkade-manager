"""Comptes ROMKADE (Supabase Auth) : vérification des jetons OAuth présentés par ChatGPT, Claude…

Supabase Auth est le serveur d'autorisation OAuth 2.1 (inscription automatique des clients, PKCE). Le serveur MCP
n'est que « serveur de ressources » : il vérifie la signature du jeton (ES256) avec les clés publiques du projet
(JWKS), son émetteur et sa date d'expiration.

Double authentification : un compte qui a une application d'authentification (facteur TOTP vérifié) n'est accepté
qu'avec un jeton de niveau aal2 (code saisi après le mot de passe). La page de connexion et le Manager demandent ce
code, mais un jeton obtenu directement auprès de Supabase avec le seul mot de passe (aal1) passerait sinon. Les
facteurs du compte sont lus avec la clé d'administration de Supabase (secret_key), gardés quelques minutes.

Le compte ROMKADE d'un utilisateur Supabase est « sb:<identifiant Supabase> » (table accounts de store.py).
"""

import logging
import threading
import time

import httpx
import jwt

log = logging.getLogger("romkade.auth")

ACCOUNT_PREFIX = "sb:"
FACTORS_TTL = 300  # secondes : facteurs d'un compte gardés en mémoire (activés ou retirés : pris en compte ensuite)


class SupabaseAuth:
    def __init__(self, supabase_url: str, publishable_key: str = "", secret_key: str = "",
                 transport: httpx.BaseTransport | None = None):
        self.url = supabase_url.rstrip("/")
        self.publishable_key = publishable_key
        self.secret_key = secret_key
        self.transport = transport
        self.issuer = f"{self.url}/auth/v1"
        self.jwks = jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600)
        self._factors: dict[str, tuple[float, bool]] = {}  # utilisateur -> (lu à, a un facteur TOTP vérifié)
        self._lock = threading.Lock()
        if not secret_key:
            log.warning("ROMKADE_SUPABASE_SECRET_KEY absente : double authentification non vérifiée par le serveur")

    @property
    def metadata_url(self) -> str:
        """Métadonnées du serveur d'autorisation (RFC 8414, chemin inséré après le domaine)."""
        return f"{self.url}/.well-known/oauth-authorization-server/auth/v1"

    def verify(self, token: str) -> dict | None:
        """Revendications d'un jeton d'accès valide émis par Supabase pour ce projet, sinon None."""
        try:
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["ES256", "RS256"], issuer=self.issuer,
                                options={"require": ["exp", "sub", "iss"], "verify_aud": False}, leeway=30)
        except jwt.PyJWTError as exc:
            log.info("jeton refusé : %s", exc)
            return None
        if claims.get("role") != "authenticated" or claims.get("exp", 0) < time.time() - 30:
            return None
        if not self.second_factor_ok(claims):
            log.info("jeton refusé : double authentification non faite (aal %s)", claims.get("aal"))
            return None
        return claims

    def second_factor_ok(self, claims: dict) -> bool:
        """Jeton aal2, ou compte sans application d'authentification."""
        if claims.get("aal") == "aal2":
            return True
        return not self.has_second_factor(str(claims["sub"]))

    def has_second_factor(self, user_id: str) -> bool:
        """Le compte a-t-il un facteur TOTP vérifié ? Supabase injoignable : dernière réponse connue, sinon non
        (la page de connexion et le Manager demandent toujours le code)."""
        if not self.secret_key:
            return False
        with self._lock:
            known = self._factors.get(user_id)
        if known and time.time() - known[0] < FACTORS_TTL:
            return known[1]
        try:
            with httpx.Client(timeout=8, transport=self.transport) as http:
                r = http.get(f"{self.issuer}/admin/users/{user_id}",
                             headers={"apikey": self.secret_key, "Authorization": f"Bearer {self.secret_key}"})
            r.raise_for_status()
            factors = r.json().get("factors") or []
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("facteurs du compte illisibles : %s", exc)
            return known[1] if known else False
        found = any(f.get("status") == "verified" and f.get("factor_type", "totp") == "totp" for f in factors)
        with self._lock:
            self._factors[user_id] = (time.time(), found)
        return found


def account_id(claims: dict) -> str:
    return ACCOUNT_PREFIX + str(claims["sub"])
