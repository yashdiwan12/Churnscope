"""GET /churn/at-risk: counts, ranking, histogram, paging, evaluation block and the cache."""

from typing import ClassVar

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import create_app
from app.ml.artifact import ModelBundle
from app.services import features, prediction
from app.services.ingestion import ingest_events
from tests.auth_helpers import act_as_allowed_user
from tests.test_churn_api import StubPipeline, make_client, stub_bundle

URL = "/churn/at-risk"


@pytest.fixture(autouse=True)
def _fresh_cache():
    # Event ids restart after each test's TRUNCATE, so a stale entry could otherwise be re-hit.
    prediction.clear_at_risk_cache()
    yield
    prediction.clear_at_risk_cache()


def ingest(session, rows, prefix="ev"):
    result = ingest_events(
        session,
        [
            {
                "event_id": f"{prefix}{i}",
                "customer_id": cid,
                "event_name": name,
                "event_timestamp": ts,
                "properties": {},
            }
            for i, (cid, name, ts) in enumerate(rows)
        ],
    )
    assert result.rejected == []


# Latest event is 2026-06-30 12:00, so the cutoff is 2026-06-30 00:00. Stub score = days / 28.
ROWS = [
    ("Z", "signup", "2026-04-01T00:00:00Z"),
    ("Z", "session_start", "2026-06-30T12:00:00Z"),  # after the cutoff; Z is not eligible
    ("A", "signup", "2026-05-01T00:00:00Z"),
    ("A", "session_start", "2026-06-29T00:00:00Z"),  # 1 day  -> 0.0357
    ("B", "signup", "2026-05-01T00:00:00Z"),
    ("B", "session_start", "2026-06-05T00:00:00Z"),  # 25 days -> 0.8929
    ("C", "signup", "2026-05-01T00:00:00Z"),
    ("C", "session_start", "2026-06-16T00:00:00Z"),  # 14 days -> 0.5 (exactly the threshold)
    ("D", "signup", "2026-05-01T00:00:00Z"),
    ("D", "session_start", "2026-06-16T00:00:00Z"),  # 14 days -> 0.5, ties with C
    ("E", "signup", "2026-05-01T00:00:00Z"),
    ("E", "session_start", "2026-06-23T00:00:00Z"),  # 7 days -> 0.25
    ("F", "signup", "2026-04-01T00:00:00Z"),
    ("F", "session_start", "2026-05-01T00:00:00Z"),  # outside the window: not eligible
]


@pytest.fixture
def client(session):
    ingest(session, ROWS)
    return make_client(session, stub_bundle())


def test_counts_ranks_and_ordering(client):
    r = client.get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["model_version"] == "test-v1"
    assert body["cutoff"].startswith("2026-06-30T00:00:00")
    assert body["data_through"].startswith("2026-06-30T12:00:00")
    assert (body["window_days"], body["horizon_days"], body["decision_threshold"]) == (28, 14, 0.5)
    assert "not calibrated" in body["caveat"]
    assert body["eligible_customers"] == 5
    assert body["at_risk_count"] == 3
    rows = body["rows"]
    assert [x["rank"] for x in rows] == [1, 2, 3, 4, 5]
    # C and D tie at 0.5 and keep distinct ranks, ordered by customer_id.
    assert [x["customer_id"] for x in rows] == ["B", "C", "D", "E", "A"]
    assert [x["risk_score"] for x in rows] == [0.8929, 0.5, 0.5, 0.25, 0.0357]
    assert [x["predicted_class"] for x in rows] == (["at_risk"] * 3 + ["not_at_risk"] * 2)


class ScriptedPipeline:
    """Score by whole days since last activity, so exact edge scores can be produced."""

    SCORES: ClassVar[dict[int, float]] = {1: 0.0, 3: 0.3, 5: 0.5, 7: 0.7, 10: 1.0}

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        days = np.round(x["days_since_last_activity"].to_numpy()).astype(int)
        s = np.array([self.SCORES[d] for d in days])
        return np.column_stack([1 - s, s])


def test_histogram_from_rounded_scores(session):
    rows = [("Z", "signup", "2026-04-01T00:00:00Z"), ("Z", "session_start", "2026-06-30T12:00:00Z")]
    for cid, days in {"H0": 1, "H3": 3, "H5": 5, "H7": 7, "H10": 10}.items():
        day = 30 - days
        rows += [
            (cid, "signup", "2026-05-01T00:00:00Z"),
            (cid, "session_start", f"2026-06-{day:02d}T00:00:00Z"),
        ]
    ingest(session, rows)
    bundle = ModelBundle(pipeline=ScriptedPipeline(), metadata=stub_bundle().metadata)
    body = make_client(session, bundle).get(URL).json()

    hist = body["score_histogram"]
    assert len(hist) == 10
    assert [(b["bin_start"], b["bin_end"]) for b in hist][:2] == [(0.0, 0.1), (0.1, 0.2)]
    assert hist[-1]["bin_end"] == 1.0
    counts = [b["count"] for b in hist]
    assert sum(counts) == body["eligible_customers"] == 5
    assert counts == [1, 0, 0, 1, 0, 1, 0, 1, 0, 1]  # 0.0, 0.3, 0.5, 0.7, 1.0
    # The threshold bin (0.5) and above hold exactly the at-risk customers, 0.5 included.
    assert sum(counts[5:]) == body["at_risk_count"] == 3
    by_id = {x["customer_id"]: x for x in body["rows"]}
    assert by_id["H5"]["predicted_class"] == "at_risk"


