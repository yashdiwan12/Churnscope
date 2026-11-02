"""datasets: every customer and event belongs to a dataset

Dataset 1 is the demo data (existing rows are backfilled to it); each signed-in user may own one
upload. Global uniqueness on external_customer_id / event_id becomes per-dataset, and a composite
foreign key stops an event pointing at another dataset's customer.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=True),
        sa.Column("signup_rule", sa.Text(), nullable=False),
        sa.Column("mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mapped_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("customer_count", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("data_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scoring", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('demo', 'upload')", name="ck_datasets_kind"),
        sa.CheckConstraint(
            "signup_rule IN ('event', 'derived_from_first_event')", name="ck_datasets_signup_rule"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_datasets_one_upload_per_owner",
        "datasets",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'upload'"),
    )
    op.execute(
        "INSERT INTO datasets (id, owner_id, kind, name, signup_rule, mapping, mapped_counts, "
        "customer_count, event_count) OVERRIDING SYSTEM VALUE "
        "SELECT 1, NULL, 'demo', 'Demo data (synthetic)', 'event', '{}', '{}', "
        "(SELECT count(*) FROM customers), (SELECT count(*) FROM events)"
    )
    # The next generated id is 2: the explicit insert above does not advance the identity.
    op.execute("SELECT setval(pg_get_serial_sequence('datasets', 'id'), 1)")

    for table in ("customers", "events"):
        op.add_column(
            table, sa.Column("dataset_id", sa.BigInteger(), server_default="1", nullable=False)
        )
        op.alter_column(table, "dataset_id", server_default=None)
        op.create_foreign_key(
            f"fk_{table}_dataset", table, "datasets", ["dataset_id"], ["id"], ondelete="CASCADE"
        )

    op.drop_constraint("events_customer_id_fkey", "events", type_="foreignkey")
    op.drop_constraint("customers_external_customer_id_key", "customers", type_="unique")
    op.drop_constraint("events_event_id_key", "events", type_="unique")
    op.create_unique_constraint(
        "uq_customers_dataset_external", "customers", ["dataset_id", "external_customer_id"]
    )
    op.create_unique_constraint("uq_customers_dataset_id", "customers", ["dataset_id", "id"])
    op.create_unique_constraint("uq_events_dataset_event_id", "events", ["dataset_id", "event_id"])
    op.create_foreign_key(
        "fk_events_dataset_customer",
        "events",
        "customers",
        ["dataset_id", "customer_id"],
        ["dataset_id", "id"],
    )

    op.drop_index("ix_events_customer_ts", table_name="events")
    op.drop_index("ix_events_name_ts", table_name="events")
    op.create_index(
        "ix_events_dataset_customer_ts", "events", ["dataset_id", "customer_id", "event_timestamp"]
    )
    op.create_index(
        "ix_events_dataset_name_ts", "events", ["dataset_id", "event_name", "event_timestamp"]
    )
    op.create_index("ix_events_dataset_id", "events", ["dataset_id", "id"])

    # Same lockdown as 0002: closed to Supabase's REST roles.
    op.execute('ALTER TABLE public."datasets" ENABLE ROW LEVEL SECURITY')
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
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM datasets WHERE kind = 'upload') THEN
                RAISE EXCEPTION 'cannot downgrade 0003: upload datasets exist; delete them first';
            END IF;
        END $$;
        """
    )
    op.drop_index("ix_events_dataset_id", table_name="events")
    op.drop_index("ix_events_dataset_name_ts", table_name="events")
    op.drop_index("ix_events_dataset_customer_ts", table_name="events")
    op.create_index("ix_events_name_ts", "events", ["event_name", "event_timestamp"])
    op.create_index("ix_events_customer_ts", "events", ["customer_id", "event_timestamp"])

    op.drop_constraint("fk_events_dataset_customer", "events", type_="foreignkey")
    op.drop_constraint("uq_events_dataset_event_id", "events", type_="unique")
    op.drop_constraint("uq_customers_dataset_id", "customers", type_="unique")
    op.drop_constraint("uq_customers_dataset_external", "customers", type_="unique")
    op.create_unique_constraint("events_event_id_key", "events", ["event_id"])
    op.create_unique_constraint(
        "customers_external_customer_id_key", "customers", ["external_customer_id"]
    )
    op.create_foreign_key("events_customer_id_fkey", "events", "customers", ["customer_id"], ["id"])

    for table in ("events", "customers"):
        op.drop_constraint(f"fk_{table}_dataset", table, type_="foreignkey")
        op.drop_column(table, "dataset_id")
    op.drop_index("uq_datasets_one_upload_per_owner", table_name="datasets")
    op.drop_table("datasets")
