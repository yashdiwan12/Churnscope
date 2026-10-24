"""Endpoint tests on a hand-checked dataset (same example as test_metrics.py).

Latest event is 2026-01-30 (E's signup), so that is the "data through" / censoring point. By hand:
  funnel (default 14-day window): eligible A-D (E's window is not over) -> 4 / 3 / 1
  retention period 3: A's 4th week ends 02-02 > 01-30, so no one is eligible -> incomplete
"""

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import create_app
from app.services.ingestion import ingest_events

ROWS = [
    ("A", "signup", "2026-01-05"),
    ("A", "onboarding_complete", "2026-01-06"),
    ("A", "report_created", "2026-01-08"),
    ("A", "session_start", "2026-01-13"),
    ("A", "session_start", "2026-01-27"),
    ("B", "signup", "2026-01-06"),
    ("B", "onboarding_complete", "2026-01-07"),
    ("B", "session_start", "2026-01-07"),
    ("C", "signup", "2026-01-07"),
    ("C", "report_created", "2026-01-08"),
    ("C", "onboarding_complete", "2026-01-09"),
    ("D", "signup", "2026-01-12"),
    ("E", "signup", "2026-01-30"),
]


@pytest.fixture
def client(session):
    ingest_events(
        session,
        [
            {
                "event_id": f"ev{i}",
                "customer_id": cid,
                "event_name": name,
                "event_timestamp": f"{day}T00:00:00Z",
            }
            for i, (cid, name, day) in enumerate(ROWS)
        ],
    )
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


@pytest.fixture
def empty_client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_overview_hand_checked(client):
    r = client.get(
        "/analytics/overview",
        params={"start": "2026-01-07T00:00:00Z", "end": "2026-01-09T00:00:00Z"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["active_users"] == 3  # B (01-07), A and C (01-08)
    assert body["new_users"] == 1  # C signs up 01-07
    assert body["returning_users"] == 2  # A and B signed up before the window
    assert body["returning_user_rate"] == pytest.approx(2 / 3)
    assert body["qualifying_events"] == 3
    assert [d["active_users"] for d in body["daily_active_users"]] == [1, 2]
    assert body["window"]["data_through"].startswith("2026-01-30")
    assert "signup" not in body["qualifying_event_names"]


def test_funnel_hand_checked_with_default_window(client):
    r = client.get("/analytics/funnel")
    assert r.status_code == 200
    body = r.json()
    assert body["eligible_users"] == 4  # E is censored
    steps = {s["step"]: s for s in body["steps"]}
    assert [steps[k]["users"] for k in ("signup", "onboarding_complete", "report_created")] == [
        4,
        3,
        1,
    ]
    assert steps["onboarding_complete"]["conversion_from_previous"] == pytest.approx(3 / 4)
    assert steps["report_created"]["conversion_from_previous"] == pytest.approx(1 / 3)
    assert steps["report_created"]["conversion_from_start"] == pytest.approx(1 / 4)
    assert "excluded" in body["note"]


def test_funnel_only_counts_signups_in_range(client):
    r = client.get(
        "/analytics/funnel", params={"start": "2026-01-06T00:00:00Z", "end": "2026-01-08T00:00:00Z"}
    )
    body = r.json()  # signups B (01-06) and C (01-07)
    assert body["eligible_users"] == 2
    assert [s["users"] for s in body["steps"]] == [2, 2, 0]  # C's report precedes onboarding


def test_retention_marks_incomplete_cells(client):
    r = client.get("/analytics/retention", params={"periods": 4})
    assert r.status_code == 200
    cells = {(c["cohort"], c["period"]): c for c in r.json()["cells"]}
    p0 = cells[("2026-01-05", 0)]
    assert (p0["cohort_size"], p0["eligible"], p0["retained"]) == (3, 3, 3)
    assert p0["retention"] == pytest.approx(1.0) and p0["complete"] is True
    p1 = cells[("2026-01-05", 1)]
    assert p1["retained"] == 1 and p1["retention"] == pytest.approx(1 / 3)
    p3 = cells[("2026-01-05", 3)]
    assert p3["eligible"] == 0 and p3["retention"] is None and p3["complete"] is False
    assert cells[("2026-01-26", 0)]["retention"] is None  # E: week 0 not finished


def test_engagement_hand_checked(client):
    r = client.get(
        "/analytics/engagement",
        params={"start": "2026-01-07T00:00:00Z", "end": "2026-01-09T00:00:00Z"},
    )
    body = r.json()
    assert body["active_users"] == 3
    assert body["active_days_per_user_mean"] == pytest.approx(1.0)
    assert body["events_per_active_user"] == pytest.approx(1.0)
    assert body["median_hours_between_activities"] is None  # nobody has two events
    assert body["feature_adoption"] == {}


@pytest.mark.parametrize(
    "path,params",
    [
        ("/analytics/overview", {"start": "2026-01-07T00:00:00"}),  # naive timestamp
        ("/analytics/overview", {"start": "2026-02-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"}),
        ("/analytics/overview", {"start": "2024-01-01T00:00:00Z", "end": "2026-01-01T00:00:00Z"}),
        ("/analytics/funnel", {"window_days": 0}),
        ("/analytics/retention", {"periods": 0}),
        ("/analytics/engagement", {"start": "not-a-date"}),
    ],
)
def test_invalid_parameters_return_422(client, path, params):
    assert client.get(path, params=params).status_code == 422


def test_empty_database_returns_zeros_not_errors(empty_client):
    o = empty_client.get("/analytics/overview").json()
    assert o["active_users"] == 0 and o["returning_user_rate"] is None
    assert o["window"]["data_through"] is None
    f = empty_client.get("/analytics/funnel").json()
    assert f["eligible_users"] == 0 and all(s["users"] == 0 for s in f["steps"])
    assert empty_client.get("/analytics/retention").json()["cells"] == []
    assert empty_client.get("/analytics/engagement").json()["active_users"] == 0


def test_openapi_lists_analytics_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("overview", "funnel", "retention", "engagement"):
        assert f"/analytics/{p}" in paths
