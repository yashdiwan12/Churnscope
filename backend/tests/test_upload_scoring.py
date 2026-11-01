"""Per-upload churn scoring (spec 5a): learned and backtested on the file's own history. Pure."""

import json
import os
import time

import numpy as np
import pandas as pd
import pytest

from app.ml import train
from app.services import features, upload_scoring
from app.services.upload_scoring import (
    MARGIN,
    MIN_PER_CLASS,
    MIN_TEST_ROWS,
    fit,
    json_proba,
)

DAY = pd.Timedelta(days=1)
D0 = pd.Timestamp("2026-01-05", tz="UTC")  # first event of every fixture
NOW = pd.Timestamp("2026-11-01T09:00:00", tz="UTC")


def frame(rows: list[tuple]) -> pd.DataFrame:
    """Events from (customer, event_name, timestamp[, properties]) tuples."""
    df = pd.DataFrame(
        {
            "customer_id": [r[0] for r in rows],
            "event_name": [r[1] for r in rows],
            "event_timestamp": pd.to_datetime([r[2] for r in rows], utc=True),
            "properties": [r[3] if len(r) > 3 else {} for r in rows],
        }
    )
    return df.sort_values("event_timestamp", kind="stable").reset_index(drop=True)


def daily(cid: str, start: pd.Timestamp, end: pd.Timestamp, name="session_start") -> list:
    """One event at noon on each day from ``start`` (a midnight) up to and excluding ``end``."""
    days = pd.date_range(start, end - DAY, freq="D")
    return [(cid, name, d + pd.Timedelta(hours=12)) for d in days]


def cutoff(k: int) -> pd.Timestamp:
    """The k-th weekly cutoff of a fixture whose first event is at D0."""
    return D0 + (features.WINDOW_DAYS + 7 * k) * DAY


# ----------------------------------------------------------------------------- fixtures
def recency_file(actives=200, churners_per_week=15, weeks=9, seed=1) -> pd.DataFrame:
    """Churners sign up just after a cutoff, use the product briefly and go quiet before the next
    one, so at every cutoff where they are scored they have already been silent for days. Actives
    use the product daily to the end of the file. Days since last activity separates them."""
    rng = np.random.default_rng(seed)
    end = cutoff(weeks) + 15 * DAY
    rows: list = []
    for i in range(actives):
        cid = f"a{i}"
        rows += [(cid, "signup", D0)] + daily(cid, D0, end)
    n = 0
    for k in range(-3, weeks):
        for _ in range(churners_per_week):
            cid = f"c{n}"
            n += 1
            start = cutoff(k) + DAY
            rows.append((cid, "signup", start))
            for d in range(int(rng.integers(1, 4))):
                rows.append((cid, "session_start", start + d * DAY + pd.Timedelta(hours=10)))
    return frame(rows)


def report_file(sharers=150, quiet=150, weeks=8) -> pd.DataFrame:
    """Every customer is active daily up to each cutoff. Sharers share a report weekly and never
    stop. The others never share; they repeat a 21-day cycle aligned with the cutoffs: silent for
    the 14 days after a cutoff, then active daily for 7. So at the cutoff where a silence starts,
    they look as fresh as everyone else (the rule cannot rank them) yet churn; one and two weeks
    into the silence they look quiet but come back. Churn follows "no report_shared", not recency.
    """
    end = cutoff(weeks) + 15 * DAY
    rows: list = []
    for i in range(sharers):
        cid = f"s{i}"
        rows += [(cid, "signup", D0)] + daily(cid, D0, end)
        rows += [
            (cid, "report_shared", d + pd.Timedelta(hours=13))
            for d in pd.date_range(D0 + (i % 7) * DAY, end - DAY, freq="7D")
        ]
    for i in range(quiet):
        cid = f"q{i}"
        rows.append((cid, "signup", D0))
        phase = i % 3
        day = D0
        while day < end:
            k = round((day - cutoff(0)) / (7 * DAY))
            on_grid = day == cutoff(0) + k * 7 * DAY
            if on_grid and (k - phase) % 3 == 0:
                day += 14 * DAY  # silent for the two weeks after this cutoff
                continue
            rows.append((cid, "session_start", day + pd.Timedelta(hours=12)))
            day += DAY
    return frame(rows)


