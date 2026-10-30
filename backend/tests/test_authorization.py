"""Authentication + allow-list on the protected routes. No network; tokens are minted locally."""

import logging
import time

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import TokenVerifier, get_verifier
from app.db.session import get_session
from app.main import create_app
from tests.auth_helpers import ISSUER, StaticJWKS, make_ec_key, mint

KEY = make_ec_key()
OTHER = make_ec_key()
SECRET = "hs-secret-0123456789-0123456789-xx"

PROTECTED = [
    ("get", "/analytics/overview", None),
    ("get", "/analytics/funnel", None),
    ("get", "/analytics/retention", None),
    ("get", "/analytics/engagement", None),
    ("post", "/churn/predict", {"customer_ids": ["c1"]}),
    ("get", "/churn/at-risk", None),
]


@pytest.fixture
def build(monkeypatch):
    """App whose verifier trusts KEY, with the allow-list set through the environment."""

    def _build(emails="alice@example.com", domains="", down=False, session=None) -> TestClient:
        monkeypatch.setenv("ALLOWED_EMAILS", emails)
        monkeypatch.setenv("ALLOWED_EMAIL_DOMAINS", domains)
        get_settings.cache_clear()
        app = create_app()
        jwks = StaticJWKS({"k1": KEY}, down=down)
        app.dependency_overrides[get_verifier] = lambda: TokenVerifier(
            issuer=ISSUER, jwks_client=jwks, hs256_secret=SECRET
        )
        if session is not None:
            app.dependency_overrides[get_session] = lambda: session
        return TestClient(app, raise_server_exceptions=False)

    yield _build
    get_settings.cache_clear()


def call(client, method, path, body, token=None, header=None):
    headers = {}
    if header is not None:
        headers["Authorization"] = header
    elif token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.request(method, path, json=body, headers=headers)


@pytest.mark.parametrize("method,path,body", PROTECTED)
@pytest.mark.parametrize(
    "header", [None, "", "Bearer", "Bearer ", "Basic abc", "Bearer a b", "Bearer garbage"]
)
def test_missing_or_malformed_authorization_is_401(build, method, path, body, header):
    r = call(build(), method, path, body, header=header)
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated"}
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "token",
    [
        mint(KEY, "ES256", exp=int(time.time()) - 3600),
        mint(KEY, "ES256", aud="anon"),
        mint(KEY, "ES256", iss="https://evil.example/auth/v1"),
        mint(OTHER, "ES256"),
        mint(KEY, "ES256", role="anon"),
        mint(KEY, "ES256", is_anonymous=True),
    ],
    ids=["expired", "wrong-aud", "wrong-iss", "forged", "role-anon", "anonymous"],
)
def test_invalid_tokens_are_401(build, token):
    r = call(build(), "get", "/analytics/overview", None, token=token)
    assert r.status_code == 401


def test_valid_token_passes_and_scheme_is_case_insensitive(build, session):
    client = build(session=session)
    token = mint(KEY, "ES256")
    assert call(client, "get", "/analytics/overview", None, token=token).status_code == 200
    r = call(client, "get", "/analytics/overview", None, header=f"bearer {token}")
    assert r.status_code == 200


def test_valid_token_not_on_allow_list_is_403(build):
    r = call(build(), "get", "/analytics/overview", None, token=mint(KEY, "ES256", email="x@y.io"))
    assert r.status_code == 403
    assert r.json() == {"detail": "Not allowed"}


def test_empty_allow_list_allows_nobody(build):
    r = call(build(emails=""), "get", "/analytics/overview", None, token=mint(KEY, "ES256"))
    assert r.status_code == 403


@pytest.mark.parametrize("email", [None, ["alice@example.com"], 42, ""])
def test_missing_or_non_string_email_is_403(build, email):
    token = mint(KEY, "ES256", email=email)
    assert call(build(), "get", "/analytics/overview", None, token=token).status_code == 403


def test_email_case_and_whitespace_are_normalised(build, session):
    client = build(emails=" Alice@Example.com ", session=session)
    token = mint(KEY, "ES256", email="alice@EXAMPLE.com")
    assert call(client, "get", "/analytics/overview", None, token=token).status_code == 200


@pytest.mark.parametrize(
    "email,status",
    [
        ("bob@example.com", 200),
        ("bob@evil.example.com", 403),
        ("bob@notexample.com", 403),
        ("bob@example.com.evil.io", 403),
    ],
)
def test_domain_allow_list_is_exact(build, session, email, status):
    client = build(emails="", domains="example.com", session=session)
    token = mint(KEY, "ES256", email=email)
    assert call(client, "get", "/analytics/overview", None, token=token).status_code == status


@pytest.mark.parametrize(
    "overrides",
    [
        {"amr": [{"method": "password", "timestamp": 0}], "app_metadata": {"provider": "email"}},
        {"amr": None},
        {"app_metadata": {"provider": "github"}},
    ],
)
def test_sign_in_not_through_google_is_403(build, overrides):
    token = mint(KEY, "ES256", **overrides)
    assert call(build(), "get", "/analytics/overview", None, token=token).status_code == 403


def test_auth_backend_down_is_503_not_allow(build):
    r = call(build(down=True), "get", "/analytics/overview", None, token=mint(KEY, "ES256"))
    assert r.status_code == 503
    assert r.json() == {"detail": "Authentication unavailable"}


def test_health_stays_open(build):
    assert build().get("/health").status_code == 200


def test_responses_and_logs_do_not_contain_the_token(build, caplog):
    caplog.set_level(logging.DEBUG)
    token = mint(KEY, "ES256", aud="anon")
    r = call(build(), "get", "/analytics/overview", None, token=token)
    assert token not in r.text and token not in caplog.text
