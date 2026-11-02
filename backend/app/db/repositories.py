"""Database reads for analytics. Returns DataFrames in the shape app.services.metrics expects."""

import pandas as pd
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Customer, Event


def data_through(session: Session, dataset_id: int) -> pd.Timestamp | None:
    """Timestamp of the dataset's latest event, i.e. how fresh the data is. None if no events."""
    ts = session.scalar(
        select(func.max(Event.event_timestamp)).where(Event.dataset_id == dataset_id)
    )
    return None if ts is None else pd.Timestamp(ts).tz_convert("UTC")


def latest_event_id(session: Session, dataset_id: int) -> int | None:
    """Highest event id, which grows with every insert whatever the event's own timestamp is."""
    return session.scalar(select(func.max(Event.id)).where(Event.dataset_id == dataset_id))


def customer_external_ids(session: Session, dataset_id: int, pks: list[int]) -> dict[int, str]:
    """Map internal customer ids to external ids; unknown ids are absent from the result."""
    if not pks:
        return {}
    rows = session.execute(
        select(Customer.id, Customer.external_customer_id).where(
            Customer.dataset_id == dataset_id, Customer.id.in_(pks)
        )
    )
    return {pk: ext for pk, ext in rows}


def resolve_customers(session: Session, dataset_id: int, external_ids: list[str]) -> dict[str, int]:
    """Map external customer ids to internal ids; unknown ids are absent from the result."""
    rows = session.execute(
        select(Customer.external_customer_id, Customer.id).where(
            Customer.dataset_id == dataset_id, Customer.external_customer_id.in_(external_ids)
        )
    )
    return {ext: pk for ext, pk in rows}


def load_events(
    session: Session,
    dataset_id: int,
    until: pd.Timestamp | None = None,
    since: pd.Timestamp | None = None,
    customer_ids: list[int] | None = None,
) -> pd.DataFrame:
    """The dataset's events before ``until`` (all if None), loaded in memory.

    With ``customer_ids``, only those customers' events are fetched. With ``since``, only events
    at or after it are fetched, plus every ``signup`` event (needed to tell new from returning
    users). Callers that need full history leave ``since`` unset.

    MVP trade-off: metrics are computed in Pandas over the full history, which is fine for the
    synthetic log (tens of thousands of rows) but is not a design for large event volumes.
    """
    stmt = select(
        Event.customer_id,
        Event.event_name,
        Event.event_timestamp,
        Event.properties,
    ).where(Event.dataset_id == dataset_id)
    if until is not None:
        stmt = stmt.where(Event.event_timestamp < until.to_pydatetime())
    if customer_ids is not None:
        stmt = stmt.where(Event.customer_id.in_(customer_ids))
    if since is not None:
        stmt = stmt.where(
            or_(Event.event_timestamp >= since.to_pydatetime(), Event.event_name == "signup")
        )
    rows = session.execute(stmt).all()
    df = pd.DataFrame(rows, columns=["customer_id", "event_name", "event_timestamp", "properties"])
    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], utc=True)
    return df
