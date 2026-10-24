"""Hand-checked examples for app.services.metrics (see docs/metrics.md)."""

import math

import pandas as pd
import pytest

from app.services import metrics

T = lambda s: pd.Timestamp(s, tz="UTC")

AS_OF = T("2026-02-02")

# A: full funnel, returns in weeks 1 and 3. B: onboards, no report. C: report before onboarding
# (out of order). D: signs up, never active. E: signs up too recently for the funnel window.
ROWS = [
    ("A", "signup", "2026-01-05"),
    ("A", "onboarding_complete", "2026-01-06"),
    ("A", "report_created", "2026-01-08"),
    ("A", "session_start", "2026-01-13"),
    ("A", "session_start", "2026-01-27"),
    ("B", "signup", "2026-01-06"),
    ("B", "onboarding_complete", "2026-01-07"),
    ("B", "session_start", "2026-01-07"),
    ("C", "signup", "2026-01-07"),
    ("C", "report_created", "2026-01-08"),
    ("C", "onboarding_complete", "2026-01-09"),
    ("D", "signup", "2026-01-12"),
    ("E", "signup", "2026-01-30"),
]


@pytest.fixture
def events() -> pd.DataFrame:
    return pd.DataFrame(ROWS, columns=["customer_id", "event_name", "event_timestamp"]).assign(
        event_timestamp=lambda d: pd.to_datetime(d["event_timestamp"], utc=True)
    )


def test_active_users_counts_distinct_qualifying_in_half_open_window(events):
    assert metrics.active_users(events, T("2026-01-07"), T("2026-01-09")) == 3  # B, A, C
    assert metrics.active_users(events, T("2026-01-09"), T("2026-01-12")) == 0
    # end is exclusive: the 01-08 events are excluded from [01-07, 01-08)
    assert metrics.active_users(events, T("2026-01-07"), T("2026-01-08")) == 1  # B only


def test_active_users_empty_range_is_zero(events):
    assert metrics.active_users(events, T("2030-01-01"), T("2030-02-01")) == 0


def test_funnel_ordering_window_and_censoring(events):
    f = metrics.funnel(events, AS_OF, window_days=14).set_index("step")
    assert f["eligible_users"].iloc[0] == 4  # A-D; E is censored
    assert f.loc["signup", "users"] == 4
    assert f.loc["onboarding_complete", "users"] == 3  # A, B, C
    assert f.loc["report_created", "users"] == 1  # A only; C's report precedes onboarding
    assert f.loc["onboarding_complete", "conversion_from_previous"] == pytest.approx(3 / 4)
    assert f.loc["report_created", "conversion_from_previous"] == pytest.approx(1 / 3)
    assert f.loc["report_created", "conversion_from_start"] == pytest.approx(1 / 4)


def test_funnel_step_outside_window_does_not_count(events):
    f = metrics.funnel(events, AS_OF, window_days=1).set_index("step")
    # window of 1 day: only signups with 1 day elapsed; onboarding on day 1 is within window
    assert f.loc["onboarding_complete", "users"] == 2  # A (day 1), B (day 1); C is day 2


def test_funnel_empty_has_nan_rates():
    empty = pd.DataFrame(
        {
            "customer_id": [],
            "event_name": [],
            "event_timestamp": pd.to_datetime([], utc=True),
        }
    )
    f = metrics.funnel(empty, AS_OF)
    assert (f["users"] == 0).all()
    assert math.isnan(f.loc[1, "conversion_from_previous"])


