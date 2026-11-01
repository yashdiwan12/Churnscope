"""dataset_id on analytics and churn routes: visibility (404, never 403), isolation, cache."""

import uuid
from datetime import UTC, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.authorization import current_user
from app.core.security import AuthUser
from app.db.models import Customer, Dataset, Event, UserProfile
from app.db.session import get_session
from app.main import create_app
from app.services import prediction
from app.services.ingestion import ingest_events
from tests.test_churn_api import stub_bundle

NOT_FOUND = {"detail": "Dataset not found"}
PATHS = [
    "/analytics/overview",
    "/analytics/funnel",
    "/analytics/retention",
    "/analytics/engagement",
    "/churn/at-risk",
]


@pytest.fixture(autouse=True)
def _fresh_cache():
    prediction.clear_at_risk_cache()
    yield
    prediction.clear_at_risk_cache()


def make_upload(session, owner: uuid.UUID, customers: int = 0) -> Dataset:
    ds = Dataset(
        owner_id=owner,
        kind="upload",
        name="mine.csv",
        signup_rule="event",
        mapping={},
        mapped_counts={},
        customer_count=0,
        event_count=0,
    )
    session.add(ds)
    session.flush()
    for i in range(customers):
        c = Customer(
            dataset_id=ds.id,
            external_customer_id=f"u{i}",
            created_at=datetime(2026, 1, 5, tzinfo=UTC),
        )
        session.add(c)
        session.flush()
        session.add(
            Event(
                dataset_id=ds.id,
                event_id=f"e{i}",
                customer_id=c.id,
                event_name="signup",
                event_timestamp=datetime(2026, 1, 5, tzinfo=UTC),
            )
        )
    session.commit()
    return ds


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
    return TestClient(app)


def seed_demo(session):
    ingest_events(
        session,
        [
            {
                "event_id": f"d{i}",
                "customer_id": f"D{i}",
                "event_name": "signup",
                "event_timestamp": "2026-01-05T00:00:00Z",
                "properties": {},
            }
            for i in range(2)
        ],
    )


@pytest.mark.parametrize("path", PATHS[:4])
def test_analytics_routes_accept_demo_default(session, users, path):
    seed_demo(session)
    c = client_for(session, users[0])
    default = c.get(path)
    explicit = c.get(path, params={"dataset_id": 1})
    assert default.status_code == 200
    assert explicit.status_code == 200
    assert "detail" not in default.json()
    assert default.json() == explicit.json()


@pytest.mark.parametrize("path", PATHS)
def test_foreign_dataset_is_404_on_every_route(session, users, path):
    foreign = make_upload(session, users[1])
    r = client_for(session, users[0]).get(path, params={"dataset_id": foreign.id})
    assert r.status_code == 404
    assert r.json() == NOT_FOUND


@pytest.mark.parametrize("path", PATHS)
def test_missing_and_huge_ids_are_404_or_422(session, users, path):
    c = client_for(session, users[0])
    assert c.get(path, params={"dataset_id": 999999}).json() == NOT_FOUND
    assert c.get(path, params={"dataset_id": 2**63}).status_code == 422
    assert c.get(path, params={"dataset_id": 0}).status_code == 422


def test_owner_sees_own_dataset_numbers(session, users):
    seed_demo(session)  # 2 demo customers must not leak into the upload's numbers
    mine = make_upload(session, users[0], customers=3)
    c = client_for(session, users[0])
    body = c.get(
        "/analytics/overview",
        params={
            "dataset_id": mine.id,
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-02-01T00:00:00Z",
        },
    ).json()
    assert body["new_users"] == 3
    demo = c.get(
        "/analytics/overview",
        params={"start": "2026-01-01T00:00:00Z", "end": "2026-02-01T00:00:00Z"},
    ).json()
    assert demo["new_users"] == 2


def test_upload_at_risk_is_409_before_scoring(session, users, monkeypatch):
    mine = make_upload(session, users[0], customers=1)

    def boom(*a, **k):
        raise AssertionError("must not score an upload")

    monkeypatch.setattr(prediction, "score_all", boom)
    r = client_for(session, users[0]).get("/churn/at-risk", params={"dataset_id": mine.id})
    assert r.status_code == 409
    assert r.json() == {"detail": "Churn scoring is not available for this dataset"}
    assert not prediction._cache


def test_at_risk_cache_keyed_per_dataset_and_bounded(session, monkeypatch):
    seed_demo(session)
    monkeypatch.setattr(
        prediction,
        "score_all",
        lambda s, b, dataset_id, cutoff: pd.DataFrame({"customer_id": [], "risk_score": []}),
    )
    bundle = stub_bundle()
    stamps = [pd.Timestamp(f"2026-02-0{d}", tz="UTC") for d in range(1, 6)]
    for ts in stamps:
        prediction._scored(session, bundle, 1, ts)
    assert len(prediction._cache) == 4
    cutoffs = [k[2] for k in prediction._cache]
    assert stamps[0] not in cutoffs and stamps[-1] in cutoffs  # oldest evicted

    prediction.clear_at_risk_cache()
    prediction._scored(session, bundle, 1, stamps[0])
    prediction._cache[(2, bundle.version, stamps[0], None)] = pd.DataFrame()
    prediction.evict_dataset(1)
    assert [k[0] for k in prediction._cache] == [2]
