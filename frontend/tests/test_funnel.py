"""The Funnel page with a fake API: slider, labels, denominators, None conversions, states."""

import copy
import time
from datetime import date

from streamlit.testing.v1 import AppTest

from auth import Tokens
from tests.fake_api import BANNER, CONFIGURED, FUNNEL_OK, install, run, texts


def funnel_script():
    import streamlit as st

    from api_client import ApiClient
    from views import funnel

    st.info("Demo data: synthetic events from a seeded generator, not real customers.")
    funnel.render(ApiClient("http://api.test", lambda: "AT"))


def funnel_app(monkeypatch, status=200, body=FUNNEL_OK):
    for key, value in CONFIGURED.items():
        monkeypatch.setenv(key, value)
    requested = install(monkeypatch, {"/analytics/funnel": (status, body)})
    at = AppTest.from_function(funnel_script, default_timeout=30)
    at.session_state["tokens"] = Tokens("AT", "RT", time.time() + 3600)
    return at, requested


def open_funnel(at):
    return run(at)


def test_funnel_renders_steps_conversions_denominator_and_note(monkeypatch):
    at, _ = funnel_app(monkeypatch)
    shown = texts(open_funnel(at))
    assert BANNER in shown
    assert "Window: 1 Oct to 30 Oct 2026 (30 days)" in shown
    assert "Data through 30 Oct 2026" in shown
    assert "Eligible users: 200 (n=200)" in shown
    assert "signup: 200 users, 100.0% from start" in shown
    assert "first_report: 50 users, 25.0% from previous (n=200), 25.0% from start (n=200)" in shown
    assert "export: 5 users, 10.0% from previous (n=50), 2.5% from start (n=200)" in shown
    assert "Users signed up in the last 14 days are excluded." in shown
    assert "nan" not in shown.lower()
    assert "none" not in shown.lower()
    assert len(at.get("plotly_chart")) == 1


def test_funnel_slider_defaults_to_14_and_bounds(monkeypatch):
    at, _ = funnel_app(monkeypatch)
    slider = open_funnel(at).sidebar.slider[0]
    assert (slider.min, slider.max, slider.value) == (1, 90, 14)


def test_funnel_zero_first_step_shows_empty_state_without_nan(monkeypatch):
    empty = copy.deepcopy(FUNNEL_OK)
    empty["eligible_users"] = 0
    for step in empty["steps"]:
        step.update(users=0, conversion_from_previous=None, conversion_from_start=None)
    at, _ = funnel_app(monkeypatch, body=empty)
    shown = texts(open_funnel(at))
    assert "No eligible users in this window" in shown
    assert "nan" not in shown.lower()
    assert len(at.get("plotly_chart")) == 0


def test_funnel_503_shows_retry(monkeypatch):
    at, _ = funnel_app(monkeypatch, status=503, body={"detail": "database cold start"})
    shown = texts(open_funnel(at))
    assert "The service is unavailable. Please try again shortly." in shown
    assert "Retry" in [b.label for b in at.get("button")]
    assert "database cold start" not in shown


def test_funnel_invalid_range_makes_no_funnel_call(monkeypatch):
    at, requested = funnel_app(monkeypatch)
    open_funnel(at)
    at.sidebar.checkbox[0].uncheck()
    run(at)
    requested.clear()
    at.sidebar.date_input[0].set_value(date(2026, 10, 30))
    at.sidebar.date_input[1].set_value(date(2026, 10, 1))
    shown = texts(run(at))
    assert "The start date must be on or before the end date." in shown
    assert "/analytics/funnel" not in requested


def test_funnel_window_days_reaches_the_request(monkeypatch):
    at, requested = funnel_app(monkeypatch)
    run(at)
    calls = [q for p, q in zip(requested, requested.queries) if p == "/analytics/funnel"]
    assert str(calls[-1]["window_days"]) == "14"
    at.sidebar.slider[0].set_value(30)
    run(at)
    calls = [q for p, q in zip(requested, requested.queries) if p == "/analytics/funnel"]
    assert str(calls[-1]["window_days"]) == "30"
