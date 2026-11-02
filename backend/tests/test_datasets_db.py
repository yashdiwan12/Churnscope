import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db import datasets, repositories
from app.db.datasets import DEMO_DATASET_ID
from app.db.models import Customer, Dataset, Event, UserProfile
from app.services.ingestion import ingest_events


def ev(n, customer="c1", ts="2026-01-05T00:00:00Z", name="session_start"):
    return {
        "event_id": f"e{n}",
        "customer_id": customer,
        "event_name": name,
        "event_timestamp": ts,
    }


def make_user(session) -> uuid.UUID:
    uid = uuid.uuid4()
    session.add(UserProfile(id=uid))
    session.commit()
    return uid


def make_upload(session, owner) -> Dataset:
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
    session.commit()
    return ds


def test_migration_creates_demo_dataset(session):
    row = session.get(Dataset, DEMO_DATASET_ID)
    assert row is not None
    assert row.kind == "demo"
    assert row.owner_id is None


def test_demo_row_survives_earlier_tests_teardown(session):
    """The session fixture truncates between tests; the demo row must still be there, and a
    new dataset must never be handed id 1."""
    assert session.get(Dataset, DEMO_DATASET_ID) is not None
    assert make_upload(session, make_user(session)).id > DEMO_DATASET_ID


def test_existing_rows_backfilled_to_demo(session):
    ingest_events(session, [ev(1), ev(2, "c2")])
    assert session.scalars(select(Event.dataset_id)).all() == [DEMO_DATASET_ID] * 2
    assert session.scalars(select(Customer.dataset_id)).all() == [DEMO_DATASET_ID] * 2


def test_same_event_id_in_two_datasets_both_import(session):
    other = make_upload(session, make_user(session))
    ingest_events(session, [ev(1)])
    ingest_events(session, [ev(1)], dataset_id=other.id)
    for ds_id in (DEMO_DATASET_ID, other.id):
        n = session.scalar(select(func.count()).select_from(Event).where(Event.dataset_id == ds_id))
        assert n == 1


def test_event_cannot_reference_other_datasets_customer(session):
    other = make_upload(session, make_user(session))
    ingest_events(session, [ev(1)])
    cust = session.scalar(select(Customer.id))
    session.add(
        Event(
            event_id="x",
            dataset_id=other.id,
            customer_id=cust,
            event_name="session_start",
            event_timestamp=func.now(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_one_upload_per_owner(session):
    owner = make_user(session)
    make_upload(session, owner)
    with pytest.raises(IntegrityError):
        make_upload(session, owner)
    session.rollback()


def test_profile_delete_cascades_upload(session):
    owner = make_user(session)
    ds = make_upload(session, owner)
    ds_id = ds.id
    ingest_events(session, [ev(1)], dataset_id=ds_id)
    session.execute(text("DELETE FROM user_profiles WHERE id = :i"), {"i": owner})
    session.commit()
    assert session.scalar(select(func.count()).select_from(Event)) == 0
    assert session.scalar(select(func.count()).select_from(Customer)) == 0
    assert session.get(Dataset, ds_id) is None


def test_visible_and_delete_upload_rules(session):
    owner, stranger = make_user(session), make_user(session)
    ds = make_upload(session, owner)
    assert datasets.visible(session, stranger, DEMO_DATASET_ID).id == DEMO_DATASET_ID
    assert datasets.visible(session, owner, ds.id).id == ds.id
    assert datasets.visible(session, stranger, ds.id) is None
    assert datasets.visible(session, owner, 99999) is None
    assert [d.id for d in datasets.list_visible(session, owner)] == [DEMO_DATASET_ID, ds.id]
    assert [d.id for d in datasets.list_visible(session, stranger)] == [DEMO_DATASET_ID]
    assert datasets.own_upload(session, owner).id == ds.id
    assert datasets.own_upload(session, stranger) is None
    assert datasets.delete_upload(session, owner, DEMO_DATASET_ID) is False
    assert datasets.delete_upload(session, stranger, ds.id) is False
    assert datasets.delete_upload(session, owner, 99999) is False
    assert session.get(Dataset, ds.id) is not None
    assert datasets.delete_upload(session, owner, ds.id) is True
    assert datasets.own_upload(session, owner) is None


def test_repositories_scope_to_dataset(session):
    other = make_upload(session, make_user(session))
    ingest_events(session, [ev(1, "a", "2026-01-05T00:00:00Z")])
    ingest_events(
        session,
        [ev(2, "b", "2026-02-05T00:00:00Z"), ev(3, "b", "2026-02-06T00:00:00Z")],
        dataset_id=other.id,
    )
    d, o = DEMO_DATASET_ID, other.id
    assert len(repositories.load_events(session, d)) == 1
    assert len(repositories.load_events(session, o)) == 2
    assert repositories.data_through(session, d).month == 1
    assert repositories.data_through(session, o).month == 2
    assert repositories.latest_event_id(session, d) != repositories.latest_event_id(session, o)
    assert set(repositories.resolve_customers(session, d, ["a", "b"])) == {"a"}
    assert set(repositories.resolve_customers(session, o, ["a", "b"])) == {"b"}
    pk_b = repositories.resolve_customers(session, o, ["b"])["b"]
    assert repositories.customer_external_ids(session, d, [pk_b]) == {}
    assert repositories.customer_external_ids(session, o, [pk_b]) == {pk_b: "b"}
    assert repositories.latest_event_id(session, 99999) is None


def test_downgrade_refuses_when_uploads_exist(engine, session):
    make_upload(session, make_user(session))
    cfg = Config("alembic.ini")
    try:
        with pytest.raises(Exception, match="upload"):
            command.downgrade(cfg, "0002")
    finally:
        session.rollback()
        # Restore head whatever happened, so later tests see the full schema.
        command.upgrade(cfg, "head")
    assert session.get(Dataset, DEMO_DATASET_ID) is not None


def test_downgrade_then_upgrade_keeps_demo_data(engine, session):
    session.execute(text("DELETE FROM datasets WHERE kind = 'upload'"))
    session.commit()
    ingest_events(session, [ev(1), ev(2, customer="c2")])
    demo_events = session.scalar(
        select(func.count()).select_from(Event).where(Event.dataset_id == DEMO_DATASET_ID)
    )
    assert demo_events >= 2
    session.rollback()  # end the read transaction so the migration can take its locks
    cfg = Config("alembic.ini")
    try:
        command.downgrade(cfg, "0002")
        command.upgrade(cfg, "head")
    finally:
        session.rollback()
        command.upgrade(cfg, "head")  # whatever happened, later tests see the full schema
    session.expire_all()
    assert session.get(Dataset, DEMO_DATASET_ID).kind == "demo"
    assert (
        session.scalar(
            select(func.count()).select_from(Event).where(Event.dataset_id == DEMO_DATASET_ID)
        )
        == demo_events
    )
    assert session.scalar(select(func.count()).select_from(Event)) == demo_events
    # The uploads-era constraints are back: a customer id is unique per dataset, not globally.
    owner = make_user(session)
    upload = make_upload(session, owner)
    session.add(
        Customer(
            dataset_id=upload.id,
            external_customer_id="c1",
            created_at=datetime(2026, 1, 5, tzinfo=UTC),
        )
    )
    session.commit()
