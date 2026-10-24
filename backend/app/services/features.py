"""Leakage-aware churn features and labels. Definitions: docs/model_card.md.

For a cutoff ``t`` and a customer:

* features use only events in ``[t - 28d, t)`` plus first-occurrence timestamps strictly before
  ``t``;
* the label uses only events in ``[t, t + 14d)``;
* a customer is *eligible* at ``t`` if they signed up before ``t`` and had >= 1 qualifying event in
  the feature window (a customer already inactive has already churned, so is not scored).

Features and label windows are disjoint and half-open, so nothing at or after ``t`` reaches a
feature.
"""

from collections.abc import Iterable

import numpy as np
import pandas as pd

from app.services.metrics import QUALIFYING_EVENTS, validate_events

WINDOW_DAYS = 28
HORIZON_DAYS = 14

FEATURE_COLUMNS = [
    "days_since_last_activity",
    "active_days_28d",
    "active_days_14d",
    "events_28d",
    "sessions_28d",
    "features_used_28d",
    "reports_created_28d",
    "reports_shared_28d",
    "events_last_14d",
    "events_prev_14d",
    "activity_change",
    "distinct_features_28d",
    "onboarding_complete",
    "has_created_report",
    "account_age_days",
]

_DAY = pd.Timedelta(days=1)
_CATEGORY_COLUMN = {
    "session_start": "sessions_28d",
    "feature_used": "features_used_28d",
    "report_created": "reports_created_28d",
    "report_shared": "reports_shared_28d",
}


def _first_times(events: pd.DataFrame) -> pd.DataFrame:
    first = events.groupby(["customer_id", "event_name"])["event_timestamp"].min().unstack()
    first = first.reindex(columns=["signup", "onboarding_complete", "report_created"])
    return first.astype("datetime64[ns, UTC]")  # a missing event type must stay datetime, not NaN


def build_features(
    events: pd.DataFrame, cutoffs: Iterable[pd.Timestamp], window_days: int = WINDOW_DAYS
) -> pd.DataFrame:
    """One row per (customer_id, cutoff) for eligible customers. Columns: FEATURE_COLUMNS."""
    validate_events(events)
    first = _first_times(events)
    qual = events[events["event_name"].isin(QUALIFYING_EVENTS)]
    window = pd.Timedelta(days=window_days)
    frames = []

    for t in cutoffs:
        w = qual[(qual["event_timestamp"] >= t - window) & (qual["event_timestamp"] < t)]
        if w.empty:
            continue
        g = w.groupby("customer_id")
        day = w["event_timestamp"].dt.floor("D")
        recent = w["event_timestamp"] >= t - pd.Timedelta(days=14)

        out = pd.DataFrame(index=g.size().index)
        out["days_since_last_activity"] = (t - g["event_timestamp"].max()) / _DAY
        out["active_days_28d"] = day.groupby(w["customer_id"]).nunique()
        out["active_days_14d"] = day[recent].groupby(w.loc[recent, "customer_id"]).nunique()
        out["events_28d"] = g.size()
        by_name = w.groupby(["customer_id", "event_name"]).size().unstack(fill_value=0)
        for name, col in _CATEGORY_COLUMN.items():
            out[col] = by_name.get(name, 0)
        out["events_last_14d"] = recent.groupby(w["customer_id"]).sum()
        out["events_prev_14d"] = out["events_28d"] - out["events_last_14d"]
        total = out["events_last_14d"] + out["events_prev_14d"]
        out["activity_change"] = (out["events_last_14d"] - out["events_prev_14d"]) / total

        used = w[w["event_name"] == "feature_used"]
        names = used["properties"].map(lambda p: p.get("feature") if isinstance(p, dict) else None)
        out["distinct_features_28d"] = (
            pd.DataFrame({"c": used["customer_id"], "f": names})
            .dropna()
            .groupby("c")["f"]
            .nunique()
        )

        ft = first.reindex(out.index)
        out["onboarding_complete"] = (ft["onboarding_complete"] < t).astype(int)
        out["has_created_report"] = (ft["report_created"] < t).astype(int)
        out["account_age_days"] = (t - ft["signup"]) / _DAY
        out = out[ft["signup"].notna() & (ft["signup"] < t)]  # must have signed up before t
        out = out.fillna(0)
        out["cutoff"] = t
        frames.append(out)

    if not frames:
        empty = pd.DataFrame(columns=[*FEATURE_COLUMNS, "cutoff"])
        empty.index.name = "customer_id"
        return empty
    result = pd.concat(frames)
    result.index.name = "customer_id"
    result = result.reset_index().set_index(["customer_id", "cutoff"])
    return result[FEATURE_COLUMNS].astype(float)


def build_labels(
    events: pd.DataFrame, index: pd.MultiIndex, horizon_days: int = HORIZON_DAYS
) -> pd.Series:
    """churn = 1 if the customer has no qualifying event in ``[cutoff, cutoff + horizon)``."""
    validate_events(events)
    qual = events[events["event_name"].isin(QUALIFYING_EVENTS)]
    horizon = pd.Timedelta(days=horizon_days)
    labels = pd.Series(0, index=index, name="churn", dtype=int)
    for t in index.get_level_values("cutoff").unique():
        future = qual[(qual["event_timestamp"] >= t) & (qual["event_timestamp"] < t + horizon)]
        active_later = set(future["customer_id"])
        rows = index[index.get_level_values("cutoff") == t]
        labels.loc[rows] = [
            int(c not in active_later) for c in rows.get_level_values("customer_id")
        ]
    return labels


def make_cutoffs(
    first_event: pd.Timestamp,
    data_through: pd.Timestamp,
    horizon_days: int = HORIZON_DAYS,
    window_days: int = WINDOW_DAYS,
    step_days: int = 7,
) -> list[pd.Timestamp]:
    """Weekly midnight-UTC cutoffs whose label horizon is fully observed in the data.

    The first cutoff is one feature window after the first event; the last satisfies
    ``cutoff + horizon <= data_through`` so no label is built from an unfinished horizon.
    """
    start = first_event.floor("D") + pd.Timedelta(days=window_days)
    last = data_through - pd.Timedelta(days=horizon_days)
    n = int((last - start) // pd.Timedelta(days=step_days)) + 1 if last >= start else 0
    return [start + pd.Timedelta(days=step_days * i) for i in range(max(n, 0))]


def split_by_cutoff(
    cutoffs: list[pd.Timestamp], n_test: int, horizon_days: int = HORIZON_DAYS
) -> tuple[list[pd.Timestamp], list[pd.Timestamp], list[pd.Timestamp]]:
    """Time-based split: the last ``n_test`` cutoffs are test; train cutoffs end early enough that
    their label horizon closes by the first test cutoff. Returns (train, test, dropped_gap)."""
    ordered = sorted(cutoffs)
    if n_test < 1 or len(ordered) <= n_test:
        raise ValueError("not enough cutoffs for a train/test split")
    test = ordered[-n_test:]
    limit = test[0] - pd.Timedelta(days=horizon_days)
    train = [c for c in ordered[:-n_test] if c <= limit]
    gap = [c for c in ordered[:-n_test] if c > limit]
    if not train:
        raise ValueError("no train cutoffs left after the purge gap")
    return train, test, gap


def class_balance(y: pd.Series) -> float:
    return float(np.mean(y)) if len(y) else float("nan")
