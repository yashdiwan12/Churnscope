"""Churn on an upload: scoring after import, /churn/at-risk for uploads, the score endpoint."""

import io
import json
import logging
import os
import threading
import time
import uuid

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.core.authorization import current_user
from app.core.security import AuthUser
from app.db import repositories
from app.db.models import Dataset, UserProfile
from app.db.session import get_session
from app.main import create_app
from app.schemas.churn import UPLOAD_CAVEAT
from app.services import prediction, upload_scoring
from tests.test_churn_api import stub_bundle
from tests.test_upload_scoring import _big_file, _history, recency_file, report_file

URL = "/churn/at-risk"
NOT_FOUND = {"detail": "Dataset not found"}


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
    app.state.model_bundle = stub_bundle()
    return TestClient(app, raise_server_exceptions=False)


def to_csv(events: pd.DataFrame) -> str:
    out = events[["customer_id", "event_name"]].copy()
    out["event_timestamp"] = events["event_timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return out.to_csv(index=False)


def do_import(client, events: pd.DataFrame):
    names = set(events["event_name"])
    mapping = {n: n for n in names}
    return client.post(
        "/datasets",
        files={"file": ("mine.csv", io.BytesIO(to_csv(events).encode()), "text/csv")},
        data={"mapping": json.dumps(mapping)},
    )


def stored_scoring(session, dataset_id: int) -> dict | None:
    session.expire_all()
    return session.scalar(select(Dataset.scoring).where(Dataset.id == dataset_id))


def test_import_runs_scoring_and_at_risk_serves_upload(session, users):
    c = client_for(session, users[0])
    r = do_import(c, report_file(sharers=100, quiet=60))
    assert r.status_code == 201
    ds = r.json()["dataset"]
    assert ds["scoring_method"] == "logistic"
    assert ds["capabilities"]["churn"] is True
    scoring = stored_scoring(session, ds["id"])
    assert scoring["method"] == "logistic"
    assert scoring["backtest"]["test_rows"] >= 200

    body = c.get(URL, params={"dataset_id": ds["id"]}).json()
    assert body["dataset_id"] == ds["id"]
    assert body["method"] == "logistic"
    assert body["histogram_unit"] == "risk_score"
    assert body["backtest"] == scoring["backtest"]
    assert body["evaluation"] is None
    assert body["caveat"] == UPLOAD_CAVEAT
    assert body["decision_threshold"] == 0.5
    assert len(body["score_histogram"]) == 10
    assert sum(b["count"] for b in body["score_histogram"]) == body["eligible_customers"] > 0
    rows = body["rows"]
    assert [x["rank"] for x in rows] == list(range(1, len(rows) + 1))
    assert all(x["days_inactive"] is None for x in rows)
    scores = [x["risk_score"] for x in rows]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 1 for s in scores)
    at_risk = sum(1 for b in body["score_histogram"][5:] for _ in range(b["count"]))
    assert body["at_risk_count"] == at_risk


def test_rule_view_shows_days_not_probability(session, users):
    c = client_for(session, users[0])
    ds = do_import(c, recency_file(actives=120)).json()["dataset"]
    assert ds["scoring_method"] == "inactive_rule"  # both perfect: the rule wins ties

    body = c.get(URL, params={"dataset_id": ds["id"]}).json()
    assert body["method"] == "inactive_rule"
    assert body["histogram_unit"] == "days_inactive"
    assert body["decision_threshold"] == upload_scoring.RULE_DAYS
    assert body["evaluation"] is None
    assert body["backtest"]["rule"]["pr_auc"] >= 0.9
    hist = body["score_histogram"]
    assert [(b["bin_start"], b["bin_end"]) for b in hist] == [(0, 7), (7, 14), (14, 21), (21, 28)]
    assert sum(b["count"] for b in hist) == body["eligible_customers"]
    assert body["at_risk_count"] == sum(b["count"] for b in hist[1:])

    rows = c.get(URL, params={"dataset_id": ds["id"], "limit": 100}).json()["rows"]
    assert all(x["risk_score"] is None for x in rows)
    days = [x["days_inactive"] for x in rows]
    assert all(d is not None for d in days)
    # Most days inactive first, ties by customer id; rank is the position in that order.
    assert [(-d, x["customer_id"]) for d, x in zip(days, rows, strict=True)] == sorted(
        (-d, x["customer_id"]) for d, x in zip(days, rows, strict=True)
    )
    assert [x["rank"] for x in rows] == list(range(1, len(rows) + 1))
    for x in rows:
        assert x["predicted_class"] == ("at_risk" if x["days_inactive"] >= 7 else "not_at_risk")

    asc = c.get(URL, params={"dataset_id": ds["id"], "sort": "risk_asc"}).json()["rows"]
    asc_days = [x["days_inactive"] for x in asc]
    assert asc_days == sorted(asc_days)


