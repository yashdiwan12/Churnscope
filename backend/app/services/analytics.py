"""Orchestrates repositories + metrics into API-shaped results. No HTTP, no SQL here."""

from datetime import timedelta

import pandas as pd
from sqlalchemy.orm import Session

from app.db import repositories
from app.schemas.analytics import (
    DailyActive,
    EngagementOut,
    FunnelOut,
    FunnelStepOut,
    OverviewOut,
    RetentionCell,
    RetentionOut,
    Window,
)
from app.services import metrics

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 366


class InvalidRange(ValueError):
    pass


def _none(x: float) -> float | None:
    return None if pd.isna(x) else float(x)


def resolve_window(
    session: Session, start: pd.Timestamp | None, end: pd.Timestamp | None
) -> tuple[Window, pd.Timestamp | None]:
    """Validate/default the [start, end) window. Defaults to the last 30 days of data."""
    through = repositories.data_through(session)
    if end is None:
        latest = through if through is not None else pd.Timestamp.now("UTC")
        end = latest.floor("D") + timedelta(days=1)
    if start is None:
        start = end - timedelta(days=DEFAULT_WINDOW_DAYS)
    if start >= end:
        raise InvalidRange("start must be before end")
    if end - start > timedelta(days=MAX_WINDOW_DAYS):
        raise InvalidRange(f"window must not exceed {MAX_WINDOW_DAYS} days")
    return Window(start=start, end=end, data_through=through), through


def overview(session: Session, start: pd.Timestamp | None, end: pd.Timestamp | None) -> OverviewOut:
    window, _ = resolve_window(session, start, end)
    s, e = pd.Timestamp(window.start), pd.Timestamp(window.end)
    ev = repositories.load_events(session, until=e, since=s)
    active = metrics.active_users(ev, s, e)
    returning = metrics.returning_users(ev, s, e)
    in_window = ev[
        ev["event_name"].isin(metrics.QUALIFYING_EVENTS)
        & (ev["event_timestamp"] >= s)
        & (ev["event_timestamp"] < e)
    ]
    dau = metrics.daily_active_users(ev, s, e)
    return OverviewOut(
        window=window,
        active_users=active,
        new_users=metrics.new_users(ev, s, e),
        returning_users=returning,
        returning_user_rate=returning / active if active else None,
        qualifying_events=len(in_window),
        daily_active_users=[DailyActive(date=d, active_users=int(n)) for d, n in dau.items()],
        qualifying_event_names=list(metrics.QUALIFYING_EVENTS),
    )


def funnel_report(
    session: Session, start: pd.Timestamp | None, end: pd.Timestamp | None, window_days: int
) -> FunnelOut:
    """Funnel for customers who signed up in [start, end), censored at the data's latest event."""
    window, through = resolve_window(session, start, end)
    s, e = pd.Timestamp(window.start), pd.Timestamp(window.end)
    note = (
        f"Customers who signed up in the window; each step must happen within {window_days} days "
        "of signup. Customers whose window had not fully elapsed at the data's latest event "
        "are excluded."
    )
    if through is None:
        steps = [
            FunnelStepOut(
                step=x, users=0, conversion_from_previous=None, conversion_from_start=None
            )
            for x in metrics.FUNNEL_STEPS
        ]
        return FunnelOut(
            window=window, window_days=window_days, eligible_users=0, steps=steps, note=note
        )

    ev = repositories.load_events(session)
    # Scope by each customer's *first* signup, the same anchor the funnel uses.
    first_signup = ev[ev["event_name"] == "signup"].groupby("customer_id")["event_timestamp"].min()
    in_range = first_signup[(first_signup >= s) & (first_signup < e)]
    ev = ev[ev["customer_id"].isin(in_range.index)]
    f = metrics.funnel(ev, as_of=through, window_days=window_days)
    steps = [
        FunnelStepOut(
            step=r.step,
            users=int(r.users),
            conversion_from_previous=_none(r.conversion_from_previous),
            conversion_from_start=_none(r.conversion_from_start),
        )
        for r in f.itertuples()
    ]
    return FunnelOut(
        window=window,
        window_days=window_days,
        eligible_users=int(f["eligible_users"].iloc[0]),
        steps=steps,
        note=note,
    )


def retention_report(session: Session, periods: int) -> RetentionOut:
    through = repositories.data_through(session)
    if through is None:
        return RetentionOut(as_of=None, period_days=metrics.PERIOD_DAYS, periods=periods, cells=[])
    ev = repositories.load_events(session)
    r = metrics.cohort_retention(ev, as_of=through, periods=periods)
    cells = [
        RetentionCell(
            cohort=c.cohort.date(),
            period=int(c.period),
            cohort_size=int(c.cohort_size),
            eligible=int(c.eligible),
            retained=int(c.retained),
            retention=_none(c.retention),
            complete=bool(c.eligible == c.cohort_size),
        )
        for c in r.itertuples()
    ]
    return RetentionOut(
        as_of=through, period_days=metrics.PERIOD_DAYS, periods=periods, cells=cells
    )


def engagement_report(
    session: Session, start: pd.Timestamp | None, end: pd.Timestamp | None
) -> EngagementOut:
    window, _ = resolve_window(session, start, end)
    s, e = pd.Timestamp(window.start), pd.Timestamp(window.end)
    ev = repositories.load_events(session, until=e, since=s)
    return EngagementOut(window=window, **metrics.engagement(ev, s, e))