def floors_file(actives=10, test_new=160, test_churners=20, train_churners=20) -> pd.DataFrame:
    """Exactly four cutoffs: c0 trains, c1 is the purge gap, c2 and c3 test. Counts by design:

    * actives (signup D0, daily to the end): a non-churner row at c0, c2 and c3;
    * test_new (signup just before c3, then daily): one non-churner test row at c3;
    * test_churners (one session 3 days before c3): one churner test row at c3;
    * train_churners (one session 20 days before c0): a churner row at c0 (and c1, the gap).

    So test rows = 2*actives + test_new + test_churners; test non-churners = 2*actives + test_new.
    """
    c0, c3 = cutoff(0), cutoff(3)
    end = c3 + 15 * DAY  # a fourth cutoff (c3 + 7) would need end >= c3 + 21
    rows: list = [("anchor", "signup", D0), ("anchor_end", "signup", end)]
    for i in range(actives):
        rows += [(f"a{i}", "signup", D0)] + daily(f"a{i}", D0, end)
    for i in range(test_new):
        rows += [(f"n{i}", "signup", c3 - 4 * DAY)] + daily(f"n{i}", c3 - 3 * DAY, end)
    for i in range(test_churners):
        rows += [(f"t{i}", "signup", c3 - 4 * DAY), (f"t{i}", "session_start", c3 - 3 * DAY)]
    for i in range(train_churners):
        rows += [(f"r{i}", "signup", D0), (f"r{i}", "session_start", c0 - 20 * DAY)]
    return frame(rows)


# ----------------------------------------------------------------------------- tests
def test_recency_file_ranks_quiet_customers_first():
    out = fit(recency_file(), NOW)
    assert out["method"] in ("logistic", "inactive_rule")
    assert out["reason"] is None
    bt = out["backtest"]
    assert bt["model"]["pr_auc"] >= 0.9
    assert bt["rule"]["pr_auc"] >= 0.9
    assert bt["test_rows"] >= MIN_TEST_ROWS
    assert out["fitted_at"] == NOW.isoformat()


def test_model_wins_when_churn_is_not_recency():
    out = fit(report_file(), NOW)
    bt = out["backtest"]
    assert out["method"] == "logistic"
    assert bt["model"]["pr_auc"] > bt["rule"]["pr_auc"] + MARGIN
    assert out["model"]["features"] == features.FEATURE_COLUMNS


def _patch_metrics(monkeypatch, model_pr: float, rule_pr: float) -> None:
    def model_metrics(y, proba, threshold=0.5):
        return {"pr_auc": model_pr, "roc_auc": 0.8, "precision": 0.5, "recall": 0.5}

    def rule_metrics(y_train, y_test, x_test, inactive_days=7.0):
        rule = {"pr_auc": rule_pr, "roc_auc": 0.8, "precision": 0.5, "recall": 0.5}
        return {"majority_class": {}, "inactive_rule": rule}

    monkeypatch.setattr(upload_scoring.evaluate, "classification_metrics", model_metrics)
    monkeypatch.setattr(upload_scoring.evaluate, "baseline_metrics", rule_metrics)


def test_tie_goes_to_rule(monkeypatch):
    _patch_metrics(monkeypatch, model_pr=0.819, rule_pr=0.8)  # model - rule = 0.019
    out = fit(recency_file(), NOW)
    assert out["method"] == "inactive_rule"
    assert out["backtest"]["model"]["pr_auc"] == 0.819
    assert out["backtest"]["rule"]["pr_auc"] == 0.8


def test_model_needs_the_full_margin(monkeypatch):
    _patch_metrics(monkeypatch, model_pr=0.821, rule_pr=0.8)
    assert fit(recency_file(), NOW)["method"] == "logistic"


def test_no_training_label_inside_test_period():
    for events in (recency_file(), report_file(), floors_file()):
        bt = fit(events, NOW)["backtest"]
        train_c = [pd.Timestamp(c) for c in bt["train_cutoffs"]]
        test_c = [pd.Timestamp(c) for c in bt["test_cutoffs"]]
        assert len(test_c) == upload_scoring.N_TEST
        assert max(train_c) + features.HORIZON_DAYS * DAY <= min(test_c)


def test_floor_fixture_counts_are_as_designed():
    bt = fit(floors_file(), NOW)["backtest"]
    assert (bt["test_rows"], bt["test_churners"], bt["train_churners"]) == (200, 20, 20)


@pytest.mark.parametrize(
    ("at_limit", "below", "reason"),
    [
        ({"test_new": 160}, {"test_new": 159}, "too_few_test_rows"),
        ({"test_new": 200}, {"test_new": 200, "test_churners": 19}, "too_few_test_churners"),
        (
            {"actives": 10, "test_new": 0, "test_churners": 180},
            {"actives": 9, "test_new": 1, "test_churners": 181},
            "too_few_test_non_churners",
        ),
        ({"test_new": 200}, {"test_new": 200, "train_churners": 19}, "too_few_train_churners"),
    ],
)
def test_floors(at_limit, below, reason):
    ok = fit(floors_file(**at_limit), NOW)
    assert ok["method"] in ("logistic", "inactive_rule"), ok["reason"]
    bt = ok["backtest"]
    assert bt["test_rows"] >= MIN_TEST_ROWS
    assert min(bt["test_churners"], bt["train_churners"]) >= MIN_PER_CLASS
    assert bt["test_rows"] - bt["test_churners"] >= MIN_PER_CLASS

    short = fit(floors_file(**below), NOW)
    assert short["method"] == "rule_unchecked"
    assert short["reason"] == reason
    assert short["model"] is None and short["backtest"] is None


