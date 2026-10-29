"""Test-only helpers: mint Supabase-shaped tokens locally so no test calls Supabase."""

import time
import uuid
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa

ISSUER = "https://test.supabase.co/auth/v1"


def make_ec_key():
    return ec.generate_private_key(ec.SECP256R1())


def make_rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def claims(**overrides) -> dict:
    """A valid payload; an override of None deletes the claim."""
    payload = {
        "iss": ISSUER,
        "aud": "authenticated",
        "role": "authenticated",
        "sub": str(uuid.uuid4()),
        "email": "alice@example.com",
        "exp": int(time.time()) + 3600,
        "amr": [{"method": "oauth", "timestamp": 0}],
        "app_metadata": {"provider": "google"},
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def mint(key, alg: str, *, kid: str = "k1", **overrides) -> str:
    """Sign a token with `key` (a private key, or the secret string for HS256)."""
    return jwt.encode(claims(**overrides), key, algorithm=alg, headers={"kid": kid})


class StaticJWKS:
    """Stands in for jwt.PyJWKClient: maps kid -> private key, never touches the network."""

    def __init__(self, keys: dict | None = None, down: bool = False):
        self._keys = {kid: k.public_key() for kid, k in (keys or {}).items()}
        self._down = down

    def get_signing_key_from_jwt(self, token: str):
        if self._down:
            raise jwt.PyJWKClientConnectionError("jwks unreachable")
        kid = jwt.get_unverified_header(token).get("kid")
        if kid not in self._keys:
            raise jwt.PyJWKClientError("Unable to find a signing key that matches")
        return SimpleNamespace(key=self._keys[kid])


def act_as_allowed_user(app) -> None:
    """For tests of other behaviour: skip token checks and act as an allow-listed user."""
    from app.core.authorization import current_user
    from app.core.security import AuthUser

    app.dependency_overrides[current_user] = lambda: AuthUser(
        id=uuid.uuid4(), email="alice@example.com", amr_methods=("oauth",), provider="google"
    )
