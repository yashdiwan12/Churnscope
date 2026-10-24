import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://churnscope:churnscope@localhost:5433/churnscope"
)


@pytest.fixture(scope="session")
def engine():
    """Fresh schema built by the real Alembic migrations. Skips if Postgres is unreachable."""
    eng = create_engine(TEST_DB_URL)
    try:
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    except OperationalError as exc:
        pytest.skip(f"Postgres not available ({type(exc).__name__}); run `docker compose up -d`")

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
