"""POST /datasets/check: parses and summarises an upload, stores nothing, never echoes input."""

import io
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Customer, Dataset, Event
from app.db.session import get_session
from app.main import create_app
from app.services.uploads import MAX_FILE_BYTES, MAX_REASONS, MAX_REQUEST_BYTES
from tests.auth_helpers import act_as_allowed_user

HEAD = "customer_id,event_name,event_timestamp\n"
MULTIPART = {"Content-Type": "multipart/form-data; boundary=x"}


@pytest.fixture
def client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    act_as_allowed_user(app)
    return TestClient(app, raise_server_exceptions=False)


def post(client, data: bytes | str, name="events.csv"):
    if isinstance(data, str):
        data = data.encode()
    return client.post("/datasets/check", files={"file": (name, io.BytesIO(data), "text/csv")})


def counts(session):
    return tuple(
        session.scalar(select(func.count()).select_from(m)) for m in (Customer, Event, Dataset)
    )


def test_check_returns_summary_and_stores_nothing(client, session):
    before = counts(session)
    body = HEAD + (
        "u1,Session Start,2026-01-05T00:00:00Z\nu2,login,2026-01-06T00:00:00Z\nu2,login,garbage\n"
    )
    r = post(client, body)
    assert r.status_code == 200
    out = r.json()
    assert out["total_rows"] == 3
    assert out["valid_rows"] == 2
    assert out["customers"] == 2
    assert out["skipped_count"] == 1
    assert out["skipped"] == [{"row": 3, "code": "bad_timestamp"}]
    assert out["suggested_mapping"] == {"Session Start": "session_start", "login": None}
    assert {"name": "login", "count": 1} in out["event_names"]
    assert out["zoneless_timestamps"] is False
    assert "session_start" in out["our_event_names"]
    assert out["qualifying_events"] and out["funnel_steps"]
    assert counts(session) == before


def test_skip_list_is_capped_but_count_is_not(client):
    rows = "".join(",login,2026-01-05T00:00:00Z\n" for _ in range(MAX_REASONS + 5))
    out = post(client, HEAD + rows + "u1,login,2026-01-05T00:00:00Z\n").json()
    assert out["skipped_count"] == MAX_REASONS + 5
    assert len(out["skipped"]) == MAX_REASONS


def test_check_requires_sign_in(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    r = TestClient(app).post("/datasets/check", files={"file": ("a.csv", b"x", "text/csv")})
    assert r.status_code == 401


def test_check_411_without_content_length(client):
    def gen():
        yield b"x"

    r = client.post("/datasets/check", content=gen(), headers=MULTIPART)
    assert r.status_code == 411


def test_check_413_over_limit(client):
    r = client.post(
        "/datasets/check",
        content=b"x",
        headers={**MULTIPART, "Content-Length": str(MAX_REQUEST_BYTES + 1)},
    )
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "file_too_large"
    big = post(client, HEAD + "a" * (MAX_FILE_BYTES + 1))
    assert big.status_code == 413
    assert big.json()["detail"]["code"] == "file_too_large"


def test_check_422_never_echoes_input(client, caplog):
    caplog.set_level(logging.DEBUG)
    r = client.post("/datasets/check", data={"file": "SECRET-123"})
    assert r.status_code == 422
    assert "SECRET-123" not in r.text
    assert "SECRET-123" not in caplog.text
    detail = r.json()["detail"]
    items = detail if isinstance(detail, list) else [detail]
    for item in items:
        assert set(item) <= {"loc", "msg", "code", "message"}


def test_rejection_body_shape_and_no_echo(client):
    r = post(client, b"customer_id,event_name\nSECRET-123,x\n")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "missing_columns"
    assert "SECRET-123" not in r.text


def row_share(n_early: int, n_total: int) -> str:
    early = [f"u{i},login,2026-01-01T00:00:00Z\n" for i in range(n_early)]
    late = [f"u{i},login,2026-03-01T00:00:00Z\n" for i in range(n_early, n_total)]
    return HEAD + "".join(early + late)


def test_censor_warning_at_threshold(client):
    at = post(client, row_share(25, 100)).json()
    assert at["first_week_share"] == 0.25
    assert at["censor_warning"] is True
    below = post(client, row_share(24, 100)).json()
    assert below["first_week_share"] == 0.24
    assert below["censor_warning"] is False
