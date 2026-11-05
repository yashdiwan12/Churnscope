"""The sign-in gate, smoke-tested with Streamlit's AppTest and a fake API (no browser, no network)."""

import html
import re
import time

import pytest
from streamlit.testing.v1 import AppTest

from tests.fake_api import APP, ME_OK, OVERVIEW_OK, install, run, signed_in_app, texts

NOT_ALLOWED = "This account is not allowed to use Churnscope."
UNAVAILABLE = "The service is unavailable. Please try again shortly."


def sign_in_anchors(at):
    """The sign-in anchors on the page: (attributes, href with `&amp;` unescaped)."""
    found = []
    for md in at.markdown:
        for attrs in re.findall(r"<a\s([^>]*)>\s*Sign in with Google", md.value):
            href = re.search(r'href="([^"]*)"', attrs)
            found.append((attrs, html.unescape(href.group(1)) if href else ""))
    return found


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
    assert sign_in_anchors(at) == []


def test_signed_out_user_gets_a_google_link_with_pkce(monkeypatch):
    at, _ = signed_out(monkeypatch, SUPABASE_URL="https://p.supabase.co", SUPABASE_ANON_KEY="anon")
    anchors = sign_in_anchors(at)
    assert len(anchors) == 1
    attrs, link = anchors[0]
    assert 'target="_self"' in attrs  # same window: the OAuth redirect must return to this tab
    assert link.startswith("https://p.supabase.co/auth/v1/authorize?")
    assert "code_challenge=" in link and "flow%3D" in link


def test_reruns_reuse_one_pending_sign_in(monkeypatch):
    at, _ = signed_out(monkeypatch, SUPABASE_URL="https://p.supabase.co", SUPABASE_ANON_KEY="anon")
    first = sign_in_anchors(at)[0][1]
    second = sign_in_anchors(run(at))[0][1]
    assert first == second


def test_no_session_shows_sign_in_and_no_page_content(monkeypatch):
    at, requested = signed_out(
        monkeypatch, SUPABASE_URL="https://p.supabase.co", SUPABASE_ANON_KEY="anon"
    )
    assert len(sign_in_anchors(at)) == 1
    assert "Active users" not in texts(at)
    assert requested == []


def test_401_from_me_returns_to_sign_in(monkeypatch):
    at, requested = signed_in_app(monkeypatch, {"/me": (401, {"detail": "expired"})})
    run(at)
    assert "tokens" not in at.session_state
    assert len(sign_in_anchors(at)) == 1
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
    assert len(sign_in_anchors(at)) == 1
    assert "/auth/v1/logout" in requested


def test_blocked_account_can_sign_out(monkeypatch):
    routes = {"/me": (403, None), "/auth/v1/logout": (204, None)}
    at, _ = signed_in_app(monkeypatch, routes)
    run(at)
    at.button(key="sign_out").click()
    run(at)
    assert "tokens" not in at.session_state
    assert len(sign_in_anchors(at)) == 1


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


# --- idle sign-out: a session untouched for IDLE_TIMEOUT_MINUTES ends on the next interaction ---

LOGOUT = "/auth/v1/logout"


def idle_app(monkeypatch, idle_seconds, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    routes = {"/me": (200, ME_OK), "/analytics/overview": (200, OVERVIEW_OK), LOGOUT: (204, None)}
    at, requested = signed_in_app(monkeypatch, routes)
    at.session_state["last_seen"] = time.time() - idle_seconds
    return at, requested


def test_session_idle_past_the_limit_is_signed_out_with_a_notice(monkeypatch):
    at, requested = idle_app(monkeypatch, idle_seconds=31 * 60)
    run(at)
    assert "tokens" not in at.session_state
    assert len(sign_in_anchors(at)) == 1
    assert "signed out after 30 minutes of inactivity" in texts(at)
    assert "Active users" not in texts(at)
    assert "/me" not in requested  # the API is never asked once the session has expired
    assert LOGOUT in requested  # the refresh token is revoked on the server too


def test_session_within_the_limit_stays_signed_in_and_stamps_activity(monkeypatch):
    at, _ = idle_app(monkeypatch, idle_seconds=10 * 60)
    before = time.time()
    run(at)
    assert "tokens" in at.session_state
    assert "inactivity" not in texts(at)
    assert at.session_state["last_seen"] >= before


def test_idle_limit_is_configurable_and_zero_turns_it_off(monkeypatch):
    at, _ = idle_app(monkeypatch, idle_seconds=2 * 60, IDLE_TIMEOUT_MINUTES="1")
    run(at)
    assert "tokens" not in at.session_state
    assert "after 1 minute of inactivity" in texts(at)

    at, _ = idle_app(monkeypatch, idle_seconds=99 * 3600, IDLE_TIMEOUT_MINUTES="0")
    run(at)
    assert "tokens" in at.session_state


def test_a_bad_idle_setting_falls_back_to_the_default(monkeypatch):
    at, _ = idle_app(monkeypatch, idle_seconds=31 * 60, IDLE_TIMEOUT_MINUTES="soon")
    run(at)
    assert "tokens" not in at.session_state
