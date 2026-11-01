"""Dataset visibility and ownership rules.

A dataset is visible to a caller when it is the demo dataset or the caller owns it. Anything
else is "not visible": callers turn that into 404, never 403, so ids do not leak existence.
"""

import uuid

from sqlalchemy import delete, func, insert, or_, select, text
from sqlalchemy.orm import Session

from app.db.models import Customer, Dataset, Event
from app.services import uploads

DEMO_DATASET_ID = 1


def visible(session: Session, user_id: uuid.UUID, dataset_id: int) -> Dataset | None:
    return session.scalar(
        select(Dataset).where(
            Dataset.id == dataset_id,
            or_(Dataset.id == DEMO_DATASET_ID, Dataset.owner_id == user_id),
        )
    )


def list_visible(session: Session, user_id: uuid.UUID) -> list[Dataset]:
    """The demo dataset first, then the caller's upload (if any)."""
    return list(
        session.scalars(
            select(Dataset)
            .where(or_(Dataset.id == DEMO_DATASET_ID, Dataset.owner_id == user_id))
            .order_by(Dataset.id != DEMO_DATASET_ID, Dataset.id)
        )
    )


def own_upload(session: Session, user_id: uuid.UUID) -> Dataset | None:
    return session.scalar(
        select(Dataset).where(Dataset.owner_id == user_id, Dataset.kind == "upload")
    )


def delete_upload(session: Session, user_id: uuid.UUID, dataset_id: int) -> bool:
    """Delete the caller's upload (customers and events cascade). Commits.

    False for the demo dataset, a missing id, or someone else's dataset. The caller evicts the
    dataset's churn-cache entries.
    """
    result = session.execute(
        delete(Dataset).where(
            Dataset.id == dataset_id,
            Dataset.owner_id == user_id,
            Dataset.kind == "upload",
        )
    )
    session.commit()
    return result.rowcount > 0


class StorageFull(Exception):
    """Storing the upload would take uploaded events past the global cap."""


def _delete_own_upload(session: Session, user_id: uuid.UUID) -> list[int]:
    return list(
        session.scalars(
            delete(Dataset)
            .where(Dataset.owner_id == user_id, Dataset.kind == "upload")
            .returning(Dataset.id)
        )
    )


def _insert_customers(session: Session, rows: list[dict]) -> dict[str, int]:
    ids: dict[str, int] = {}
    stmt = insert(Customer).returning(Customer.external_customer_id, Customer.id)
    for start in range(0, len(rows), uploads.INSERT_BATCH):
        batch = rows[start : start + uploads.INSERT_BATCH]
        ids.update({ext: pk for ext, pk in session.execute(stmt, batch)})
    return ids


def _insert_events(session: Session, rows: list[dict]) -> None:
    for start in range(0, len(rows), uploads.INSERT_BATCH):
        session.execute(insert(Event), rows[start : start + uploads.INSERT_BATCH])


def replace_upload(
    session: Session, user_id: uuid.UUID, filename: str, prepared: "uploads.Prepared"
) -> Dataset:
    """Store `prepared` as the caller's upload, replacing their old one, in one transaction.

    One global transaction-scoped advisory lock serialises imports, so the cap check, the delete
    of the old upload and the insert are one atomic step (spec D5). Any failure rolls back and the
    old upload stays. Commits; then evicts the old and new datasets' churn-cache entries.
    """
    from app.services import prediction  # prediction imports this module

    events, customers = prepared.events, prepared.customers
    old_ids: list[int] = []
    try:
        session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": uploads.IMPORT_LOCK_KEY}
        )
        others = session.scalar(
            select(func.coalesce(func.sum(Dataset.event_count), 0)).where(
                Dataset.kind == "upload", Dataset.owner_id != user_id
            )
        )
        if int(others) + len(events) > uploads.GLOBAL_UPLOADED_EVENTS_CAP:  # read at call time
            raise StorageFull
        old_ids = _delete_own_upload(session, user_id)
        dataset = Dataset(
            owner_id=user_id,
            kind="upload",
            name=filename,
            source_filename=filename,
            signup_rule=prepared.signup_rule,
            mapping=prepared.mapping,
            mapped_counts=prepared.mapped_counts,
            customer_count=len(customers),
            event_count=len(events),
            data_through=(
                None if events.empty else events["event_timestamp"].max().to_pydatetime()
            ),
        )
        session.add(dataset)
        session.flush()
        ids = _insert_customers(
            session,
            [
                {
                    "dataset_id": dataset.id,
                    "external_customer_id": c,
                    "created_at": t.to_pydatetime(),
                }
                for c, t in zip(customers["customer_id"], customers["created_at"], strict=True)
            ],
        )
        _insert_events(
            session,
            [
                {
                    "dataset_id": dataset.id,
                    "event_id": eid,
                    "customer_id": ids[c],
                    "event_name": name,
                    "event_timestamp": t.to_pydatetime(),
                    "properties": props,
                }
                for c, name, t, eid, props in zip(
                    events["customer_id"],
                    events["event_name"],
                    events["event_timestamp"],
                    events["event_id"],
                    events["properties"],
                    strict=True,
                )
            ],
        )
        session.commit()
    except BaseException:
        session.rollback()
        raise
    for dataset_id in [*old_ids, dataset.id]:
        prediction.evict_dataset(dataset_id)
    return dataset
