"""enable row-level security on every public table

Supabase exposes the ``public`` schema through its REST API (PostgREST). With RLS off and the
default grants, anyone holding the project's public anon key could read, change, or truncate
these tables. Enabling RLS with no policies denies the REST roles; the backend connects as a
privileged role (``postgres``, BYPASSRLS) and is unaffected.

The revokes only run where the Supabase roles exist, so the migration also works on a plain
Postgres (local Docker, CI).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = [
    "alembic_version",
    "customers",
    "events",
    "predictions",
    "saved_reports",
    "user_profiles",
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        DO $$
        DECLARE r text;
        BEGIN
            FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
                    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
                    EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM %I', r);
                    -- tables created later by this role must not be re-opened by default grants
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', r
                    );
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', r
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    # Deliberately does not restore the anon/authenticated grants: re-opening the tables to the
    # public REST API is never the desired rollback. Re-grant by hand if you truly need it.
    for table in TABLES:
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
