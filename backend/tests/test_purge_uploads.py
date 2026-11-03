import uuid

import pytest
from sqlalchemy import create_engine, func, select, text

from app.db.datasets import DEMO_DATASET_ID
from app.db.models import Customer, Dataset, Event, UserProfile
from scripts import purge_uploads


def make_upload(session, age_days: int) -> int:
    owner = uuid.uuid4()
    session.add(UserProfile(id=owner))
    session.commit()
    ds = Dataset(
        owner_id=owner,
        kind="upload",
        name="secret-name.csv",
        signup_rule="event",
        mapping={},
        mapped_counts={},
        customer_count=1,
        event_count=1,
    )
    session.add(ds)
    session.flush()
    cust = Customer(dataset_id=ds.id, external_customer_id="c1", created_at=func.now())
    session.add(cust)
    session.flush()
    session.add(
        Event(
            dataset_id=ds.id,
            event_id="e1",
            customer_id=cust.id,
            event_name="session_start",
            event_timestamp=func.now(),
        )
    )
    session.commit()
    session.execute(
        text("UPDATE datasets SET created_at = now() - make_interval(days => :d) WHERE id = :i"),
        {"d": age_days, "i": ds.id},
    )
    session.commit()
    return ds.id


def dataset_ids(session) -> set[int]:
    session.expire_all()
    return set(session.scalars(select(Dataset.id)))


def test_dry_run_deletes_nothing_and_reports_count(session, capsys):
    old, new = make_upload(session, 40), make_upload(session, 2)
    assert purge_uploads.main(["--older-than", "30", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "1" in out and "dry run" in out.lower()
    assert dataset_ids(session) == {DEMO_DATASET_ID, old, new}


def test_real_run_deletes_only_old_uploads_and_cascades(session, capsys):
    old, new = make_upload(session, 40), make_upload(session, 2)
    assert purge_uploads.main(["--older-than", "30"]) == 0
    out = capsys.readouterr().out
    assert "secret-name" not in out and "c1" not in out
    assert dataset_ids(session) == {DEMO_DATASET_ID, new}
    for model in (Customer, Event):
        n = session.scalar(select(func.count()).select_from(model).where(model.dataset_id == old))
        assert n == 0


def test_never_deletes_the_demo_dataset(session):
    session.execute(text("UPDATE datasets SET created_at = now() - interval '999 days'"))
    session.commit()
    assert purge_uploads.main(["--older-than", "1"]) == 0
    assert dataset_ids(session) == {DEMO_DATASET_ID}


@pytest.mark.parametrize("value", ["0", "-5", "abc", "1.5"])
def test_days_must_be_a_positive_integer(value, session):
    with pytest.raises(SystemExit) as exc:
        purge_uploads.main(["--older-than", value])
    assert exc.value.code == 2


def test_connection_error_prints_one_line_and_exits_1(monkeypatch, capsys):
    unreachable = create_engine(
        "postgresql+psycopg://user:secret@127.0.0.1:1/nowhere", connect_args={"connect_timeout": 2}
    )
    monkeypatch.setattr(purge_uploads, "get_engine", lambda: unreachable)
    assert purge_uploads.main(["--older-than", "30"]) == 1
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert err.startswith("purge failed: ")
    assert "secret" not in err and "Traceback" not in err
