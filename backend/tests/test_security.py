"""Token verification: every forged or malformed shape is rejected; no network involved."""

import base64
import hashlib
import hmac
import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from app.core.config import Settings
from app.core.security import AuthUnavailable, InvalidToken, TokenVerifier
from tests.auth_helpers import ISSUER, StaticJWKS, claims, make_ec_key, make_rsa_key, mint

EC = make_ec_key()
RSA = make_rsa_key()
OTHER = make_ec_key()


def verifier(secret: str = "") -> TokenVerifier:
    return TokenVerifier(
        issuer=ISSUER, jwks_client=StaticJWKS({"k1": EC, "r1": RSA}), hs256_secret=secret
    )


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def raw_hs256(secret: bytes, payload: dict) -> str:
    """Hand-built HS256 token (PyJWT refuses to sign with PEM bytes, an attacker would not)."""
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(payload).encode())
    sig = hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


def test_settings_allow_lists_are_lowercased_and_trimmed():
    s = Settings(
        _env_file=None,
        allowed_emails=" Alice@Example.com , ,bob@x.io",
        allowed_email_domains="Example.COM",
    )
    assert s.allowed_email_list == {"alice@example.com", "bob@x.io"}
    assert s.allowed_domain_list == {"example.com"}
    assert Settings(_env_file=None, allowed_emails="").allowed_email_list == set()


def test_valid_es256_and_rs256_tokens_verify():
    for key, alg, kid in [(EC, "ES256", "k1"), (RSA, "RS256", "r1")]:
        sub = str(uuid.uuid4())
        user = verifier().verify(mint(key, alg, kid=kid, sub=sub))
        assert user.id == uuid.UUID(sub)
        assert user.email == "alice@example.com"
        assert user.amr_methods == ("oauth",)
        assert user.provider == "google"


def test_valid_hs256_token_verifies_only_when_secret_configured():
    token = mint("test-secret-0123456789-0123456789-xx", "HS256")
    assert (
        verifier("test-secret-0123456789-0123456789-xx").verify(token).email == "alice@example.com"
    )
    with pytest.raises(InvalidToken):
        verifier("").verify(token)
    with pytest.raises(InvalidToken):
        verifier("another-secret-0123456789-0123456789").verify(token)


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 3600},
        {"aud": "anon"},
        {"iss": "https://evil.example/auth/v1"},
        {"role": "anon"},
        {"role": "service_role"},
        {"is_anonymous": True},
        {"sub": None},
        {"sub": "not-a-uuid"},
        {"exp": None},
        {"aud": None},
        {"iss": None},
    ],
    ids=lambda o: ",".join(f"{k}={v}" for k, v in o.items()),
)
def test_rejected_with_invalid_token(overrides):
    with pytest.raises(InvalidToken):
        verifier().verify(mint(EC, "ES256", **overrides))


def test_token_signed_by_another_key_is_rejected():
    with pytest.raises(InvalidToken):
        verifier().verify(mint(OTHER, "ES256", kid="k1"))


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c", "Bearer x"])
def test_malformed_tokens_are_rejected(token):
    with pytest.raises(InvalidToken):
        verifier("s" * 32).verify(token)


def test_alg_none_rejected():
    token = jwt.encode(claims(), None, algorithm="none")
    with pytest.raises(InvalidToken):
        verifier("s" * 32).verify(token)


def test_algorithm_confusion_rejected():
    pem = EC.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    token = raw_hs256(pem, claims())
    for secret in ("", "unrelated-secret-0123456789-0123456789"):
        with pytest.raises(InvalidToken):
            verifier(secret).verify(token)


def test_unknown_kid_is_invalid_token():
    with pytest.raises(InvalidToken):
        verifier().verify(mint(EC, "ES256", kid="rotated-away"))


def test_jwks_unreachable_is_auth_unavailable():
    v = TokenVerifier(issuer=ISSUER, jwks_client=StaticJWKS({"k1": EC}, down=True))
    with pytest.raises(AuthUnavailable):
        v.verify(mint(EC, "ES256"))


def test_nothing_configured_is_auth_unavailable():
    with pytest.raises(AuthUnavailable):
        TokenVerifier(issuer=ISSUER).verify(mint(EC, "ES256"))


def test_clock_leeway():
    assert verifier().verify(mint(EC, "ES256", exp=int(time.time()) - 5))
    with pytest.raises(InvalidToken):
        verifier().verify(mint(EC, "ES256", exp=int(time.time()) - 30))


def test_error_messages_never_contain_the_token():
    token = mint(EC, "ES256", aud="anon")
    with pytest.raises(InvalidToken) as exc:
        verifier().verify(token)
    assert token not in str(exc.value) and token.split(".")[1] not in str(exc.value)


@pytest.mark.parametrize("alg", [["RS256"], {"a": 1}, 5, None], ids=str)
def test_non_string_alg_header_is_invalid_token(alg):
    head = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    token = f"{head}.{b64(json.dumps(claims()).encode())}.{b64(b'sig')}"
    with pytest.raises(InvalidToken):
        verifier("s" * 32).verify(token)


@pytest.mark.parametrize("error", [json.JSONDecodeError("bad", "", 0), OSError("reset")])
def test_malformed_or_broken_jwks_response_is_auth_unavailable(error):
    v = TokenVerifier(issuer=ISSUER, jwks_client=StaticJWKS({"k1": EC}, error=error))
    with pytest.raises(AuthUnavailable):
        v.verify(mint(EC, "ES256"))