def _history(days: int) -> pd.DataFrame:
    rows = [("a", "signup", D0)]
    rows += [("a", "session_start", D0 + d * DAY) for d in range(1, days + 1)]
    return frame(rows)


def test_short_history():
    short = fit(_history(27), NOW)
    assert short["method"] == "unavailable"
    assert short["reason"] == "short_history"
    assert short["history_days"] == 27.0
    assert short["model"] is None and short["backtest"] is None
    enough = fit(_history(28), NOW)
    assert enough["method"] == "rule_unchecked"
    assert enough["reason"] == "not_enough_history_for_test"
    assert enough["history_days"] == 28.0


def test_empty_file_is_unavailable():
    out = fit(frame([]), NOW)
    assert out["method"] == "unavailable"
    assert out["history_days"] == 0.0


def _leaves(value):
    if isinstance(value, dict):
        assert all(isinstance(k, str) for k in value)
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v)
    else:
        yield value


def test_json_model_matches_sklearn(monkeypatch):
    fitted = []
    real = train.make_logistic

    def capture(seed):
        pipe = real(seed)
        fitted.append(pipe)
        return pipe

    monkeypatch.setattr(upload_scoring.train, "make_logistic", capture)
    events = report_file()
    out = fit(events, NOW)
    assert len(fitted) == 1
    x = features.build_features(events, [cutoff(4), cutoff(6)])
    diff = np.abs(json_proba(out["model"], x) - fitted[0].predict_proba(x)[:, 1])
    assert diff.max() < 1e-9

    stored = json.loads(json.dumps(out))
    assert stored == out
    for leaf in _leaves(stored):
        assert leaf is None or isinstance(leaf, (str, int, float)), type(leaf)
    assert set(out["model"]) == {"features", "mean", "scale", "coef", "intercept", "threshold"}


def test_json_proba_uses_feature_names_not_column_order():
    events = report_file()
    model = fit(events, NOW)["model"]
    x = features.build_features(events, [cutoff(5)])
    shuffled = x[list(reversed(x.columns))]
    assert np.allclose(json_proba(model, x), json_proba(model, shuffled))


def test_single_customer_and_identical_rows_do_not_crash():
    one = frame([("a", "signup", D0)] + daily("a", D0, D0 + 120 * DAY))
    assert fit(one, NOW)["method"] == "rule_unchecked"

    same: list = []
    for i in range(300):
        same += [(f"c{i}", "signup", D0)] + daily(f"c{i}", D0, D0 + 120 * DAY)
    out = fit(frame(same), NOW)  # identical feature rows, nobody churns
    assert out["method"] == "rule_unchecked"
    assert out["reason"] == "too_few_test_churners"

    zero_variance = fit(floors_file(test_new=200), NOW)  # constant columns are scaled safely
    assert all(np.isfinite(zero_variance["model"]["scale"]))


def _big_file(customers=10_000, events=50_000, days=180, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    first = rng.integers(0, days - 30, customers)
    rows: list = []
    per = (events - customers) // customers
    for i in range(customers):
        cid = f"u{i}"
        start = D0 + int(first[i]) * DAY
        rows.append((cid, "signup", start))
        life = int(rng.integers(5, days - first[i]))
        offsets = np.sort(rng.uniform(0, life, per))
        names = rng.choice(["session_start", "feature_used", "report_created"], per)
        rows += [
            (cid, str(n), start + pd.Timedelta(days=float(o)))
            for n, o in zip(names, offsets, strict=True)
        ]
    return frame(rows)


@pytest.mark.skipif(
    not os.environ.get("CHURNSCOPE_TIMING"), reason="timing check; set CHURNSCOPE_TIMING=1"
)
def test_fit_time_on_largest_upload():
    events = _big_file()
    assert len(events) == 50_000 and events["customer_id"].nunique() == 10_000
    start = time.perf_counter()
    out = fit(events, NOW)
    seconds = time.perf_counter() - start
    print(f"fit on 50,000 events / 10,000 customers: {seconds:.2f} s, method {out['method']}")
    assert seconds < 20
