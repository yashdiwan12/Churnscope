"""POST /events: service API key, closed unless configured, bounded body, Phase 2 ingestion inside."""

import hmac
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import get_session
from app.main import create_app

KEY = "ingest-key-0123456789-0123456789-abcdef"


def event(i, **kw):
    return {
        "event_id": f"e{i}",
        "customer_id": "c1",
        "event_name": "session_start",
        "event_timestamp": "2026-01-05T00:00:00Z",
        **kw,
    }


@pytest.fixture
def make(monkeypatch, session):
    def _make(key=KEY) -> TestClient:
        monkeypatch.setenv("INGEST_API_KEY", key)
        get_settings.cache_clear()
        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        return TestClient(app, raise_server_exceptions=False)

    yield _make
    get_settings.cache_clear()


def test_unset_key_closes_the_route(make):
    r = make("").post("/events", json={"events": []}, headers={"X-API-Key": "anything"})
    assert r.status_code == 503
    assert r.json() == {"detail": "Ingestion is not configured"}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": ""}, {"X-API-Key": "wrong"}])
def test_missing_empty_or_wrong_key_is_401(make, headers):
    r = make().post("/events", json={"events": [event(1)]}, headers=headers)
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated"}


def test_user_bearer_token_is_not_an_ingest_key(make):
    r = make().post("/events", json={"events": []}, headers={"Authorization": "Bearer x"})
    assert r.status_code == 401


def test_valid_key_ingests_and_is_idempotent(make):
    client, h = make(), {"X-API-Key": KEY}
    first = client.post("/events", json={"events": [event(1), event(2)]}, headers=h)
    assert first.status_code == 200
    assert first.json()["inserted"] == 2 and first.json()["received"] == 2
    again = client.post("/events", json={"events": [event(1), event(2)]}, headers=h)
    assert again.json()["inserted"] == 0 and again.json()["duplicates"] == 2


def test_bad_rows_are_rejected_good_rows_stored(make):
    bad = event(2, event_name="nope")
    r = make().post("/events", json={"events": [event(1), bad]}, headers={"X-API-Key": KEY})
    body = r.json()
    assert r.status_code == 200 and body["inserted"] == 1
    assert [x["index"] for x in body["rejected"]] == [1]


def test_unknown_top_level_field_is_422(make):
    r = make().post("/events", json={"events": [], "x": 1}, headers={"X-API-Key": KEY})
    assert r.status_code == 422


def test_more_than_5000_events_is_422(make):
    body = {"events": [event(i) for i in range(5001)]}
    assert make().post("/events", json=body, headers={"X-API-Key": KEY}).status_code == 422


def test_body_over_5mb_is_413_before_parsing(make):
    big = b"x" * (5 * 1024 * 1024 + 1)
    r = make().post(
        "/events", content=big, headers={"X-API-Key": KEY, "Content-Type": "application/json"}
    )
    assert r.status_code == 413


def test_key_is_compared_in_constant_time(make, monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    make().post("/events", json={"events": []}, headers={"X-API-Key": "wrong"})
    assert calls


def test_key_never_appears_in_responses_or_logs(make, caplog):
    caplog.set_level(logging.DEBUG)
    client = make()
    for headers in ({"X-API-Key": KEY}, {"X-API-Key": KEY + "x"}):
        r = client.post("/events", json={"events": [event(9)]}, headers=headers)
        assert KEY not in r.text
    assert KEY not in caplog.text


def test_x_api_key_is_not_a_cors_allowed_header(make):
    r = make().options(
        "/events",
        headers={
            "Origin": "http://localhost:8501",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key",
        },
    )
    assert "x-api-key" not in r.headers.get("access-control-allow-headers", "").lower()
