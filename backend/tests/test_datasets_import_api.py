"""POST /datasets (import and replace), GET /datasets and DELETE /datasets/{id}."""

import io
import json
import logging
import threading
import uuid

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.authorization import current_user
from app.core.config import get_settings
from app.core.security import AuthUser
from app.db import datasets as datasets_db
from app.db.models import Customer, Dataset, Event, UserProfile
from app.db.session import get_session
from app.main import create_app
from app.services import prediction, uploads
from app.services.ingestion import ingest_events

HEAD = "customer_id,event_name,event_timestamp\n"
MAP = {"login": "session_start", "join": "signup"}
NOT_FOUND = {"detail": "Dataset not found"}
INGEST_KEY = "ingest-key-0123456789-0123456789-abcdef"


@pytest.fixture(autouse=True)
def _fresh_cache():
    prediction.clear_at_risk_cache()
    yield
    prediction.clear_at_risk_cache()


@pytest.fixture
def users(session):
    ids = [uuid.uuid4(), uuid.uuid4()]
    session.add_all([UserProfile(id=i) for i in ids])
    session.commit()
    return ids


def client_for(session, uid: uuid.UUID) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[current_user] = lambda: AuthUser(
        id=uid, email="alice@example.com", amr_methods=("oauth",), provider="google"
    )
    return TestClient(app, raise_server_exceptions=False)


def make_csv(customers: int, prefix: str = "u") -> str:
    """Each customer: a signup and two logins."""
    rows = []
    for i in range(customers):
        rows += [
            f"{prefix}{i},join,2026-03-01T00:00:00Z",
            f"{prefix}{i},login,2026-03-02T00:00:00Z",
            f"{prefix}{i},login,2026-03-09T00:00:00Z",
        ]
    return HEAD + "\n".join(rows) + "\n"


def do_import(client, body: str, mapping=MAP, name="mine.csv", **flags):
    data = {"mapping": json.dumps(mapping)}
    data |= {k: ("true" if v else "false") for k, v in flags.items()}
    return client.post(
        "/datasets", files={"file": (name, io.BytesIO(body.encode()), "text/csv")}, data=data
    )


def rows_in(session, dataset_id: int) -> tuple[int, int]:
    session.expire_all()
    return tuple(
        session.scalar(select(func.count()).select_from(m).where(m.dataset_id == dataset_id))
        for m in (Customer, Event)
    )


def uploads_of(session, uid) -> list[Dataset]:
    session.expire_all()
    return list(session.scalars(select(Dataset).where(Dataset.owner_id == uid)))


def test_import_then_list_shows_demo_and_upload(session, users):
    c = client_for(session, users[0])
    r = do_import(c, make_csv(3), name="C:\\Users\\me\\Exports\\mine.csv")
    assert r.status_code == 201
    out = r.json()
    ds = out["dataset"]
    assert ds["kind"] == "upload"
    assert ds["name"] == ds["source_filename"] == "mine.csv"
    assert (ds["customer_count"], ds["event_count"]) == (3, 9)
    assert ds["signup_rule"] == "event"
    assert ds["data_through"].startswith("2026-03-09")
    assert ds["scoring_method"] == "unavailable"  # 8 days of history: too short to score
    assert ds["capabilities"]["retention"] is True
    assert ds["capabilities"]["churn"] is False
    assert out["imported_events"] == 9
    assert (out["duplicate_rows"], out["invalid_rows"], out["ignored_rows"]) == (0, 0, 0)
    assert rows_in(session, ds["id"]) == (3, 9)

    listed = c.get("/datasets")
    assert listed.status_code == 200
    assert [d["id"] for d in listed.json()] == [1, ds["id"]]
    demo = listed.json()[0]
    assert demo["kind"] == "demo" and demo["capabilities"]["churn"] is True
    # The other user sees only the demo.
    assert [d["id"] for d in client_for(session, users[1]).get("/datasets").json()] == [1]


def test_filename_defaults_and_is_cut(session, users):
    c = client_for(session, users[0])
    long = "a" * 150 + ".csv"
    assert do_import(c, make_csv(1), name=long).json()["dataset"]["name"] == long[:100]


def test_reimport_same_file_gives_identical_counts(session, users):
    c = client_for(session, users[0])
    body = make_csv(10) + "u0,login,2026-03-02T00:00:00Z\nu1,login,garbage\n"
    first, second = do_import(c, body).json(), do_import(c, body).json()
    keys = ("imported_events", "duplicate_rows", "invalid_rows", "ignored_rows", "skipped")
    assert {k: first[k] for k in keys} == {k: second[k] for k in keys}
    assert first["duplicate_rows"] == 1 and first["invalid_rows"] == 1
    assert first["skipped"] == [{"row": 32, "code": "bad_timestamp"}]
    assert first["dataset"]["event_count"] == second["dataset"]["event_count"] == 30
    assert second["dataset"]["id"] != first["dataset"]["id"]


