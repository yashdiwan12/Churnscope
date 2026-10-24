"""A down or unconfigured database must give a clean 503, never a 500 or a leaked connection string."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import DatabaseUnavailable, get_session
from app.main import create_app

UNREACHABLE = "postgresql+psycopg://user:secret@127.0.0.1:1/nowhere"


def unreachable_session():
    engine = create_engine(UNREACHABLE, connect_args={"connect_timeout": 2})
    with Session(engine) as session:
        yield session


def unconfigured_session():
    raise DatabaseUnavailable("DATABASE_URL is not configured")
    yield  # pragma: no cover


@pytest.mark.parametrize("dependency", [unreachable_session, unconfigured_session])
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/analytics/overview", None),
        ("get", "/analytics/retention", None),
        ("post", "/churn/predict", {"customer_ids": ["A"]}),
    ],
)
def test_database_failures_are_503_without_details(dependency, method, path, body):
    app = create_app()
    app.dependency_overrides[get_session] = dependency
    app.state.model_bundle = object()  # past the model check, so the DB is what fails
    client = TestClient(app, raise_server_exceptions=False)
    r = client.request(method, path, json=body)
    assert r.status_code == 503
    assert r.json() == {"detail": "Database unavailable"}
    assert "secret" not in r.text and "127.0.0.1" not in r.text


def test_health_does_not_depend_on_the_database():
    app = create_app()
    app.dependency_overrides[get_session] = unconfigured_session
    assert TestClient(app).get("/health").status_code == 200
