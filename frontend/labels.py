"""Time-basis lines shown on every page. No Streamlit, so they test without a browser."""

from datetime import datetime, timedelta

NO_DATA = "No data yet"


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _day(d: datetime, with_year: bool = True) -> str:
    text = f"{d.day} {d.strftime('%b')}"  # strftime("%b") of the C locale; no %-d (not on Windows)
    return f"{text} {d.year}" if with_year else text


def window_label(window: dict) -> str:
    start = _parse(window["start"])
    end = _parse(window["end"])
    days = (end - start).days
    last = end - timedelta(days=1)  # the API's end is exclusive
    first = _day(start, with_year=start.year != last.year)
    unit = "day" if days == 1 else "days"
    return f"Window: {first} to {_day(last)} ({days} {unit})"


def freshness_label(ts: str | None) -> str:
    return NO_DATA if ts is None else f"Data through {_day(_parse(ts))}"


def cohorts_label(as_of: str | None) -> str:
    return NO_DATA if as_of is None else f"Cohorts as of {_day(_parse(as_of))}"


def cutoff_label(cutoff: str | None, window_days: int) -> str:
    if cutoff is None:
        return NO_DATA
    return f"Scored at cutoff {_day(_parse(cutoff))} using the {window_days} days before it"
