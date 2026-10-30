"""A fake Churnscope API for AppTest runs: patches httpx.Client.request and answers by URL path.

AppTest runs the script in this process, so the patch reaches every request the app makes
(the Churnscope API and Supabase alike). A path missing from `routes` raises, which the run
records as an uncaught exception; `run` below fails the test on any such exception.
"""

import time
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from auth import Tokens

APP = str(Path(__file__).resolve().parent.parent / "app.py")
CONFIGURED = {"SUPABASE_URL": "https://p.supabase.co", "SUPABASE_ANON_KEY": "anon"}
BANNER = "Demo data: synthetic events from a seeded generator, not real customers."

ME_OK = {
    "id": "00000000-0000-0000-0000-000000000001",
    "email": "analyst@example.com",
    "created_at": "2026-10-01T00:00:00Z",
}

OVERVIEW_OK = {
    "window": {
        "start": "2026-10-01T00:00:00Z",
        "end": "2026-10-31T00:00:00Z",
        "data_through": "2026-10-30T18:00:00Z",
    },
    "active_users": 120,
    "new_users": 30,
    "returning_users": 90,
    "returning_user_rate": 0.75,
    "qualifying_events": 4321,
    "daily_active_users": [
        {"date": "2026-10-29", "active_users": 50},
        {"date": "2026-10-30", "active_users": 60},
    ],
    "qualifying_event_names": ["login", "report_viewed"],
}

FUNNEL_OK = {
    "window": OVERVIEW_OK["window"],
    "window_days": 14,
    "eligible_users": 200,
    "steps": [
        {
            "step": "signup",
            "users": 200,
            "conversion_from_previous": None,
            "conversion_from_start": 1.0,
        },
        {
            "step": "first_report",
            "users": 50,
            "conversion_from_previous": 0.25,
            "conversion_from_start": 0.25,
        },
        {
            "step": "export",
            "users": 5,
            "conversion_from_previous": 0.1,
            "conversion_from_start": 0.025,
        },
    ],
    "note": "Users signed up in the last 14 days are excluded.",
}

ENGAGEMENT_OK = {
    "window": OVERVIEW_OK["window"],
    "active_users": 120,
    "active_days_per_user_mean": 4.26,
    "active_days_per_user_median": 3.0,
    "events_per_active_user": 36.04,
    "median_hours_between_activities": None,
    "feature_adoption": {"export": 0.05, "login": 0.9, "report_viewed": 0.425},
}


class Requested(list):
    """The requested paths (a plain list of str); `.queries` holds each request's query dict."""

    def __init__(self):
        super().__init__()
        self.queries: list[dict[str, str]] = []


def install(monkeypatch, routes: dict[str, tuple[int, dict | None]]) -> Requested:
    requested = Requested()

    def fake_request(self, method, url, **kwargs):
        path = httpx.URL(str(url)).path
        requested.append(path)
        requested.queries.append(
            dict(httpx.URL(str(url)).params) | dict(kwargs.get("params") or {})
        )
        if path not in routes:
            raise AssertionError(f"unexpected request to {path}")
        status, body = routes[path]
        return httpx.Response(status, json=body, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    return requested


def signed_in_app(monkeypatch, routes: dict[str, tuple[int, dict | None]]):
    """A configured app whose session already holds valid tokens, plus the requested paths."""
    for key, value in CONFIGURED.items():
        monkeypatch.setenv(key, value)
    requested = install(monkeypatch, routes)
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["tokens"] = Tokens("AT", "RT", time.time() + 3600)
    return at, requested


def run(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def texts(at: AppTest) -> str:
    """Every visible text in the run (main area and sidebar), joined for substring checks."""
    parts: list[str] = []
    for kind in ("title", "caption", "markdown", "info", "success", "warning", "error"):
        parts += [str(el.value) for el in at.get(kind)]
    for metric in at.get("metric"):
        parts += [metric.label, str(metric.value)]
    parts += [button.label for button in at.get("button")]
    return "\n".join(parts)


def _cell(cohort, period, eligible, retained, complete=True, size=40):
    rate = None if eligible == 0 else retained / eligible
    return {
        "cohort": cohort,
        "period": period,
        "cohort_size": size,
        "eligible": eligible,
        "retained": retained,
        "retention": rate,
        "complete": complete,
    }


RETENTION_OK = {
    "as_of": "2026-10-30T12:00:00+00:00",
    "period_days": 7,
    "periods": 8,
    "cells": [
        _cell("2026-10-05", 0, 40, 40),
        _cell("2026-10-05", 1, 40, 20),
        _cell("2026-10-12", 0, 19, 19, size=19),
        _cell("2026-10-12", 1, 19, 5, complete=False, size=19),
        _cell("2026-10-19", 1, 0, 0, complete=False, size=30),
    ],
}
