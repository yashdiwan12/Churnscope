from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Customer, Event
from app.services.ingestion import ingest_events


def ev(i: int, customer: str = "c1", **over):
    base = {
        "event_id": f"e{i}",
        "customer_id": customer,
        "event_name": "feature_used",
        "event_timestamp": "2026-01-05T12:00:00Z",
        "properties": {"feature": "exports"},
    }
    return base | over


def count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_valid_events_inserted_and_customer_created(session):
    r = ingest_events(session, [ev(1), ev(2, "c2")])
    assert (r.received, r.inserted, r.duplicates, r.rejected) == (2, 2, 0, [])
    assert count(session, Event) == 2 and count(session, Customer) == 2


def test_reingesting_same_batch_creates_no_duplicates(session):
    batch = [ev(1), ev(2), ev(3)]
    ingest_events(session, batch)
    r = ingest_events(session, batch)
    assert (r.inserted, r.duplicates) == (0, 3)
    assert count(session, Event) == 3 and count(session, Customer) == 1


def test_duplicate_within_one_batch_and_overlapping_batches(session):
    r = ingest_events(session, [ev(1), ev(1), ev(2)])
    assert (r.inserted, r.duplicates) == (2, 1)
    r = ingest_events(session, [ev(2), ev(3)])
    assert (r.inserted, r.duplicates) == (1, 1)
    assert count(session, Event) == 3


def test_concurrent_ingestion_of_same_events_does_not_duplicate(session, engine):
    batch = [ev(i) for i in range(50)]

    def run():
        with Session(engine) as s:
            return ingest_events(s, batch).inserted

    with ThreadPoolExecutor(4) as pool:
        inserted = list(pool.map(lambda _: run(), range(4)))
    assert sum(inserted) == 50
    assert count(session, Event) == 50


def test_invalid_events_rejected_with_reason_and_valid_ones_kept(session):
    bad = [
        ev(1, event_name="nope"),
        ev(2, event_timestamp="2026-01-05T12:00:00"),  # no timezone
        ev(3, event_timestamp="not a date"),
        ev(4, customer_id=""),
        ev(5, properties={"x": "y" * 5000}),
        ev(6, properties={"nested": {"a": 1}}),
        ev(7, surprise="field"),
        {"event_id": "e8"},
        ev(9),
    ]
    r = ingest_events(session, bad)
    assert r.inserted == 1 and [x.index for x in r.rejected] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert count(session, Event) == 1


def test_rejection_reason_does_not_echo_payload_values(session):
    secret = "SENSITIVE-VALUE-123"
    r = ingest_events(session, [ev(1, event_name=secret)])
    assert secret not in r.rejected[0].reason


def test_timestamps_normalised_to_utc(session):
    ingest_events(session, [ev(1, event_timestamp="2026-01-05T12:00:00+02:00")])
    ts = session.scalar(select(Event.event_timestamp))
    assert ts.utcoffset().total_seconds() == 0 and ts.hour == 10


def test_failed_write_rolls_back_everything(session, monkeypatch):
    import app.services.ingestion as ing

    def boom(*a, **k):
        raise RuntimeError("db down")

    original = ing.insert

    class Wrapper:
        def __call__(self, model):
            if model is Event:
                boom()
            return original(model)

    monkeypatch.setattr(ing, "insert", Wrapper())
    try:
        ingest_events(session, [ev(1)])
    except RuntimeError:
        pass
    assert count(session, Customer) == 0 and count(session, Event) == 0
