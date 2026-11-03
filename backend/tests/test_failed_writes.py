"""A write that fails in the database is never a 2xx and leaves no rows behind."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.db import datasets as datasets_db
from app.db import reports
from app.db.models import Dataset, Event, SavedReport
from app.db.session import get_session
from app.main import create_app
from tests.test_datasets_import_api import client_for, do_import, make_csv, users  # noqa: F401
from tests.test_events_api import KEY, event


def boom(*args, **kwargs):
    raise OperationalError("x", {}, Exception())


def count(session, model) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(model))


def call_events(session, uid, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("INGEST_API_KEY", KEY)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app, raise_server_exceptions=False)
    monkeypatch.setattr("app.api.routes.events.ingest_events", boom)
    return Event, lambda: client.post(
        "/events", json={"events": [event(1)]}, headers={"X-API-Key": KEY}
    )


def call_import(session, uid, monkeypatch):
    client = client_for(session, uid)
    monkeypatch.setattr(datasets_db, "replace_upload", boom)
    return Dataset, lambda: do_import(client, make_csv(3))


def call_delete(session, uid, monkeypatch):
    client = client_for(session, uid)
    made = do_import(client, make_csv(3))
    assert made.status_code == 201
    dataset_id = made.json()["dataset"]["id"]
    monkeypatch.setattr(datasets_db, "delete_upload", boom)
    return Dataset, lambda: client.delete(f"/datasets/{dataset_id}")


def call_report(session, uid, monkeypatch):
    client = client_for(session, uid)
    monkeypatch.setattr(reports, "create_report", boom)
    return SavedReport, lambda: client.post(
        "/me/reports", json={"report_type": "retention", "filters": {}}
    )


@pytest.mark.parametrize(
    "setup", [call_events, call_import, call_delete, call_report], ids=lambda f: f.__name__
)
def test_failed_write_is_never_2xx(setup, session, users, monkeypatch):  # noqa: F811
    model, call = setup(session, users[0], monkeypatch)
    before = count(session, model)
    r = call()
    get_settings.cache_clear()
    assert r.status_code == 503
    assert r.json() == {"detail": "Database unavailable"}
    assert count(session, model) == before
