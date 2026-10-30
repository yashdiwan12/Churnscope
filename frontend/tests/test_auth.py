"""PKCE helpers, the verifier store and the Supabase token calls. No network, no Streamlit."""

import re

import httpx
import pytest

from auth import (
    AuthError,
    Tokens,
    VerifierStore,
    authorize_url,
    challenge_for,
    exchange_code,
    needs_refresh,
    new_verifier,
    refresh,
    sign_out,
)

URL = "https://proj.supabase.co"


def test_verifier_is_url_safe_and_long_enough():
    v = new_verifier()
    assert 43 <= len(v) <= 128 and re.fullmatch(r"[A-Za-z0-9_-]+", v)
    assert new_verifier() != v


def test_challenge_matches_the_rfc7636_example():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_store_pop_is_single_use():
    store = VerifierStore(clock=Clock())
    store.put("f1", "v1")
    assert store.pop("f1") == "v1"
    assert store.pop("f1") is None
    assert store.pop("never-stored") is None


def test_store_entries_expire_after_ten_minutes():
    clock = Clock()
    store = VerifierStore(clock=clock)
    store.put("f1", "v1")
    clock.now = 601
    assert store.pop("f1") is None


def test_store_caps_entries_evicting_the_oldest():
    store = VerifierStore(clock=Clock(), cap=3)
    for i in range(5):
        store.put(f"f{i}", f"v{i}")
    assert store.pop("f0") is None and store.pop("f1") is None
    assert store.pop("f4") == "v4"


def test_authorize_url_carries_pkce_parameters():
    url = authorize_url(
        supabase_url=URL, redirect_to="http://localhost:8501?flow=abc", challenge="CH"
    )
    assert url.startswith(f"{URL}/auth/v1/authorize?")
    for part in ["provider=google", "code_challenge=CH", "code_challenge_method=s256"]:
        assert part in url
    assert "redirect_to=http%3A%2F%2Flocalhost%3A8501%3Fflow%3Dabc" in url


@pytest.mark.parametrize("expires_in,expected", [(59, True), (61, False)])
def test_needs_refresh_margin(expires_in, expected):
    assert needs_refresh(Tokens("a", "r", 1000 + expires_in), now=1000) is expected


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_exchange_code_posts_pkce_grant_and_parses_tokens():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(request.url), request.read()
        seen["apikey"] = request.headers["apikey"]
        return httpx.Response(
            200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}
        )

    tokens = exchange_code(
        make_client(handler), supabase_url=URL, anon_key="ANON", code="C", verifier="V", now=100
    )
    assert seen["url"] == f"{URL}/auth/v1/token?grant_type=pkce"
    assert b'"auth_code":"C"' in seen["body"].replace(b" ", b"")
    assert b'"code_verifier":"V"' in seen["body"].replace(b" ", b"")
    assert seen["apikey"] == "ANON"
    assert tokens == Tokens("AT", "RT", 3700)


def test_refresh_uses_the_refresh_grant():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{URL}/auth/v1/token?grant_type=refresh_token"
        return httpx.Response(
            200, json={"access_token": "A2", "refresh_token": "R2", "expires_in": 60}
        )

    t = refresh(make_client(handler), supabase_url=URL, anon_key="K", refresh_token="R", now=0)
    assert t == Tokens("A2", "R2", 60)


def test_failed_exchange_raises_without_echoing_the_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad", "secret": "LEAK-123"})

    with pytest.raises(AuthError) as exc:
        exchange_code(make_client(handler), supabase_url=URL, anon_key="K", code="C", verifier="V")
    assert "LEAK-123" not in str(exc.value) and "V" != str(exc.value)


def test_network_failure_is_an_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(AuthError):
        exchange_code(make_client(handler), supabase_url=URL, anon_key="K", code="C", verifier="V")


def test_sign_out_is_best_effort():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    sign_out(make_client(handler), supabase_url=URL, anon_key="K", access_token="AT")  # no raise
