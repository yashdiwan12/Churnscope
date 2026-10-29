"""Verify a Supabase-issued JWT. No HTTP of our own and no DB; the key source is injectable.

Fail closed: anything that is not a clean, fully checked token is `InvalidToken`; if we cannot
check at all (keys unreachable or auth not configured) it is `AuthUnavailable`, never "allow".
Messages are generic: tokens and claim payloads are never put into errors or logs.
"""

import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import get_settings

ASYMMETRIC_ALGS = {"ES256", "RS256"}
AUDIENCE = "authenticated"
LEEWAY_SECONDS = 10


class InvalidToken(Exception):
    """The token is missing, malformed, forged, expired or for another audience/issuer."""


class AuthUnavailable(Exception):
    """We cannot verify tokens right now (no key source, or the JWKS endpoint is unreachable)."""


@dataclass(frozen=True)
class AuthUser:
    id: uuid.UUID
    email: str | None
    amr_methods: tuple[str, ...]
    provider: str | None


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        jwks_client: PyJWKClient | Any | None = None,
        hs256_secret: str = "",
    ):
        self._issuer = issuer
        self._jwks = jwks_client
        self._secret = hs256_secret

    def verify(self, token: str) -> AuthUser:
        if self._jwks is None and not self._secret:
            raise AuthUnavailable("authentication is not configured")
        try:
            alg = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError:
            raise InvalidToken("invalid token") from None

        key: Any
        if alg in ASYMMETRIC_ALGS:
            if self._jwks is None:
                raise AuthUnavailable("no signing keys configured")
            try:
                key = self._jwks.get_signing_key_from_jwt(token).key
            except jwt.PyJWKClientConnectionError:
                raise AuthUnavailable("signing keys unreachable") from None
            except jwt.PyJWTError:
                raise InvalidToken("invalid token") from None
        elif alg == "HS256" and self._secret:
            key = self._secret  # a configured secret and nothing else; never a JWKS key
        else:  # includes "none" and HS256 without a configured secret
            raise InvalidToken("invalid token")

        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[alg],
                audience=AUDIENCE,
                issuer=self._issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError:
            raise InvalidToken("invalid token") from None
        return _user_from_claims(payload)


def _user_from_claims(payload: dict) -> AuthUser:
    if payload.get("role") != AUDIENCE or payload.get("is_anonymous") is True:
        raise InvalidToken("invalid token")
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except ValueError:
        raise InvalidToken("invalid token") from None
    email = payload.get("email")
    amr = payload.get("amr")
    methods = tuple(
        m["method"]
        for m in (amr if isinstance(amr, list) else [])
        if isinstance(m, dict) and isinstance(m.get("method"), str)
    )
    meta = payload.get("app_metadata")
    provider = meta.get("provider") if isinstance(meta, dict) else None
    return AuthUser(
        id=user_id,
        email=email if isinstance(email, str) else None,
        amr_methods=methods,
        provider=provider if isinstance(provider, str) else None,
    )


@lru_cache
def get_verifier() -> TokenVerifier:
    settings = get_settings()
    base = settings.supabase_url.rstrip("/")
    issuer = f"{base}/auth/v1"
    jwks = PyJWKClient(f"{issuer}/.well-known/jwks.json", timeout=5, lifespan=600) if base else None
    return TokenVerifier(issuer=issuer, jwks_client=jwks, hs256_secret=settings.supabase_jwt_secret)