def test_retention_cells_and_incomplete_periods(events):
    r = metrics.cohort_retention(events, AS_OF, periods=4).set_index(["cohort", "period"])
    c1, c2, c3 = (
        T("2026-01-05").tz_localize(None),
        T("2026-01-12").tz_localize(None),
        T("2026-01-26").tz_localize(None),
    )

    assert r.loc[(c1, 0), "cohort_size"] == 3
    assert r.loc[(c1, 0), "retention"] == pytest.approx(1.0)  # A, B, C all active in week 0
    assert r.loc[(c2, 0), "retention"] == 0.0  # D eligible, never active
    assert math.isnan(r.loc[(c3, 0), "retention"])  # E: period 0 not yet complete

    assert r.loc[(c1, 1), "retained"] == 1  # only A
    assert r.loc[(c1, 1), "retention"] == pytest.approx(1 / 3)

    # period 3: only A's 4th week is complete by AS_OF, B and C drop out of the denominator
    assert r.loc[(c1, 3), "eligible"] == 1
    assert r.loc[(c1, 3), "retention"] == pytest.approx(1.0)


def test_rejects_naive_timestamps(events):
    naive = events.assign(event_timestamp=events["event_timestamp"].dt.tz_localize(None))
    with pytest.raises(ValueError, match="timezone-aware"):
        metrics.active_users(naive, T("2026-01-01"), T("2026-02-01"))


def test_week_boundary_uses_utc_monday():
    ev = pd.DataFrame(
        [
            ("X", "signup", "2026-01-11T23:59:00Z"),  # Sunday -> cohort 2026-01-05
            ("Y", "signup", "2026-01-12T00:00:00Z"),  # Monday -> cohort 2026-01-12
        ],
        columns=["customer_id", "event_name", "event_timestamp"],
    ).assign(event_timestamp=lambda d: pd.to_datetime(d["event_timestamp"], utc=True))
    r = metrics.cohort_retention(ev, AS_OF, periods=1)
    assert sorted(r["cohort"].dt.strftime("%Y-%m-%d")) == ["2026-01-05", "2026-01-12"]


def test_new_and_returning_users(events):
    # window [01-12, 01-20): D signs up in it (new); active in it: A (session 01-13) only
    assert metrics.new_users(events, T("2026-01-12"), T("2026-01-20")) == 1
    assert metrics.returning_users(events, T("2026-01-12"), T("2026-01-20")) == 1  # A
    # window [01-05, 01-20): everyone active signed up inside it -> none returning
    assert metrics.returning_users(events, T("2026-01-05"), T("2026-01-20")) == 0


def test_daily_active_users_zero_filled(events):
    s = metrics.daily_active_users(events, T("2026-01-07"), T("2026-01-10"))
    assert list(s.values) == [1, 2, 0]  # 07: B; 08: A, C; 09: none
    assert len(s) == 3


def test_engagement_hand_checked():
    rows = [
        ("A", "signup", "2026-01-01T00:00:00Z", {}),
        ("A", "session_start", "2026-01-02T00:00:00Z", {}),
        ("A", "feature_used", "2026-01-02T06:00:00Z", {"feature": "exports"}),
        ("A", "feature_used", "2026-01-04T00:00:00Z", {"feature": "exports"}),
        ("B", "feature_used", "2026-01-03T00:00:00Z", {"feature": "alerts"}),
        ("C", "onboarding_complete", "2026-01-03T00:00:00Z", {}),  # not qualifying
    ]
    ev = pd.DataFrame(rows, columns=["customer_id", "event_name", "event_timestamp", "properties"])
    ev["event_timestamp"] = pd.to_datetime(ev["event_timestamp"], utc=True)
    e = metrics.engagement(ev, T("2026-01-01"), T("2026-01-10"))
    assert e["active_users"] == 2  # A, B (C's only event does not qualify)
    assert e["active_days_per_user_mean"] == pytest.approx(1.5)  # A: 01-02, 01-04 = 2; B: 1
    assert e["events_per_active_user"] == pytest.approx(2.0)  # 4 events / 2 users
    # gaps: A 6h and 42h; B none -> median of [6, 42] = 24
    assert e["median_hours_between_activities"] == pytest.approx(24.0)
    assert e["feature_adoption"] == {"exports": 0.5, "alerts": 0.5}


def test_engagement_empty_window_is_all_none(events):
    e = metrics.engagement(events, T("2030-01-01"), T("2030-02-01"))
    assert e["active_users"] == 0 and e["events_per_active_user"] is None
    assert e["feature_adoption"] == {}
