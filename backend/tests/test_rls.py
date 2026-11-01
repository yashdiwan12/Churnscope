"""Row-level security: tables Supabase exposes over its REST API must be closed to anon/authenticated.

Supabase exposes the `public` schema through PostgREST; with RLS off, anyone holding the (public)
anon key could read or change every table. The backend connects as a privileged role that bypasses
RLS, so enabling RLS with no policies denies the REST roles without affecting the API.
"""

import pytest
from sqlalchemy import text

TABLES = [
    "alembic_version",
    "customers",
    "datasets",
    "events",
    "predictions",
    "saved_reports",
    "user_profiles",
]


def test_rls_is_enabled_on_every_public_table(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "select relname, relrowsecurity from pg_class "
                "where relnamespace = 'public'::regnamespace and relkind = 'r'"
            )
        ).all()
    flags = dict(rows)
    assert sorted(flags) == TABLES
    assert [t for t, on in flags.items() if not on] == []


def test_a_non_owner_role_sees_nothing_even_with_select_granted(engine, session):
    """Functional proof: a role like Supabase's `anon` reads zero rows although rows exist."""
    with engine.begin() as conn:
        conn.execute(text("DROP ROLE IF EXISTS rls_probe"))
        conn.execute(text("CREATE ROLE rls_probe NOLOGIN"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO rls_probe"))
        conn.execute(text("GRANT SELECT, INSERT ON customers, events TO rls_probe"))
        conn.execute(text("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO rls_probe"))
        conn.execute(
            text(
                "INSERT INTO customers (dataset_id, external_customer_id, created_at) VALUES (1, 'rls-c', now())"
            )
        )
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            conn.execute(text("SET LOCAL ROLE rls_probe"))
            assert conn.scalar(text("SELECT count(*) FROM customers")) == 0
            with pytest.raises(Exception, match="row-level security"):
                conn.execute(
                    text(
                        "INSERT INTO customers (dataset_id, external_customer_id, created_at) VALUES (1, 'x', now())"
                    )
                )
            trans.rollback()
        with engine.connect() as conn:  # the privileged role (our backend) still sees the row
            assert conn.scalar(text("SELECT count(*) FROM customers")) == 1
    finally:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE events, customers RESTART IDENTITY CASCADE"))
            conn.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM rls_probe"))
            conn.execute(text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM rls_probe"))
            conn.execute(text("REVOKE USAGE ON SCHEMA public FROM rls_probe"))
            conn.execute(text("DROP ROLE rls_probe"))


def test_backend_role_can_still_read_and_write(engine, session):
    from app.services.ingestion import ingest_events

    r = ingest_events(
        session,
        [
            {
                "event_id": "rls-ok",
                "customer_id": "c1",
                "event_name": "session_start",
                "event_timestamp": "2026-01-05T00:00:00Z",
            }
        ],
    )
    assert r.inserted == 1
