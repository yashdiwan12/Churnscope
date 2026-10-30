"""The Retention page with a fake API: slider, time basis, incomplete and low-n labelling."""

import copy
import time

from streamlit.testing.v1 import AppTest

from auth import Tokens
from tests.fake_api import BANNER, CONFIGURED, RETENTION_OK, _cell, install, run, texts


def retention_script():
    import streamlit as st

    from api_client import ApiClient
    from views import retention

    st.info("Demo data: synthetic events from a seeded generator, not real customers.")
    retention.render(ApiClient("http://api.test", lambda: "AT"))


def retention_app(monkeypatch, status=200, body=RETENTION_OK):
    for key, value in CONFIGURED.items():
        monkeypatch.setenv(key, value)
    requested = install(monkeypatch, {"/analytics/retention": (status, body)})
    at = AppTest.from_function(retention_script, default_timeout=30)
    at.session_state["tokens"] = Tokens("AT", "RT", time.time() + 3600)
    return at, requested


def with_cells(*cells):
    body = copy.deepcopy(RETENTION_OK)
    body["cells"] = list(cells)
    return body


def test_retention_renders_time_basis_chart_and_labels(monkeypatch):
    at, _ = retention_app(monkeypatch)
    shown = texts(run(at))
    assert BANNER in shown
    assert "Cohorts as of 30 Oct 2026" in shown
    assert "Data through 30 Oct 2026" in shown
    assert "low n" in shown
    assert "incomplete" in shown
    assert "50.0% n=40" in shown
    assert len(at.get("plotly_chart")) == 1


def test_retention_slider_and_no_date_filters(monkeypatch):
    at, _ = retention_app(monkeypatch)
    run(at)
    slider = at.sidebar.slider[0]
    assert (slider.min, slider.max, slider.value) == (1, 26, 8)
    assert len(at.sidebar.date_input) == 0
    assert len(at.sidebar.checkbox) == 0


def test_retention_periods_reach_the_request(monkeypatch):
    at, requested = retention_app(monkeypatch)
    run(at)
    calls = [q for p, q in zip(requested, requested.queries) if p == "/analytics/retention"]
    assert str(calls[-1]["periods"]) == "8"
    at.sidebar.slider[0].set_value(12)
    run(at)
    calls = [q for p, q in zip(requested, requested.queries) if p == "/analytics/retention"]
    assert str(calls[-1]["periods"]) == "12"


def test_retention_warns_when_any_cell_is_incomplete(monkeypatch):
    at, _ = retention_app(monkeypatch)
    run(at)
    assert len(at.warning) == 1


def test_retention_warns_when_all_cells_incomplete_and_single_cohort(monkeypatch):
    body = with_cells(_cell("2026-10-26", 1, 25, 10, complete=False))
    at, _ = retention_app(monkeypatch, body=body)
    run(at)
    assert len(at.warning) == 1


def test_retention_no_warning_when_all_complete(monkeypatch):
    at, _ = retention_app(monkeypatch, body=with_cells(_cell("2026-10-05", 1, 40, 20)))
    run(at)
    assert len(at.warning) == 0


def test_retention_none_rate_shows_not_enough_data_without_nan(monkeypatch):
    at, _ = retention_app(monkeypatch)
    shown = texts(run(at))
    assert "not enough data" in shown
    assert "nan" not in shown.lower()
    assert "none" not in shown.lower()


def test_retention_empty_cells_shows_empty_state(monkeypatch):
    at, _ = retention_app(monkeypatch, body=with_cells())
    shown = texts(run(at))
    assert "No cohorts to show yet" in shown
    assert len(at.get("plotly_chart")) == 0


def test_retention_503_shows_retry(monkeypatch):
    at, _ = retention_app(monkeypatch, status=503, body={"detail": "database cold start"})
    shown = texts(run(at))
    assert "The service is unavailable. Please try again shortly." in shown
    assert "Retry" in [b.label for b in at.get("button")]
