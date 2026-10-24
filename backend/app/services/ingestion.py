"""Validated, idempotent event ingestion.

Pipeline: validate each row -> resolve customers -> INSERT ... ON CONFLICT (event_id) DO NOTHING
in one transaction. Duplicates are detected by the database UNIQUE constraint, so concurrent
retries cannot race.
"""

from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Customer, Event
from app.schemas.events import EventIn, IngestResult, Rejection

MAX_BATCH = 5000


def _reason(err: ValidationError) -> str:
    # Field path + message only: never echo the input value (may be sensitive).
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'event'}: {e['msg']}" for e in err.errors()
    )


def ingest_events(session: Session, raw_events: Sequence[dict[str, Any]]) -> IngestResult:
    if len(raw_events) > MAX_BATCH:
        raise ValueError(f"batch exceeds {MAX_BATCH} events")

    valid: list[EventIn] = []
    rejected: list[Rejection] = []
    for i, raw in enumerate(raw_events):
        try:
            valid.append(EventIn.model_validate(raw))
        except ValidationError as err:
            rejected.append(Rejection(index=i, reason=_reason(err)))

    inserted = 0
    if valid:
        try:
            ids = _resolve_customers(session, valid)
            rows = [
                {
                    "event_id": e.event_id,
                    "customer_id": ids[e.customer_id],
                    "event_name": e.event_name,
                    "event_timestamp": e.event_timestamp,
                    "properties": e.properties,
                }
                for e in valid
            ]
            stmt = insert(Event).values(rows).on_conflict_do_nothing(index_elements=["event_id"])
            inserted = len(session.execute(stmt.returning(Event.id)).all())
            session.commit()  # customers + events land together or not at all
        except Exception:
            session.rollback()
            raise

    return IngestResult(
        received=len(raw_events),
        inserted=inserted,
        duplicates=len(valid) - inserted,
        rejected=rejected,
    )


def _resolve_customers(session: Session, events: Sequence[EventIn]) -> dict[str, int]:
    """Map external ids to internal ids, creating unknown customers.

    A new customer's created_at is its earliest event in the batch (a placeholder until the
    customer table is loaded from the source of truth).
    """
    earliest: dict[str, Any] = {}
    for e in events:
        if e.customer_id not in earliest or e.event_timestamp < earliest[e.customer_id]:
            earliest[e.customer_id] = e.event_timestamp

    stmt = insert(Customer).values(
        [{"external_customer_id": c, "created_at": ts} for c, ts in earliest.items()]
    )
    session.execute(stmt.on_conflict_do_nothing(index_elements=["external_customer_id"]))
    rows = session.execute(
        select(Customer.external_customer_id, Customer.id).where(
            Customer.external_customer_id.in_(earliest)
        )
    )
    return {ext: pk for ext, pk in rows}
