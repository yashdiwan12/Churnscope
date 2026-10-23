"""Pure-Pandas metric definitions. See docs/metrics.md for the rules these implement.

Input is an events DataFrame with columns ``customer_id``, ``event_name`` and a tz-aware UTC
``event_timestamp``. No database access: callers pass data in.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

EVENT_NAMES = (
    "signup",
    "session_start",
    "onboarding_complete",
    "feature_used",
    "report_created",
    "report_shared",
)
# Activity that counts as "using the product". signup and onboarding_complete are setup steps.
QUALIFYING_EVENTS = ("session_start", "feature_used", "report_created", "report_shared")
FUNNEL_STEPS = ("signup", "onboarding_complete", "report_created")
PERIOD_DAYS = 7

_REQUIRED = ("customer_id", "event_name", "event_timestamp")


def validate_events(events: pd.DataFrame) -> None:
    missing = [c for c in _REQUIRED if c not in events.columns]
    if missing:
        raise ValueError(f"events missing columns: {missing}")
    ts = events["event_timestamp"]
    if not isinstance(ts.dtype, pd.DatetimeTZDtype) or str(ts.dt.tz) != "UTC":
        raise ValueError("event_timestamp must be timezone-aware UTC")


def active_users(
    events: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    qualifying: Sequence[str] = QUALIFYING_EVENTS,
) -> int:
    """Distinct customers with >=1 qualifying event in [start, end)."""
    validate_events(events)
    ts = events["event_timestamp"]
    mask = events["event_name"].isin(qualifying) & (ts >= start) & (ts < end)
    return int(events.loc[mask, "customer_id"].nunique())


def funnel(
    events: pd.DataFrame,
    as_of: pd.Timestamp,
    steps: Sequence[str] = FUNNEL_STEPS,
    window_days: int = 14,
) -> pd.DataFrame:
    """User-level, ordered funnel anchored on the first step.

    Each customer is counted once per step, using their first occurrence of that event. A
    customer reaches step N only if they reached step N-1 and the first step-N event is at or
    after the step N-1 time and within ``window_days`` of the first step. Customers whose window
    has not fully elapsed at ``as_of`` are ineligible (right-censored) and excluded.

    ``conversion_from_previous`` = reached N / reached N-1. ``conversion_from_start`` = reached
    N / eligible. Both are NaN when the denominator is 0.
    """
    validate_events(events)
    first = (
        events[events["event_name"].isin(steps)]
        .groupby(["customer_id", "event_name"])["event_timestamp"]
        .min()
        .unstack("event_name")
        .reindex(columns=list(steps))
    )
    first = first.astype({s: "datetime64[ns, UTC]" for s in steps})
    window = pd.Timedelta(days=window_days)
    start = first[steps[0]]
    eligible = start.notna() & (start + window <= as_of)

    reached = eligible.copy()
    prev_ts = start
    counts = [int(eligible.sum())]
    for step in steps[1:]:
        ts = first[step]
        reached = reached & ts.notna() & (ts >= prev_ts) & (ts <= start + window)
        counts.append(int(reached.sum()))
        prev_ts = ts.where(reached)

    out = pd.DataFrame({"step": list(steps), "users": counts})
    prev = out["users"].shift(1).replace(0, np.nan)
    out["conversion_from_previous"] = out["users"] / prev
    out.loc[0, "conversion_from_previous"] = np.nan
    out["conversion_from_start"] = out["users"] / (counts[0] if counts[0] else np.nan)
    out["eligible_users"] = counts[0]
    return out


def cohort_retention(
    events: pd.DataFrame,
    as_of: pd.Timestamp,
    periods: int = 8,
    qualifying: Sequence[str] = QUALIFYING_EVENTS,
) -> pd.DataFrame:
    """Signup-week cohorts, retention by *elapsed* 7-day period since each customer's signup.

    Cohort = UTC calendar week (Monday start) of signup. Period k covers days
    [7k, 7k+7) after the customer's own signup timestamp (period 0 = first week).
    Retained = >=1 qualifying event in period k. A customer is eligible for period k only if
    that period has fully elapsed at ``as_of``; ineligible customers drop out of that cell's
    denominator, and a cell with no eligible customers is NaN (incomplete).

    Returns long format: cohort, period, cohort_size, eligible, retained, retention.
    """
    validate_events(events)
    signup = (
        events[events["event_name"] == "signup"].groupby("customer_id")["event_timestamp"].min()
    )
    if signup.empty:
        return pd.DataFrame(
            columns=["cohort", "period", "cohort_size", "eligible", "retained", "retention"]
        )
    cohort = signup.dt.tz_localize(None).dt.to_period("W-SUN").dt.start_time
    cohort.name = "cohort"

    act = events[events["event_name"].isin(qualifying)].join(
        signup.rename("signup_ts"), on="customer_id", how="inner"
    )
    act["period"] = (act["event_timestamp"] - act["signup_ts"]) // pd.Timedelta(days=PERIOD_DAYS)
    act = act[(act["period"] >= 0) & (act["period"] < periods)]
    retained_pairs = act[["customer_id", "period"]].drop_duplicates()

    rows = []
    sizes = cohort.value_counts()
    for k in range(periods):
        complete = signup + pd.Timedelta(days=PERIOD_DAYS * (k + 1)) <= as_of
        elig = cohort[complete].value_counts()
        kept_ids = retained_pairs.loc[retained_pairs["period"] == k, "customer_id"]
        kept = cohort[complete & cohort.index.isin(kept_ids)].value_counts()
        for c in sizes.index:
            e = int(elig.get(c, 0))
            r = int(kept.get(c, 0))
            rows.append(
                {
                    "cohort": c,
                    "period": k,
                    "cohort_size": int(sizes[c]),
                    "eligible": e,
                    "retained": r,
                    "retention": r / e if e else np.nan,
                }
            )
    return pd.DataFrame(rows).sort_values(["cohort", "period"]).reset_index(drop=True)