def test_replace_keeps_one_upload_and_old_rows_gone(session, users):
    c = client_for(session, users[0])
    old = do_import(c, make_csv(5)).json()["dataset"]["id"]
    new = do_import(c, make_csv(2, prefix="v")).json()["dataset"]["id"]
    assert [d.id for d in uploads_of(session, users[0])] == [new]
    assert rows_in(session, old) == (0, 0)
    assert rows_in(session, new) == (2, 6)


def test_failed_import_keeps_old_upload(session, users, monkeypatch):
    c = client_for(session, users[0])
    old = do_import(c, make_csv(5)).json()["dataset"]
    deleted = []
    real_delete = datasets_db._delete_own_upload

    def delete_then_record(s, uid):
        ids = real_delete(s, uid)
        deleted.append(ids)
        return ids

    def boom(s, rows):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(datasets_db, "_delete_own_upload", delete_then_record)
    monkeypatch.setattr(datasets_db, "_insert_events", boom)
    r = do_import(c, make_csv(2, prefix="v"))
    assert r.status_code in (500, 503)
    assert deleted == [[old["id"]]]  # the delete ran inside the failed transaction
    assert [d.id for d in uploads_of(session, users[0])] == [old["id"]]
    assert rows_in(session, old["id"]) == (5, 15)


