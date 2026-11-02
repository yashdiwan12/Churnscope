"""SQLAlchemy models. See docs/05-data-model.md. All timestamps are timestamptz (UTC)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    """Owns every customer and event row. Row 1 is the shared demo data; others are uploads."""

    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint("kind IN ('demo', 'upload')", name="ck_datasets_kind"),
        CheckConstraint(
            "signup_rule IN ('event', 'derived_from_first_event')", name="ck_datasets_signup_rule"
        ),
        Index(
            "uq_datasets_one_upload_per_owner",
            "owner_id",
            unique=True,
            postgresql_where=text("kind = 'upload'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    source_filename: Mapped[str | None] = mapped_column(Text)
    signup_rule: Mapped[str] = mapped_column(Text)
    mapping: Mapped[dict] = mapped_column(JSONB)
    mapped_counts: Mapped[dict] = mapped_column(JSONB)
    customer_count: Mapped[int] = mapped_column(Integer)
    event_count: Mapped[int] = mapped_column(Integer)
    data_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scoring: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "external_customer_id", name="uq_customers_dataset_external"
        ),
        UniqueConstraint("dataset_id", "id", name="uq_customers_dataset_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("datasets.id", ondelete="CASCADE")
    )
    external_customer_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    plan: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    churned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        # The UNIQUE constraint is the idempotency guarantee, not application-side checks.
        UniqueConstraint("dataset_id", "event_id", name="uq_events_dataset_event_id"),
        # An event can never point at another dataset's customer.
        ForeignKeyConstraint(
            ["dataset_id", "customer_id"],
            ["customers.dataset_id", "customers.id"],
            name="fk_events_dataset_customer",
        ),
        Index("ix_events_dataset_customer_ts", "dataset_id", "customer_id", "event_timestamp"),
        Index("ix_events_dataset_name_ts", "dataset_id", "event_name", "event_timestamp"),
        Index("ix_events_dataset_id", "dataset_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("datasets.id", ondelete="CASCADE")
    )
    event_id: Mapped[str] = mapped_column(Text)
    customer_id: Mapped[int] = mapped_column(BigInteger)
    event_name: Mapped[str] = mapped_column(Text)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    properties: Mapped[dict | None] = mapped_column(JSONB)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedReport(Base):
    __tablename__ = "saved_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_profiles.id"))
    report_type: Mapped[str] = mapped_column(String(50))
    filters: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (CheckConstraint("risk_score BETWEEN 0 AND 1", name="ck_risk_score_range"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    prediction_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prediction_horizon: Mapped[str] = mapped_column(Text)
    risk_score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    predicted_class: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(Text)
