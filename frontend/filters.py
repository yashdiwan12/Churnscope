"""Date-range helpers shared by the dashboard pages. Only date_range_sidebar uses Streamlit."""

from dataclasses import dataclass
from datetime import date, timedelta

MAX_RANGE_DAYS = 366  # the API's own limit, counted in inclusive days


@dataclass
class DateSelection:
    start: str | None
    end: str | None
    error: str | None


def validate_range(start: date, end: date) -> str | None:
    if start > end:
        return "The start date must be on or before the end date."
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        return f"The date range can span at most {MAX_RANGE_DAYS} days."
    return None


def to_api_range(start: date, end: date) -> tuple[str, str]:
    """The picker's end date is inclusive; the API's end is exclusive (next midnight UTC)."""
    return (
        f"{start.isoformat()}T00:00:00Z",
        f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
    )


def date_range_sidebar() -> DateSelection:
    import streamlit as st

    with st.sidebar:
        if st.checkbox("Latest 30 days", value=True):
            return DateSelection(None, None, None)
        today = date.today()
        start = st.date_input("Start date", value=today - timedelta(days=29))
        end = st.date_input("End date (inclusive)", value=today)
    if (error := validate_range(start, end)) is not None:
        return DateSelection(None, None, error)
    api_start, api_end = to_api_range(start, end)
    return DateSelection(api_start, api_end, None)
