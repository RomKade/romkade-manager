"""Comptes ROMKADE (Supabase Auth) : vérification des jetons OAuth présentés par ChatGPT, Claude…

Supabase Auth est le serveur d'autorisation OAuth 2.1 (inscription automatique des clients, PKCE). Le serveur MCP
n'est que « serveur de ressources » : il vérifie la signature du jeton (ES256) avec les clés publiques du projet
(JWKS), son émetteur et sa date d'expiration. Aucun secret Supabase n'est nécessaire ici.

Le compte ROMKADE d'un utilisateur Supabase est « sb:<identifiant Supabase> » (table accounts de store.py).
"""

import logging
import time

import jwt

log = logging.getLogger("romkade.auth")

ACCOUNT_PREFIX = "sb:"


class SupabaseAuth:
    def __init__(self, supabase_url: str, publishable_key: str = ""):
        self.url = supabase_url.rstrip("/")
        self.publishable_key = publishable_key
        self.issuer = f"{self.url}/auth/v1"
        self.jwks = jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600)

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
        return claims


def account_id(claims: dict) -> str:
    return ACCOUNT_PREFIX + str(claims["sub"])
