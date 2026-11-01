"""Jetons ROMKADE (auth.py) : un compte avec application d'authentification n'est accepté qu'en aal2."""

import time
from types import SimpleNamespace

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from romkade_cloud.auth import SupabaseAuth

URL = "https://projet.supabase.co"
KEY = ec.generate_private_key(ec.SECP256R1())


def token(sub: str, aal: str) -> str:
    return jwt.encode({"sub": sub, "iss": f"{URL}/auth/v1", "exp": int(time.time()) + 600, "role": "authenticated",
                       "aal": aal}, KEY, algorithm="ES256")


def make(secret="sb_secret_test"):
    calls = []

    def supabase(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["apikey"] == "sb_secret_test"
        user = request.url.path.rsplit("/", 1)[-1]
        factors = {"avec-2fa": [{"factor_type": "totp", "status": "verified"}],
                   "en-cours": [{"factor_type": "totp", "status": "unverified"}]}.get(user, [])
        if user == "panne":
            return httpx.Response(500)
        return httpx.Response(200, json={"id": user, "factors": factors})

    auth = SupabaseAuth(URL, "pk", secret, transport=httpx.MockTransport(supabase))
    auth.jwks = SimpleNamespace(get_signing_key_from_jwt=lambda t: SimpleNamespace(key=KEY.public_key()))
    return auth, calls


def test_second_factor_required_when_the_account_has_one():
    auth, calls = make()
    assert auth.verify(token("sans-2fa", "aal1"))["sub"] == "sans-2fa"
    assert auth.verify(token("en-cours", "aal1"))  # facteur pas encore vérifié : pas exigé
    assert auth.verify(token("avec-2fa", "aal1")) is None  # mot de passe seul : refusé
    assert auth.verify(token("avec-2fa", "aal2"))["sub"] == "avec-2fa"
    n = len(calls)
    assert auth.verify(token("avec-2fa", "aal1")) is None and len(calls) == n  # gardé en mémoire
    assert auth.verify(token("panne", "aal1"))  # Supabase injoignable, rien de connu : accepté (code demandé par l'interface)


def test_without_admin_key_nothing_is_checked():
    auth, calls = make(secret="")
    assert auth.verify(token("avec-2fa", "aal1")) and calls == []