def test_paging_and_offset_beyond_end(client):
    page = client.get(URL, params={"limit": 2, "offset": 2}).json()
    assert [x["rank"] for x in page["rows"]] == [3, 4]
    assert [x["customer_id"] for x in page["rows"]] == ["D", "E"]
    beyond = client.get(URL, params={"offset": 99}).json()
    assert beyond["rows"] == []
    assert (beyond["eligible_customers"], beyond["at_risk_count"]) == (5, 3)


def test_evaluation_comes_from_artifact_metadata(session):
    ingest(session, ROWS)
    metrics = {
        "roc_auc": 0.88,
        "f1": 0.75,
        "precision": 0.7,
        "recall": 0.8,
        "threshold": 0.5,
        "test_churn_rate": 0.34,
        "n": 3494,
    }
    meta = {**stub_bundle().metadata, "test_metrics": metrics, "data": {"synthetic": True}}
    bundle = ModelBundle(pipeline=StubPipeline(), metadata=meta)
    ev = make_client(session, bundle).get(URL).json()["evaluation"]
    assert ev == {**metrics, "synthetic": True}


def test_evaluation_tolerates_missing_metadata(client):
    ev = client.get(URL).json()["evaluation"]
    assert ev == dict.fromkeys(
        [
            "roc_auc",
            "f1",
            "precision",
            "recall",
            "threshold",
            "test_churn_rate",
            "n",
            "synthetic",
        ]
    )


def test_empty_database(session):
    r = make_client(session, stub_bundle()).get(URL)
    assert r.status_code == 200
    body = r.json()
    assert body["cutoff"] is None and body["data_through"] is None
    assert body["eligible_customers"] == 0 and body["at_risk_count"] == 0
    assert len(body["score_histogram"]) == 10
    assert all(b["count"] == 0 for b in body["score_histogram"])
    assert body["rows"] == []


def test_cache_hit_and_invalidation(session, monkeypatch):
    ingest(session, ROWS)
    calls = []
    real = features.build_features

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(features, "build_features", spy)
    client = make_client(session, stub_bundle())

    assert client.get(URL).json()["eligible_customers"] == 5
    client.get(URL, params={"offset": 1})
    assert len(calls) == 1  # the second request is served from the cache

    ingest(session, [("A", "session_start", "2026-06-30T13:00:00Z")], prefix="new")
    client.get(URL)
    assert len(calls) == 2  # a new event invalidates the entry

    # A backdated event: a new customer, active inside the window, older than the current max.
    ingest(
        session,
        [
            ("N", "signup", "2026-05-01T00:00:00Z"),
            ("N", "session_start", "2026-06-20T00:00:00Z"),
        ],
        prefix="late",
    )
    body = client.get(URL).json()
    assert len(calls) == 3
    assert body["eligible_customers"] == 6
    assert "N" in {x["customer_id"] for x in body["rows"]}


def test_model_unavailable_is_503_even_when_db_broken():
    def broken_session():
        raise RuntimeError("DATABASE_URL is not configured")
        yield  # pragma: no cover

    app = create_app()
    act_as_allowed_user(app)
    app.dependency_overrides[get_session] = broken_session
    app.state.model_bundle = None
    r = TestClient(app, raise_server_exceptions=False).get(URL)
    assert r.status_code == 503
    assert r.json() == {"detail": "Churn model is unavailable"}


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 1_000_001}],
)
def test_bounds_are_422(client, params):
    assert client.get(URL, params=params).status_code == 422


# Risk order (rank): B1 (0.8929), C2 (0.5), D3 (0.5), E4 (0.25), A5 (0.0357).
@pytest.mark.parametrize(
    ("sort", "ids", "ranks"),
    [
        ("risk_desc", ["B", "C", "D", "E", "A"], [1, 2, 3, 4, 5]),
        ("risk_asc", ["A", "E", "C", "D", "B"], [5, 4, 2, 3, 1]),
        ("customer_asc", ["A", "B", "C", "D", "E"], [5, 1, 2, 3, 4]),
    ],
)
def test_sort_orders_rows_but_ranks_stay_by_risk(client, sort, ids, ranks):
    body = client.get(URL, params={"sort": sort}).json()
    assert body["sort"] == sort
    assert [x["customer_id"] for x in body["rows"]] == ids
    assert [x["rank"] for x in body["rows"]] == ranks


def test_paging_applies_to_the_sorted_order(client):
    page = client.get(URL, params={"sort": "risk_asc", "limit": 2, "offset": 2}).json()
    assert [x["customer_id"] for x in page["rows"]] == ["C", "D"]
    assert [x["rank"] for x in page["rows"]] == [2, 3]
    assert [x["risk_score"] for x in page["rows"]] == [0.5, 0.5]


def test_default_sort_is_risk_desc(client):
    default = client.get(URL).json()
    explicit = client.get(URL, params={"sort": "risk_desc"}).json()
    assert default["sort"] == "risk_desc"
    assert default == explicit


@pytest.mark.parametrize("sort", ["foo", "", "RISK_DESC", "risk_desc,risk_asc"])
def test_invalid_sort_is_422(client, sort):
    assert client.get(URL, params={"sort": sort}).status_code == 422


def test_sorts_share_one_scoring_run(session, monkeypatch):
    ingest(session, ROWS)
    calls = []
    real = features.build_features

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(features, "build_features", spy)
    client = make_client(session, stub_bundle())
    for sort in ("risk_desc", "risk_asc", "customer_asc"):
        assert client.get(URL, params={"sort": sort}).status_code == 200
    assert len(calls) == 1


def test_empty_database_echoes_sort(session):
    body = make_client(session, stub_bundle()).get(URL, params={"sort": "customer_asc"}).json()
    assert body["sort"] == "customer_asc"
    assert body["rows"] == []
