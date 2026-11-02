"""Validated, idempotent event ingestion.

Pipeline: validate each row -> resolve customers -> INSERT ... ON CONFLICT (dataset_id, event_id) DO NOTHING
in one transaction. Duplicates are detected by the database UNIQUE constraint, so concurrent
retries cannot race.
"""

from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.datasets import DEMO_DATASET_ID
from app.db.models import Customer, Event
from app.schemas.events import EventIn, IngestResult, Rejection

MAX_BATCH = 5000


def _reason(err: ValidationError) -> str:
    # Field path + message only: never echo the input value (may be sensitive).
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'event'}: {e['msg']}" for e in err.errors()
    )


def ingest_events(
    session: Session, raw_events: Sequence[dict[str, Any]], dataset_id: int = DEMO_DATASET_ID
) -> IngestResult:
    if len(raw_events) > MAX_BATCH:
        raise ValueError(f"batch exceeds {MAX_BATCH} events")

    valid: list[EventIn] = []
    rejected: list[Rejection] = []
    for i, raw in enumerate(raw_events):
        try:
            valid.append(EventIn.model_validate(raw))
        except ValidationError as err:
            rejected.append(Rejection(index=i, reason=_reason(err)))

    inserted = conflicts = 0
    if valid:
        try:
            ids = _resolve_customers(session, dataset_id, valid)
            rows = [
                {
                    "dataset_id": dataset_id,
                    "event_id": e.event_id,
                    "customer_id": ids[e.customer_id],
                    "event_name": e.event_name,
                    "event_timestamp": e.event_timestamp,
                    "properties": e.properties,
                }
                for e in valid
            ]
            stmt = (
                insert(Event)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["dataset_id", "event_id"])
            )
            new_ids = {r[0] for r in session.execute(stmt.returning(Event.event_id))}
            inserted = len(new_ids)
            conflicts = _count_conflicts(session, dataset_id, rows, new_ids)
            session.commit()  # customers + events land together or not at all
        except Exception:
            session.rollback()
            raise

    return IngestResult(
        received=len(raw_events),
        inserted=inserted,
        duplicates=len(valid) - inserted,
        conflicts=conflicts,
        rejected=rejected,
    )


def _count_conflicts(session: Session, dataset_id: int, rows: list[dict], new_ids: set[str]) -> int:
    """How many non-inserted rows differ from what is stored under their event_id.

    A retry of the same event is a harmless duplicate; the same event_id with different content
    is a producer bug worth surfacing (the stored row is kept: first write wins).
    """
    seen: set[str] = set()
    pending = []
    for r in rows:
        if r["event_id"] in new_ids and r["event_id"] not in seen:
            seen.add(r["event_id"])  # this occurrence is the one that was written
            continue
        pending.append(r)
    if not pending:
        return 0
    stored = {
        row.event_id: row
        for row in session.execute(
            select(
                Event.event_id,
                Event.customer_id,
                Event.event_name,
                Event.event_timestamp,
                Event.properties,
            ).where(
                Event.dataset_id == dataset_id,
                Event.event_id.in_({r["event_id"] for r in pending}),
            )
        )
    }
    return sum(
        (s.customer_id, s.event_name, s.event_timestamp, s.properties or {})
        != (r["customer_id"], r["event_name"], r["event_timestamp"], r["properties"] or {})
        for r in pending
        if (s := stored.get(r["event_id"])) is not None
    )


def _resolve_customers(
    session: Session, dataset_id: int, events: Sequence[EventIn]
) -> dict[str, int]:
    """Map external ids to internal ids, creating unknown customers.

    created_at is a placeholder until the customer table is loaded from the source of truth: the
    earliest event seen for the customer, moved earlier if an older event arrives later.
    """
    earliest: dict[str, Any] = {}
    for e in events:
        if e.customer_id not in earliest or e.event_timestamp < earliest[e.customer_id]:
            earliest[e.customer_id] = e.event_timestamp

    stmt = insert(Customer).values(
        [
            {"dataset_id": dataset_id, "external_customer_id": c, "created_at": ts}
            for c, ts in earliest.items()
        ]
    )
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["dataset_id", "external_customer_id"],
            set_={"created_at": func.least(Customer.created_at, stmt.excluded.created_at)},
        )
    )
    rows = session.execute(
        select(Customer.external_customer_id, Customer.id).where(
            Customer.dataset_id == dataset_id, Customer.external_customer_id.in_(earliest)
        )
    )
    return {ext: pk for ext, pk in rows}
