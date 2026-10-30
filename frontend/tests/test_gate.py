"""The sign-in gate, smoke-tested with Streamlit's AppTest and a fake API (no browser, no network)."""

import pytest
from streamlit.testing.v1 import AppTest

from tests.fake_api import APP, ME_OK, OVERVIEW_OK, install, run, signed_in_app, texts

NOT_ALLOWED = "This account is not allowed to use Churnscope."
UNAVAILABLE = "The service is unavailable. Please try again shortly."


def signed_out(monkeypatch, **env):
    for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    requested = install(monkeypatch, {})  # a signed-out visitor makes no request at all
    return run(AppTest.from_file(APP, default_timeout=30)), requested


def test_unconfigured_app_says_so_and_offers_no_sign_in(monkeypatch):
    at, _ = signed_out(monkeypatch)
    assert "not configured" in at.error[0].value
    assert len(at.get("link_button")) == 0


def test_signed_out_user_gets_a_google_link_with_pkce(monkeypatch):
    at, _ = signed_out(monkeypatch, SUPABASE_URL="https://p.supabase.co", SUPABASE_ANON_KEY="anon")
    link = at.get("link_button")[0].proto.url
    assert link.startswith("https://p.supabase.co/auth/v1/authorize?")
    assert "code_challenge=" in link and "flow%3D" in link


def test_reruns_reuse_one_pending_sign_in(monkeypatch):
    at, _ = signed_out(monkeypatch, SUPABASE_URL="https://p.supabase.co", SUPABASE_ANON_KEY="anon")
    first = at.get("link_button")[0].proto.url
    second = run(at).get("link_button")[0].proto.url
    assert first == second


def test_no_session_shows_sign_in_and_no_page_content(monkeypatch):
    at, requested = signed_out(
        monkeypatch, SUPABASE_URL="https://p.supabase.co", SUPABASE_ANON_KEY="anon"
    )
    assert len(at.get("link_button")) == 1
    assert "Active users" not in texts(at)
    assert requested == []


def test_401_from_me_returns_to_sign_in(monkeypatch):
    at, requested = signed_in_app(monkeypatch, {"/me": (401, {"detail": "expired"})})
    run(at)
    assert "tokens" not in at.session_state
    assert len(at.get("link_button")) == 1
    assert "Active users" not in texts(at)
    assert requested == ["/me"]


@pytest.mark.parametrize("status,message", [(403, NOT_ALLOWED), (503, UNAVAILABLE)])
def test_me_403_stops_with_no_page_content_even_with_cached_data(monkeypatch, status, message):
    routes = {"/me": (200, ME_OK), "/analytics/overview": (200, OVERVIEW_OK)}
    at, requested = signed_in_app(monkeypatch, routes)
    run(at)
    assert "Active users" in texts(at)  # the overview result is now in st.cache_data

    routes["/me"] = (status, {"detail": "server-side detail"})
    requested.clear()
    run(at)
    shown = texts(at)
    assert message in shown
    assert [b.label for b in at.get("button")] == ["Sign out"]
    assert "Active users" not in shown and "Window:" not in shown
    assert "server-side detail" not in shown
    assert requested == ["/me"]  # the gate ran again; no page asked for analytics


def test_gate_calls_me_on_every_rerun(monkeypatch):
    routes = {"/me": (200, ME_OK), "/analytics/overview": (200, OVERVIEW_OK)}
    at, requested = signed_in_app(monkeypatch, routes)
    run(at)
    run(at)
    assert requested.count("/me") == 2
    assert requested.count("/analytics/overview") == 1  # the second run used the cache


def test_signed_in_sidebar_shows_the_email_and_sign_out_clears_the_session(monkeypatch):
    routes = {
        "/me": (200, ME_OK),
        "/analytics/overview": (200, OVERVIEW_OK),
        "/auth/v1/logout": (204, None),
    }
    at, requested = signed_in_app(monkeypatch, routes)
    run(at)
    assert "Signed in as analyst@example.com" in texts(at)
    at.button(key="sign_out").click()
    run(at)
    assert "tokens" not in at.session_state
    assert len(at.get("link_button")) == 1
    assert "/auth/v1/logout" in requested


def test_blocked_account_can_sign_out(monkeypatch):
    routes = {"/me": (403, None), "/auth/v1/logout": (204, None)}
    at, _ = signed_in_app(monkeypatch, routes)
    run(at)
    at.button(key="sign_out").click()
    run(at)
    assert "tokens" not in at.session_state
    assert len(at.get("link_button")) == 1


def test_me_other_4xx_shows_the_unavailable_message_not_a_traceback(monkeypatch):
    routes = {"/me": (404, {"detail": "no such route"})}
    at, requested = signed_in_app(monkeypatch, routes)
    run(at)  # fails on any uncaught exception
    shown = texts(at)
    assert UNAVAILABLE in shown
    assert [b.label for b in at.get("button")] == ["Sign out"]
    assert "Active users" not in shown and "Window:" not in shown
    assert "404" not in shown and "no such route" not in shown
    assert requested == ["/me"]
