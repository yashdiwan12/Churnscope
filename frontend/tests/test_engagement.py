"""The Engagement page with a fake API: metrics, n/a handling, adoption, states."""

import copy
import time
from datetime import date

from streamlit.testing.v1 import AppTest

from auth import Tokens
from tests.fake_api import BANNER, CONFIGURED, ENGAGEMENT_OK, install, run, texts


def engagement_script():
    import streamlit as st

    from api_client import ApiClient
    from views import engagement

    st.info("Demo data: synthetic events from a seeded generator, not real customers.")
    engagement.render(ApiClient("http://api.test", lambda: "AT"))


def engagement_app(monkeypatch, status=200, body=ENGAGEMENT_OK):
    for key, value in CONFIGURED.items():
        monkeypatch.setenv(key, value)
    requested = install(monkeypatch, {"/analytics/engagement": (status, body)})
    at = AppTest.from_function(engagement_script, default_timeout=30)
    at.session_state["tokens"] = Tokens("AT", "RT", time.time() + 3600)
    return at, requested


def test_engagement_renders_metrics_with_n_and_adoption(monkeypatch):
    at, requested = engagement_app(monkeypatch)
    shown = texts(run(at))
    assert BANNER in shown
    assert "Window: 1 Oct to 30 Oct 2026 (30 days)" in shown
    assert "Data through 30 Oct 2026" in shown
    assert "Active users: 120 (n=120)" in shown
    assert "Active days per user (mean): 4.3 (n=120)" in shown
    assert "Active days per user (median): 3.0 (n=120)" in shown
    assert "Events per active user: 36.0 (n=120)" in shown
    assert "Median hours between activities: n/a (n=120)" in shown
    assert "Feature adoption is the share of active users who used each feature" in shown
    assert "nan" not in shown.lower()
    assert "none" not in shown.lower()
    assert len(at.get("plotly_chart")) == 1
    assert "/analytics/engagement" in requested


def test_engagement_empty_state_when_no_active_users(monkeypatch):
    empty = copy.deepcopy(ENGAGEMENT_OK)
    empty.update(
        active_users=0,
        active_days_per_user_mean=None,
        active_days_per_user_median=None,
        events_per_active_user=None,
        feature_adoption={},
    )
    at, _ = engagement_app(monkeypatch, body=empty)
    shown = texts(run(at))
    assert "No events in this window" in shown
    assert "Window: 1 Oct to 30 Oct 2026 (30 days)" in shown
    assert len(at.get("plotly_chart")) == 0


def test_engagement_503_shows_retry(monkeypatch):
    at, _ = engagement_app(monkeypatch, status=503, body={"detail": "database cold start"})
    shown = texts(run(at))
    assert "The service is unavailable. Please try again shortly." in shown
    assert "Retry" in [b.label for b in at.get("button")]
    assert "database cold start" not in shown


def test_engagement_invalid_range_makes_no_call(monkeypatch):
    at, requested = engagement_app(monkeypatch)
    run(at)
    at.sidebar.checkbox[0].uncheck()
    run(at)
    requested.clear()
    at.sidebar.date_input[0].set_value(date(2026, 10, 30))
    at.sidebar.date_input[1].set_value(date(2026, 10, 1))
    shown = texts(run(at))
    assert "The start date must be on or before the end date." in shown
    assert "/analytics/engagement" not in requested


def test_engagement_date_range_reaches_the_request(monkeypatch):
    at, requested = engagement_app(monkeypatch)
    run(at)
    at.sidebar.checkbox[0].uncheck()
    run(at)
    requested.clear()
    requested.queries.clear()
    at.sidebar.date_input[0].set_value(date(2026, 10, 5))
    at.sidebar.date_input[1].set_value(date(2026, 10, 20))
    run(at)
    calls = [q for p, q in zip(requested, requested.queries) if p == "/analytics/engagement"]
    assert calls
    assert calls[-1]["start"].startswith("2026-10-05")
    assert calls[-1]["end"].startswith("2026-10-2")
