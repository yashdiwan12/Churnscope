"""SQLAlchemy models. See docs/05-data-model.md. All timestamps are timestamptz (UTC)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    external_customer_id: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    plan: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    churned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_customer_ts", "customer_id", "event_timestamp"),
        Index("ix_events_name_ts", "event_name", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The UNIQUE constraint is the idempotency guarantee, not application-side checks.
    event_id: Mapped[str] = mapped_column(Text, unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
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
