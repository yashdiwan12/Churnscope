"""Dataset visibility and ownership rules.

A dataset is visible to a caller when it is the demo dataset or the caller owns it. Anything
else is "not visible": callers turn that into 404, never 403, so ids do not leak existence.
"""

import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.db.models import Dataset

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
    """Delete the caller's upload (customers and events cascade).

    False for the demo dataset, a missing id, or someone else's dataset.
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
