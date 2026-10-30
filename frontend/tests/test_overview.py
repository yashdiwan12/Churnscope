"""The Overview page with a fake API: labels, denominators, empty and error states, sidebar."""

import copy
from datetime import date

from tests.fake_api import BANNER, ME_OK, OVERVIEW_OK, run, signed_in_app, texts


def overview_app(monkeypatch, status=200, body=OVERVIEW_OK):
    routes = {"/me": (200, ME_OK), "/analytics/overview": (status, body)}
    return signed_in_app(monkeypatch, routes)


def test_overview_renders_labels_denominators_and_banner(monkeypatch):
    at, _ = overview_app(monkeypatch)
    shown = texts(run(at))
    assert BANNER in shown
    assert "Window: 1 Oct to 30 Oct 2026 (30 days)" in shown
    assert "Data through 30 Oct 2026" in shown
    metrics = {m.label: m.value for m in at.get("metric")}
    assert metrics["Active users"] == "120"
    assert metrics["New users"] == "30"
    assert metrics["Returning users"] == "90"
    assert metrics["Qualifying events"] == "4,321"
    assert "75.0% of active users (n=120)" in shown
    box = [e for e in at.expander if e.label == "What counts as activity"]
    assert len(box) == 1 and box[0].proto.expanded is False
    inside = " ".join(str(el.value) for el in box[0].get("caption"))
    assert "login, report_viewed" in inside
    assert "login, report_viewed" not in shown.replace(inside, "")
    assert len(at.get("plotly_chart")) == 1


def test_overview_empty_window_shows_empty_state(monkeypatch):
    empty = copy.deepcopy(OVERVIEW_OK)
    empty.update(
        active_users=0,
        new_users=0,
        returning_users=0,
        returning_user_rate=None,
        qualifying_events=0,
        daily_active_users=[],
    )
    at, _ = overview_app(monkeypatch, body=empty)
    shown = texts(run(at))
    assert "No events in this window" in shown
    assert "Window: 1 Oct to 30 Oct 2026 (30 days)" in shown
    assert len(at.get("plotly_chart")) == 0
    assert "Active users" not in shown


def test_overview_503_shows_retry_and_stale_note(monkeypatch):
    at, _ = overview_app(monkeypatch, status=503, body={"detail": "database cold start"})
    shown = texts(run(at))
    assert "The service is unavailable. Please try again shortly." in shown
    assert "Results may be up to 5 minutes old." in shown
    assert "Retry" in [b.label for b in at.get("button")]
    assert "database cold start" not in shown


def test_overview_other_4xx_shows_fixed_message_without_server_text(monkeypatch):
    at, _ = overview_app(monkeypatch, status=422, body={"detail": "start must precede end"})
    shown = texts(run(at))
    assert "Those settings are not valid. Change the filters and try again." in shown
    assert "start must precede end" not in shown
    assert "Active users" not in shown


def test_sidebar_start_after_end_shows_message_and_makes_no_overview_call(monkeypatch):
    at, requested = overview_app(monkeypatch)
    run(at)
    at.sidebar.checkbox[0].uncheck()
    run(at)  # the date inputs appear with a valid default range
    requested.clear()
    at.sidebar.date_input[0].set_value(date(2026, 10, 30))
    at.sidebar.date_input[1].set_value(date(2026, 10, 1))
    shown = texts(run(at))
    assert "The start date must be on or before the end date." in shown
    assert "/analytics/overview" not in requested
    assert requested == ["/me"]
    assert "Active users" not in shown