def test_rule_unchecked_upload_is_served_by_the_rule(session, users):
    c = client_for(session, users[0])
    ds = do_import(c, _history(40)).json()["dataset"]
    assert ds["scoring_method"] == "rule_unchecked"
    body = c.get(URL, params={"dataset_id": ds["id"]}).json()
    assert body["method"] == "rule_unchecked"
    assert body["reason"] == "not_enough_history_for_test"
    assert body["backtest"] is None and body["evaluation"] is None
    assert body["histogram_unit"] == "days_inactive"
    assert [x["customer_id"] for x in body["rows"]] == ["a"]


def test_short_upload_is_unavailable_and_409(session, users):
    c = client_for(session, users[0])
    ds = do_import(c, _history(20)).json()["dataset"]
    assert ds["scoring_method"] == "unavailable"
    assert ds["capabilities"]["churn"] is False
    r = c.get(URL, params={"dataset_id": ds["id"]})
    assert r.status_code == 409


def test_upload_without_signup_cannot_show_churn(session, users):
    c = client_for(session, users[0])
    events = _history(40)
    events = events[events["event_name"] != "signup"]
    ds = do_import(c, events).json()["dataset"]
    assert ds["scoring_method"] == "unavailable"
    assert stored_scoring(session, ds["id"])["reason"] == "no_signup"
    assert ds["capabilities"]["churn"] is False
    assert ds["capabilities"]["retention"] is False


def test_scoring_failure_keeps_dataset_and_retry_works(session, users, monkeypatch, caplog):
    c = client_for(session, users[0])

    def boom(events, now):
        raise RuntimeError("secret-customer-id-in-message")

    real = upload_scoring.fit
    monkeypatch.setattr(upload_scoring, "fit", boom)
    # Alembic's fileConfig (run by the migration fixture) disables loggers that already exist.
    monkeypatch.setattr(logging.getLogger("churnscope.datasets"), "disabled", False)
    with caplog.at_level(logging.INFO):
        r = do_import(c, recency_file(actives=120))
    assert r.status_code == 201
    ds = r.json()["dataset"]
    assert ds["scoring_method"] == "failed"
    assert ds["capabilities"]["churn"] is False
    assert stored_scoring(session, ds["id"]) == {"method": "failed", "reason": "scoring_failed"}
    assert "secret-customer-id-in-message" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert c.get(URL, params={"dataset_id": ds["id"]}).status_code == 409
    assert [d["id"] for d in c.get("/datasets").json()] == [1, ds["id"]]

    monkeypatch.setattr(upload_scoring, "fit", real)
    retry = c.post(f"/datasets/{ds['id']}/score")
    assert retry.status_code == 200
    assert retry.json()["scoring_method"] == "inactive_rule"
    assert retry.json()["capabilities"]["churn"] is True
    assert c.get(URL, params={"dataset_id": ds["id"]}).json()["method"] == "inactive_rule"


def test_transient_db_error_on_score_is_503_and_not_stored(session, users, monkeypatch):
    c = client_for(session, users[0])
    ds = do_import(c, _history(40)).json()["dataset"]
    before = stored_scoring(session, ds["id"])

    def down(*args, **kwargs):
        raise OperationalError("x", {}, Exception())

    monkeypatch.setattr(repositories, "load_events", down)
    r = c.post(f"/datasets/{ds['id']}/score")
    assert r.status_code == 503
    assert r.json() == {"detail": "Database unavailable"}
    assert stored_scoring(session, ds["id"]) == before


def test_invalidated_connection_on_score_is_503_and_not_stored(session, users, monkeypatch):
    c = client_for(session, users[0])
    ds = do_import(c, _history(40)).json()["dataset"]
    before = stored_scoring(session, ds["id"])

    def lost(*args, **kwargs):
        raise DBAPIError("x", {}, Exception(), connection_invalidated=True)

    monkeypatch.setattr(repositories, "load_events", lost)
    r = c.post(f"/datasets/{ds['id']}/score")
    assert r.status_code == 503
    assert r.json() == {"detail": "Database unavailable"}
    assert stored_scoring(session, ds["id"]) == before


def test_replace_during_score_is_404(engine, session, users, monkeypatch):
    c = client_for(session, users[0])
    ds = do_import(c, _history(40)).json()["dataset"]
    real = upload_scoring.fit

    def fit_then_replaced(events, now):
        # Another request replaces (here: deletes) the upload while this one is fitting.
        with Session(engine) as other:
            other.execute(delete(Dataset).where(Dataset.id == ds["id"]))
            other.commit()
        return real(events, now)

    monkeypatch.setattr(upload_scoring, "fit", fit_then_replaced)
    r = c.post(f"/datasets/{ds['id']}/score")
    assert r.status_code == 404
    assert r.json() == NOT_FOUND


def test_rescore_changes_the_cache_key(session, users):
    c = client_for(session, users[0])
    ds = do_import(c, _history(40)).json()["dataset"]
    c.get(URL, params={"dataset_id": ds["id"]})
    first = [k for k in prediction._cache if k[0] == ds["id"]]
    assert len(first) == 1
    assert c.post(f"/datasets/{ds['id']}/score").status_code == 200
    assert not [k for k in prediction._cache if k[0] == ds["id"]]  # evicted on re-score
    c.get(URL, params={"dataset_id": ds["id"]})
    second = [k for k in prediction._cache if k[0] == ds["id"]]
    assert len(second) == 1 and second != first
    assert second[0][1] == stored_scoring(session, ds["id"])["fitted_at"]


