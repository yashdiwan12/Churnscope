"""The whole flow on the hand-checked dataset: events in through the service key, analytics out."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_session
from app.main import create_app
from tests.auth_helpers import act_as_allowed_user
from tests.test_analytics_api import ROWS

KEY = "ingest-key-0123456789-0123456789-abcdef"
BODY = {
    "events": [
        {
            "event_id": f"ev{i}",
            "customer_id": cid,
            "event_name": name,
            "event_timestamp": f"{day}T00:00:00Z",
        }
        for i, (cid, name, day) in enumerate(ROWS)
    ]
}
OVERVIEW = "/analytics/overview?start=2026-01-07T00:00:00Z&end=2026-01-09T00:00:00Z"


@pytest.fixture
def clients(monkeypatch, session):
    monkeypatch.setenv("INGEST_API_KEY", KEY)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    service = TestClient(app, raise_server_exceptions=False)
    act_as_allowed_user(app)  # the user override only matters to the analytics routes
    yield service
    get_settings.cache_clear()


def read_numbers(client):
    overview = client.get(OVERVIEW)
    funnel = client.get("/analytics/funnel")
    retention = client.get("/analytics/retention", params={"periods": 4})
    assert overview.status_code == funnel.status_code == retention.status_code == 200
    steps = {s["step"]: s["users"] for s in funnel.json()["steps"]}
    cells = {(c["cohort"], c["period"]): c for c in retention.json()["cells"]}
    p0, p1 = cells[("2026-01-05", 0)], cells[("2026-01-05", 1)]
    return (
        overview.json()["active_users"],
        overview.json()["new_users"],
        funnel.json()["eligible_users"],
        [steps[n] for n in ("signup", "onboarding_complete", "report_created")],
        (p0["cohort_size"], p0["eligible"], p0["retained"], p1["retained"]),
    )


def test_events_in_analytics_out(clients):
    posted = clients.post("/events", json=BODY, headers={"X-API-Key": KEY})
    assert posted.status_code == 200
    expected = (3, 1, 4, [4, 3, 1], (3, 3, 3, 1))
    assert read_numbers(clients) == expected

    again = clients.post("/events", json=BODY, headers={"X-API-Key": KEY})
    assert again.status_code == 200
    assert read_numbers(clients) == expected  # the same body again changes nothing