def test_database_error_on_import_never_logs_file_values(session, users, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    def integrity(s, rows):
        raise IntegrityError("INSERT ...", {"customer_id": rows[0]["event_id"]}, Exception("x"))

    monkeypatch.setattr(datasets_db, "_insert_events", integrity)
    body = (
        "customer_id,event_name,event_timestamp,event_id\nu1,login,2026-03-02T00:00:00Z,SECRET-9\n"
    )
    r = do_import(client_for(session, users[0]), body, mapping={"login": "session_start"})
    assert r.status_code == 500
    assert r.json() == {"detail": "Import failed"}
    assert "SECRET-9" not in r.text and "SECRET-9" not in caplog.text
    assert uploads_of(session, users[0]) == []


def test_concurrent_imports_one_user_leave_one_complete_upload(engine, session, users):
    first = uploads.prepare(
        uploads.parse_csv(make_csv(400).encode(), pd.Timestamp.now("UTC")), MAP, False, False
    )
    second = uploads.prepare(
        uploads.parse_csv(make_csv(300, "v").encode(), pd.Timestamp.now("UTC")), MAP, False, False
    )
    barrier = threading.Barrier(2, timeout=10)
    errors: list[BaseException] = []

    def run(prepared):
        try:
            with Session(engine) as s:
                barrier.wait()
                datasets_db.replace_upload(s, users[0], "x.csv", prepared)
        except Exception as exc:  # noqa: BLE001 - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(p,)) for p in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads)
    assert errors == []
    mine = uploads_of(session, users[0])
    assert len(mine) == 1
    assert mine[0].event_count in (1200, 900)
    assert rows_in(session, mine[0].id) == (mine[0].customer_count, mine[0].event_count)
    assert session.scalar(select(func.count()).select_from(Event)) == mine[0].event_count


def test_global_cap_returns_409(session, users, monkeypatch):
    monkeypatch.setattr(uploads, "GLOBAL_UPLOADED_EVENTS_CAP", 15)
    a, b = client_for(session, users[0]), client_for(session, users[1])
    assert do_import(a, make_csv(5)).status_code == 201  # 15 events: exactly the cap
    r = do_import(b, make_csv(1, "v"))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "storage_full"
    assert uploads_of(session, users[1]) == []
    again = do_import(a, make_csv(5, "w"))
    assert again.status_code == 201  # A's own old rows are not counted against the cap


def test_delete_rules(session, users):
    a, b = client_for(session, users[0]), client_for(session, users[1])
    mine = do_import(a, make_csv(3)).json()["dataset"]["id"]
    theirs = do_import(b, make_csv(2, "v")).json()["dataset"]["id"]
    assert a.delete("/datasets/1").status_code == 404
    assert a.delete("/datasets/1").json() == NOT_FOUND
    assert a.delete(f"/datasets/{theirs}").status_code == 404
    assert a.delete("/datasets/999999").status_code == 404
    assert a.delete(f"/datasets/{2**63}").status_code == 422
    assert a.delete("/datasets/0").status_code == 422
    r = a.delete(f"/datasets/{mine}")
    assert r.status_code == 204 and r.content == b""
    assert rows_in(session, mine) == (0, 0)
    assert rows_in(session, theirs) == (2, 6)
    assert a.delete(f"/datasets/{mine}").status_code == 404


def test_delete_and_import_evict_churn_cache(session, users):
    c = client_for(session, users[0])
    first = do_import(c, make_csv(2)).json()["dataset"]["id"]
    stamp = pd.Timestamp("2026-03-10", tz="UTC")
    prediction._cache[(first, "v1", stamp)] = pd.DataFrame()
    prediction._cache[(1, "v1", stamp, 7)] = pd.DataFrame()
    second = do_import(c, make_csv(2, "v")).json()["dataset"]["id"]
    assert [k[0] for k in prediction._cache] == [1]  # the replaced upload's entry is gone
    prediction._cache[(second, "v1", stamp)] = pd.DataFrame()
    assert c.delete(f"/datasets/{second}").status_code == 204
    assert [k[0] for k in prediction._cache] == [1]


def test_post_events_cannot_touch_uploads(session, users, monkeypatch):
    c = client_for(session, users[0])
    mine = do_import(c, make_csv(1)).json()["dataset"]["id"]  # customer u0
    monkeypatch.setenv("INGEST_API_KEY", INGEST_KEY)
    get_settings.cache_clear()
    try:
        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        r = TestClient(app).post(
            "/events",
            json={
                "events": [
                    {
                        "event_id": "e1",
                        "customer_id": "u0",
                        "event_name": "session_start",
                        "event_timestamp": "2026-03-03T00:00:00Z",
                    }
                ]
            },
            headers={"X-API-Key": INGEST_KEY},
        )
    finally:
        get_settings.cache_clear()
    assert r.status_code == 200 and r.json()["inserted"] == 1
    assert rows_in(session, 1) == (1, 1)
    assert rows_in(session, mine) == (1, 3)


def hand_checked_events() -> list[dict]:
    """6 customers x (signup + 4 session_start) = 30 rows, 2026-03-01 .. 2026-03-20."""
    out = []
    for k in range(1, 7):
        stamps = [
            ("signup", f"2026-03-{k:02d}T00:00:00Z"),
            ("session_start", f"2026-03-{k:02d}T01:00:00Z"),
            ("session_start", f"2026-03-{k + 1:02d}T10:00:00Z"),
            ("session_start", f"2026-03-{k + 7:02d}T10:00:00Z"),
            ("session_start", f"2026-03-{k + 14:02d}T10:00:00Z"),
        ]
        out += [
            {"event_id": f"c{k}-{j}", "customer_id": f"c{k}", "event_name": n, "event_timestamp": t}
            for j, (n, t) in enumerate(stamps)
        ]
    return out


def test_metrics_on_upload_match_demo_load(session, users):
    events = hand_checked_events()
    assert len(events) == 30
    body = "customer_id,event_name,event_timestamp,event_id\n" + "".join(
        f"{e['customer_id']},{e['event_name']},{e['event_timestamp']},{e['event_id']}\n"
        for e in events
    )
    c = client_for(session, users[0])
    mine = do_import(c, body, mapping={"signup": "signup", "session_start": "session_start"})
    assert mine.status_code == 201
    upload_id = mine.json()["dataset"]["id"]
    assert rows_in(session, 1) == (0, 0)  # the demo dataset starts empty in tests
    assert ingest_events(session, events).inserted == 30

    for path in ("/analytics/overview", "/analytics/retention"):
        demo = c.get(path, params={"dataset_id": 1})
        up = c.get(path, params={"dataset_id": upload_id})
        assert demo.status_code == up.status_code == 200
        assert demo.json() == up.json()
    overview = c.get("/analytics/overview", params={"dataset_id": upload_id}).json()
    assert (overview["new_users"], overview["active_users"]) == (6, 6)
    assert overview["qualifying_events"] == 24


def test_import_rejections_use_codes_and_never_echo(session, users):
    c = client_for(session, users[0])
    body = make_csv(1).replace("u0", "SECRET-123")
    cases = [
        ({"mapping": "not json"}, "bad_mapping"),
        ({"mapping": json.dumps(["login"])}, "bad_mapping"),
        ({"mapping": json.dumps({"login": "SECRET-123"})}, "bad_mapping"),
        ({}, "bad_mapping"),
        ({"mapping": json.dumps(MAP), "derive_signup": "yes"}, "bad_form"),
    ]
    for data, code in cases:
        r = c.post(
            "/datasets",
            files={"file": ("a.csv", io.BytesIO(body.encode()), "text/csv")},
            data=data,
        )
        assert r.status_code == 422, data
        assert r.json()["detail"]["code"] == code
        assert "SECRET-123" not in r.text
    assert uploads_of(session, users[0]) == []
