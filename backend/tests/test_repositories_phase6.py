from sqlalchemy import select

from app.db import repositories
from app.db.models import Customer
from app.services.ingestion import ingest_events


def ev(i: int, customer: str = "c1", ts: str = "2026-01-05T12:00:00Z"):
    return {
        "event_id": f"e{i}",
        "customer_id": customer,
        "event_name": "feature_used",
        "event_timestamp": ts,
        "properties": {"feature": "exports"},
    }


def test_latest_event_id_none_when_empty(session):
    assert repositories.latest_event_id(session, 1) is None


def test_latest_event_id_grows_with_each_insert_even_when_timestamp_is_older(session):
    ingest_events(session, [ev(1, ts="2026-01-10T00:00:00Z")])
    first_id = repositories.latest_event_id(session, 1)
    through = repositories.data_through(session, 1)
    ingest_events(session, [ev(2, ts="2026-01-01T00:00:00Z")])
    assert repositories.latest_event_id(session, 1) > first_id
    assert repositories.data_through(session, 1) == through


def test_customer_external_ids_maps_pks_and_ignores_unknown(session):
    ingest_events(session, [ev(1, "c1"), ev(2, "c2")])
    pks = {c.external_customer_id: c.id for c in session.scalars(select(Customer))}
    got = repositories.customer_external_ids(session, 1, [pks["c1"], pks["c2"], 999999])
    assert got == {pks["c1"]: "c1", pks["c2"]: "c2"}
    assert repositories.customer_external_ids(session, 1, []) == {}
