"""Database reads for analytics. Returns DataFrames in the shape app.services.metrics expects."""

import pandas as pd
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Event


def data_through(session: Session) -> pd.Timestamp | None:
    """Timestamp of the latest event, i.e. how fresh the data is. None if there are no events."""
    ts = session.scalar(select(func.max(Event.event_timestamp)))
    return None if ts is None else pd.Timestamp(ts).tz_convert("UTC")


def load_events(
    session: Session, until: pd.Timestamp | None = None, since: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Events before ``until`` (all if None), loaded in memory.

    With ``since``, only events at or after it are fetched, plus every ``signup`` event (needed
    to tell new from returning users). Callers that need full history leave ``since`` unset.

    MVP trade-off: metrics are computed in Pandas over the full history, which is fine for the
    synthetic log (tens of thousands of rows) but is not a design for large event volumes.
    """
    stmt = select(
        Event.customer_id,
        Event.event_name,
        Event.event_timestamp,
        Event.properties,
    )
    if until is not None:
        stmt = stmt.where(Event.event_timestamp < until.to_pydatetime())
    if since is not None:
        stmt = stmt.where(
            or_(Event.event_timestamp >= since.to_pydatetime(), Event.event_name == "signup")
        )
    rows = session.execute(stmt).all()
    df = pd.DataFrame(rows, columns=["customer_id", "event_name", "event_timestamp", "properties"])
    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], utc=True)
    return df
