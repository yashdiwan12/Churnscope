"""POST /churn/predict: hand-checked scoring, eligibility, errors, and train/serve parity."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import create_app
from app.ml import train
from app.ml.artifact import ModelBundle
from app.services import features
from app.services.ingestion import ingest_events
from tests.auth_helpers import act_as_allowed_user

_spec = importlib.util.spec_from_file_location(
    "generate_events", Path(__file__).parents[1] / "scripts" / "generate_events.py"
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


class StubPipeline:
    """Score = days_since_last_activity / 28, so expected values are easy to check by hand."""

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        s = np.clip(x["days_since_last_activity"].to_numpy() / 28, 0, 1)
        return np.column_stack([1 - s, s])


def stub_bundle() -> ModelBundle:
    meta = {
        "model_version": "test-v1",
        "decision_threshold": 0.5,
        "feature_columns": features.FEATURE_COLUMNS,
    }
    return ModelBundle(pipeline=StubPipeline(), metadata=meta)


def make_client(session, bundle: ModelBundle | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.state.model_bundle = bundle
    act_as_allowed_user(app)
    return TestClient(app)


def ingest(session, rows):
    result = ingest_events(
        session,
        [
            {
                "event_id": f"ev{i}",
                "customer_id": cid,
                "event_name": name,
                "event_timestamp": ts,
                "properties": {},
            }
            for i, (cid, name, ts) in enumerate(rows)
        ],
    )
    assert result.rejected == []


# Latest event 2026-06-30 12:00 -> default cutoff is the last full midnight, 2026-06-30 00:00;
# window [06-02, 06-30). The partial day 06-30 is not used for features.
ROWS = [
    ("A", "signup", "2026-05-01T00:00:00Z"),
    ("A", "session_start", "2026-06-29T12:00:00Z"),  # 0.5 days before the cutoff
    ("A", "session_start", "2026-06-30T12:00:00Z"),  # partial last day: after the cutoff
    ("B", "signup", "2026-05-01T00:00:00Z"),
    ("B", "session_start", "2026-06-05T00:00:00Z"),  # 25 days before the cutoff
    ("C", "signup", "2026-04-01T00:00:00Z"),
    ("C", "session_start", "2026-05-01T00:00:00Z"),  # outside the 28-day window
]


@pytest.fixture
def client(session):
    ingest(session, ROWS)
    return make_client(session, stub_bundle())


def test_scores_hand_checked_and_preserves_request_order(client):
    r = client.post("/churn/predict", json={"customer_ids": ["B", "A", "C", "ghost", "A"]})
    assert r.status_code == 200
    body = r.json()
    assert body["model_version"] == "test-v1"
    assert body["cutoff"].startswith("2026-06-30T00:00:00")
    assert (body["window_days"], body["horizon_days"], body["decision_threshold"]) == (28, 14, 0.5)
    assert "not calibrated" in body["caveat"]

    p = {x["customer_id"]: x for x in body["predictions"]}
    assert [x["customer_id"] for x in body["predictions"]] == ["B", "A", "C", "ghost"]  # deduped
    assert p["B"]["risk_score"] == pytest.approx(25 / 28, abs=1e-4)
    assert p["B"]["predicted_class"] == "at_risk"
    assert p["A"]["risk_score"] == pytest.approx(0.5 / 28, abs=1e-4)
    assert p["A"]["predicted_class"] == "not_at_risk"
    assert p["C"]["status"] == "not_eligible" and p["C"]["risk_score"] is None
    assert "already inactive" in p["C"]["reason"]
    assert p["ghost"]["status"] == "unknown_customer" and p["ghost"]["risk_score"] is None


def test_model_unavailable_returns_503_without_leaking_details(session):
    r = make_client(session, None).post("/churn/predict", json={"customer_ids": ["A"]})
    assert r.status_code == 503
    assert r.json() == {"detail": "Churn model is unavailable"}


def test_other_endpoints_survive_a_missing_model(session):
    c = make_client(session, None)
    assert c.get("/health").status_code == 200
    assert c.get("/analytics/retention").status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"customer_ids": []},
        {"customer_ids": ["x"] * 101},
        {"customer_ids": ["bad id!"]},
        {"customer_ids": [""]},
        {"customer_ids": ["A"], "customer_id": "B"},  # unknown field
        {},
    ],
)
def test_invalid_requests_are_422(client, payload):
    assert client.post("/churn/predict", json=payload).status_code == 422


def test_empty_database_marks_everyone_unknown(session):
    r = make_client(session, stub_bundle()).post("/churn/predict", json={"customer_ids": ["A"]})
    assert r.status_code == 200
    assert r.json()["predictions"][0]["status"] == "unknown_customer"


def test_serving_matches_training_features_exactly(session):
    """Train/serve parity: the API score equals the real pipeline on features built directly."""
    _, events = gen.generate(150, seed=5, start="2026-01-01", days=120)
    ingest_events(session, [])  # no-op: exercises the empty batch path
    for i in range(0, len(events), 5000):
        chunk = events.iloc[i : i + 5000]
        res = ingest_events(
            session,
            [
                {
                    "event_id": r.event_id,
                    "customer_id": r.customer_id,
                    "event_name": r.event_name,
                    "event_timestamp": r.event_timestamp.isoformat(),
                    "properties": r.properties,
                }
                for r in chunk.itertuples()
            ],
        )
        assert res.rejected == []

    trained = train.train(
        events[["customer_id", "event_name", "event_timestamp", "properties"]], n_test=3
    )
    bundle = ModelBundle(pipeline=trained.pipeline, metadata=trained.metadata)
    client = make_client(session, bundle)

    cutoff = events["event_timestamp"].max().floor("D")
    x = features.build_features(events, [cutoff])
    expected = dict(
        zip(
            x.index.get_level_values("customer_id"),
            trained.pipeline.predict_proba(x[features.FEATURE_COLUMNS])[:, 1],
            strict=True,
        )
    )
    assert expected, "fixture should leave some customers eligible at the cutoff"

    ids = sorted(events["customer_id"].unique())[:60]
    body = client.post("/churn/predict", json={"customer_ids": ids}).json()
    scored = {p["customer_id"]: p for p in body["predictions"] if p["status"] == "scored"}
    assert set(scored) == set(expected) & set(ids)
    for cid, p in scored.items():
        assert p["risk_score"] == pytest.approx(expected[cid], abs=1e-4)
        assert 0.0 <= p["risk_score"] <= 1.0
    others = [p for p in body["predictions"] if p["status"] != "scored"]
    assert all(p["status"] == "not_eligible" for p in others)


# ---------------------------------------------------------------- review fixes
class FixedScore:
    def __init__(self, score: float):
        self.score = score

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        s = np.full(len(x), self.score)
        return np.column_stack([1 - s, s])


@pytest.mark.parametrize("raw", [0.49996, 0.49994, 0.5])
def test_class_always_agrees_with_the_returned_score(session, raw):
    ingest(session, ROWS)
    bundle = ModelBundle(pipeline=FixedScore(raw), metadata=stub_bundle().metadata)
    p = make_client(session, bundle).post("/churn/predict", json={"customer_ids": ["A"]}).json()
    pred = p["predictions"][0]
    assert (pred["risk_score"] >= p["decision_threshold"]) == (pred["predicted_class"] == "at_risk")


def test_known_customer_without_any_events_is_not_eligible_not_unknown(session):
    from datetime import UTC, datetime

    from app.db.models import Customer

    session.add(Customer(external_customer_id="A", created_at=datetime(2026, 1, 1, tzinfo=UTC)))
    session.commit()
    body = (
        make_client(session, stub_bundle())
        .post("/churn/predict", json={"customer_ids": ["A", "ghost"]})
        .json()
    )
    assert body["cutoff"] is None  # no events: no fabricated wall-clock cutoff
    p = {x["customer_id"]: x for x in body["predictions"]}
    assert p["A"]["status"] == "not_eligible" and "no events" in p["A"]["reason"]
    assert p["ghost"]["status"] == "unknown_customer"


def test_missing_model_is_503_even_when_the_database_is_broken():
    def broken_session():
        raise RuntimeError("DATABASE_URL is not configured")
        yield  # pragma: no cover

    app = create_app()
    act_as_allowed_user(app)
    app.dependency_overrides[get_session] = broken_session
    app.state.model_bundle = None
    r = TestClient(app, raise_server_exceptions=False).post(
        "/churn/predict", json={"customer_ids": ["A"]}
    )
    assert r.status_code == 503


def test_api_starts_and_serves_when_the_artifact_is_corrupt(session, tmp_path, monkeypatch):
    from app.ml import artifact

    (tmp_path / artifact.MODEL_FILE).write_bytes(b"garbage")
    (tmp_path / artifact.META_FILE).write_text("[]")
    monkeypatch.setattr(artifact, "ARTIFACT_DIR", tmp_path)
    app = create_app()
    act_as_allowed_user(app)
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:  # runs the lifespan, which loads the model
        assert app.state.model_bundle is None
        assert c.get("/health").status_code == 200
        assert c.post("/churn/predict", json={"customer_ids": ["A"]}).status_code == 503
