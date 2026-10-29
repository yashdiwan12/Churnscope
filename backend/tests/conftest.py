import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

# A database of its own: the fixture drops its schema, so it must never be the dev database.
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://churnscope:churnscope@localhost:5433/churnscope_test",
)


def _ensure_database(url: str) -> None:
    """Create the test database on the same server if it does not exist yet."""
    target = make_url(url)
    admin = create_engine(
        target.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )
    try:
        with admin.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        admin.dispose()


_db_unreachable: str | None = (
    None  # remembered so a down database costs one timeout, not one per test
)


@pytest.fixture(scope="session")
def engine():
    """Fresh schema built by the real Alembic migrations. Skips if Postgres is unreachable."""
    global _db_unreachable
    if _db_unreachable:
        pytest.skip(_db_unreachable)
    eng = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 5})
    try:
        _ensure_database(TEST_DB_URL)
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    except OperationalError as exc:
        if os.environ.get("CI"):  # CI must exercise the DB tests, so never skip silently there
            raise
        _db_unreachable = (
            f"Postgres not available ({type(exc).__name__}); run `docker compose up -d`"
        )
        pytest.skip(_db_unreachable)

    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DB_URL
    from app.core.config import get_settings

    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    yield eng
    if old is None:
        os.environ.pop("DATABASE_URL")
    else:
        os.environ["DATABASE_URL"] = old
    get_settings.cache_clear()
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE events, customers RESTART IDENTITY CASCADE"))
