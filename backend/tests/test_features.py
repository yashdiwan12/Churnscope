"""Hand-checked churn features/labels and leakage guards (see docs/model_card.md).

Cutoff t = 2026-02-01. Feature window [01-04, 02-01), last-14-days part [01-18, 02-01).
"""

import pandas as pd
import pytest

from app.services import features as f

T = pd.Timestamp("2026-02-01", tz="UTC")


def ev(rows):
    df = pd.DataFrame(rows, columns=["customer_id", "event_name", "event_timestamp", "properties"])
    df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], utc=True, format="ISO8601")
    return df


A_FEATURES = {"feature": "exports"}
ROWS = [
    # A: eligible, busy, onboarded, has created a report
    ("A", "signup", "2025-12-20", {}),
    ("A", "onboarding_complete", "2025-12-21", {}),
    ("A", "report_created", "2026-01-10", {}),
    ("A", "session_start", "2026-01-05", {}),
    ("A", "session_start", "2026-01-20", {}),
    ("A", "feature_used", "2026-01-25", {"feature": "exports"}),
    ("A", "feature_used", "2026-01-26", {"feature": "alerts"}),
    ("A", "report_shared", "2026-01-31T12:00:00", {}),
    ("A", "session_start", "2026-02-05", {}),  # future: label only
    # B: signed up, only non-qualifying events in the window -> not eligible
    ("B", "signup", "2026-01-30", {}),
    ("B", "onboarding_complete", "2026-01-31", {}),
    # C: one old session, then silence
    ("C", "signup", "2026-01-10", {}),
    ("C", "session_start", "2026-01-12", {}),
    # E: active but no signup on record -> account age unknown -> excluded
    ("E", "session_start", "2026-01-20", {}),
    # F: event exactly at the cutoff belongs to the label, not the features
    ("F", "signup", "2026-01-01", {}),
    ("F", "session_start", "2026-01-15", {}),
    ("F", "session_start", "2026-02-01", {}),
    # G: event exactly at window start is included
    ("G", "signup", "2025-12-01", {}),
    ("G", "session_start", "2026-01-04", {}),
    # H: event one second before the window start is excluded -> not eligible
    ("H", "signup", "2025-12-01", {}),
    ("H", "session_start", "2026-01-03T23:59:59", {}),
]


@pytest.fixture
def events():
    return ev(ROWS)


def test_features_hand_checked_customer_a(events):
    x = f.build_features(events, [T]).loc[("A", T)]
    assert x["events_28d"] == 6  # report_created, 2 sessions, 2 feature_used, report_shared
    assert x["active_days_28d"] == 6
    assert x["active_days_14d"] == 4  # 01-20, 01-25, 01-26, 01-31
    assert (x["sessions_28d"], x["features_used_28d"]) == (2, 2)
    assert (x["reports_created_28d"], x["reports_shared_28d"]) == (1, 1)
    assert (x["events_last_14d"], x["events_prev_14d"]) == (4, 2)
    assert x["activity_change"] == pytest.approx((4 - 2) / 6)
    assert x["distinct_features_28d"] == 2
    assert x["days_since_last_activity"] == pytest.approx(0.5)
    assert (x["onboarding_complete"], x["has_created_report"]) == (1, 1)
    assert x["account_age_days"] == pytest.approx(43)  # 2025-12-20 -> 2026-02-01


def test_features_hand_checked_customer_c(events):
    x = f.build_features(events, [T]).loc[("C", T)]
    assert x["events_28d"] == 1 and x["active_days_14d"] == 0
    assert (x["events_last_14d"], x["events_prev_14d"]) == (0, 1)
    assert x["activity_change"] == pytest.approx(-1.0)
    assert x["days_since_last_activity"] == pytest.approx(20)
    assert (x["onboarding_complete"], x["has_created_report"]) == (0, 0)
    assert x["account_age_days"] == pytest.approx(22)


def test_eligibility_rules(events):
    ids = set(f.build_features(events, [T]).index.get_level_values("customer_id"))
    assert ids == {"A", "C", "F", "G"}  # B inactive, E no signup, H outside window


def test_window_boundaries_are_half_open(events):
    x = f.build_features(events, [T])
    assert x.loc[("F", T), "events_28d"] == 1  # the event at t is not a feature
    assert x.loc[("G", T), "events_28d"] == 1  # the event at t-28d is
    assert x.loc[("G", T), "days_since_last_activity"] == pytest.approx(28)


def test_labels_use_only_the_horizon(events):
    x = f.build_features(events, [T])
    y = f.build_labels(events, x.index)
    assert y.loc[("A", T)] == 0  # session 02-05
    assert y.loc[("C", T)] == 1  # silent
    assert y.loc[("F", T)] == 0  # event exactly at the cutoff counts for the label
    assert y.loc[("G", T)] == 1


def test_label_horizon_is_14_days_exclusive():
    base = [("X", "signup", "2026-01-01", {}), ("X", "session_start", "2026-01-30", {})]
    inside = ev([*base, ("X", "session_start", "2026-02-14T23:59:59", {})])
    edge = ev([*base, ("X", "session_start", "2026-02-15", {})])  # t + 14d: outside
    for events, expected in ((inside, 0), (edge, 1)):
        x = f.build_features(events, [T])
        assert f.build_labels(events, x.index).loc[("X", T)] == expected


def test_future_events_never_change_features(events):
    """Leakage guard: features at t from the full history == features from events before t."""
    before = events[events["event_timestamp"] < T]
    noisy = pd.concat(
        [
            events,
            ev(
                [
                    ("A", "session_start", "2026-02-02", {}),
                    ("C", "report_created", "2026-03-01", {}),
                ]
            ),
        ]
    )
    pd.testing.assert_frame_equal(f.build_features(before, [T]), f.build_features(noisy, [T]))


def test_feature_columns_are_stable_and_complete(events):
    x = f.build_features(events, [T])
    assert list(x.columns) == f.FEATURE_COLUMNS
    assert not x.isna().any().any()


def test_empty_inputs_give_empty_frames(events):
    assert f.build_features(events, []).empty
    assert f.build_features(events, [pd.Timestamp("2020-01-01", tz="UTC")]).empty


def test_cutoffs_have_observed_horizons_and_are_weekly():
    first = pd.Timestamp("2026-01-01T10:00", tz="UTC")
    through = pd.Timestamp("2026-04-01", tz="UTC")
    cuts = f.make_cutoffs(first, through)
    assert [c.strftime("%m-%d") for c in cuts] == [
        "01-29", "02-05", "02-12", "02-19", "02-26", "03-05", "03-12",
    ]  # fmt: skip
    assert all(c + pd.Timedelta(days=14) <= through for c in cuts)
    assert f.make_cutoffs(first, pd.Timestamp("2026-01-10", tz="UTC")) == []


def test_time_split_purges_the_gap():
    first = pd.Timestamp("2026-01-01", tz="UTC")
    cuts = f.make_cutoffs(first, pd.Timestamp("2026-04-01", tz="UTC"))
    train, test, gap = f.split_by_cutoff(cuts, n_test=2)
    assert [c.strftime("%m-%d") for c in test] == ["03-05", "03-12"]
    assert [c.strftime("%m-%d") for c in gap] == ["02-26"]
    assert max(train) + pd.Timedelta(days=14) <= min(test)  # train labels are known at test time
    assert set(train).isdisjoint(test)


def test_split_rejects_too_few_cutoffs():
    cuts = f.make_cutoffs(
        pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-02-20", tz="UTC")
    )
    with pytest.raises(ValueError):
        f.split_by_cutoff(cuts, n_test=len(cuts))