def test_score_endpoint_404_for_foreign_or_demo(session, users):
    mine = do_import(client_for(session, users[0]), _history(40)).json()["dataset"]
    other = client_for(session, users[1])
    for dataset_id in (1, mine["id"], mine["id"] + 1000):
        r = other.post(f"/datasets/{dataset_id}/score")
        assert r.status_code == 404
        assert r.json() == NOT_FOUND
    assert client_for(session, users[0]).post("/datasets/1/score").status_code == 404
    assert other.post("/datasets/0/score").status_code == 422


def test_demo_response_keeps_the_shipped_model(session, users):
    body = client_for(session, users[0]).get(URL).json()
    assert body["dataset_id"] == 1
    assert body["method"] == "shipped_model"
    assert body["histogram_unit"] == "risk_score"
    assert body["backtest"] is None
    assert body["evaluation"] is not None


# ----------------------------------------------------------------------------- cache locking
def _slow(started: threading.Event, release: threading.Event, frame: pd.DataFrame):
    def compute():
        started.set()
        assert release.wait(10)
        return frame

    return compute


def test_slow_scoring_does_not_block_other_datasets():
    prediction._cache[(1, "v1", "t", 1)] = pd.DataFrame({"customer_id": ["d"]})
    started, release = threading.Event(), threading.Event()
    worker = threading.Thread(
        target=prediction._cached, args=((2, "fit", "t"), _slow(started, release, pd.DataFrame()))
    )
    worker.start()
    assert started.wait(10)
    hit = []
    reader = threading.Thread(
        target=lambda: hit.append(prediction._cached((1, "v1", "t", 1), lambda: None))
    )
    reader.start()
    reader.join(5)
    assert not reader.is_alive(), "a cache hit waited for another dataset's scoring run"
    assert hit[0]["customer_id"].tolist() == ["d"]
    release.set()
    worker.join(10)
    assert (2, "fit", "t") in prediction._cache


def test_same_key_is_scored_once():
    calls = []
    started, release = threading.Event(), threading.Event()

    def compute():
        calls.append(1)
        started.set()
        assert release.wait(10)
        return pd.DataFrame()

    threads = [threading.Thread(target=prediction._cached, args=((2, "f", "t"), compute))]
    threads[0].start()
    assert started.wait(10)
    threads.append(threading.Thread(target=prediction._cached, args=((2, "f", "t"), compute)))
    threads[1].start()
    release.set()
    for t in threads:
        t.join(10)
    assert len(calls) == 1
    assert not prediction._key_locks


def test_eviction_during_scoring_is_not_cached():
    started, release = threading.Event(), threading.Event()
    out = []
    worker = threading.Thread(
        target=lambda: out.append(
            prediction._cached((2, "f", "t"), _slow(started, release, pd.DataFrame({"x": [1]})))
        )
    )
    worker.start()
    assert started.wait(10)
    prediction.evict_dataset(2)  # e.g. the upload was deleted while it was being scored
    release.set()
    worker.join(10)
    assert out[0]["x"].tolist() == [1]  # the in-flight request still gets its answer
    assert (2, "f", "t") not in prediction._cache


def test_failed_scoring_releases_the_key_lock():
    def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        prediction._cached((2, "f", "t"), boom)
    assert not prediction._key_locks and not prediction._cache


@pytest.mark.skipif(
    not os.environ.get("CHURNSCOPE_TIMING"), reason="timing check; set CHURNSCOPE_TIMING=1"
)
def test_scoring_time_on_largest_upload(session, users, monkeypatch):
    events = _big_file()
    c = client_for(session, users[0])
    timed = []
    real = upload_scoring.fit

    def timed_fit(ev, now):
        start = time.perf_counter()
        out = real(ev, now)
        timed.append(time.perf_counter() - start)
        return out

    monkeypatch.setattr(upload_scoring, "fit", timed_fit)
    start = time.perf_counter()
    ds = do_import(c, events).json()["dataset"]
    total = time.perf_counter() - start
    start = time.perf_counter()
    assert c.post(f"/datasets/{ds['id']}/score").status_code == 200
    rescore = time.perf_counter() - start
    start = time.perf_counter()
    body = c.get(URL, params={"dataset_id": ds["id"]}).json()
    listing = time.perf_counter() - start
    print(
        f"\nimport+score {total:.2f} s (fit {timed[0]:.2f} s); POST score {rescore:.2f} s "
        f"(fit {timed[1]:.2f} s); first at-risk {listing:.2f} s; method {body['method']}"
    )
    assert rescore < 20


def test_upload_churn_does_not_need_the_synthetic_model(session, users):
    c = client_for(session, users[0])
    ds = do_import(c, report_file(sharers=100, quiet=60)).json()["dataset"]
    c.app.state.model_bundle = None
    assert c.get(URL, params={"dataset_id": ds["id"]}).status_code == 200
    assert c.get(URL).status_code == 503  # the demo still needs its model
    assert c.get(URL, params={"dataset_id": 1}).status_code == 503
