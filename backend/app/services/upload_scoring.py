"""Churn scoring for an upload, learned and backtested on the file's own history (spec 5a).

``fit`` builds weekly cutoffs over the file, holds out the latest ``N_TEST`` of them (with a purge
gap so no training label overlaps the test period), fits the logistic pipeline on the earlier
ones and compares it with the days-since-last-activity rule on the held-out rows. The model is
used only when its PR-AUC beats the rule's by at least ``MARGIN``; otherwise the rule is used.
Too little data for a fair test falls back to the unchecked rule, or to nothing at all.

The result is plain JSON stored on the dataset row. The fitted model is kept as numbers (scaler
means and scales, coefficients, intercept) and applied by ``json_proba``, a dot product, so
loading it can never run code. Pure: no database access.
"""

import numpy as np
import pandas as pd

from app.ml import evaluate, train
from app.services import features

MAX_CUTOFFS = 26
N_TEST = 2
MARGIN = 0.02
MIN_TEST_ROWS = 200
MIN_PER_CLASS = 20
RULE_DAYS = 7.0
SEED = 42

THRESHOLD = 0.5  # the logistic model's decision threshold (balanced classes)
CHECKED = ("logistic", "inactive_rule")
SCOREABLE = (*CHECKED, "rule_unchecked")
FAILED = {"method": "failed", "reason": "scoring_failed"}

_DAY = pd.Timedelta(days=1)
_METRICS = ("pr_auc", "roc_auc", "precision", "recall")


def _result(method: str, reason: str | None, now: pd.Timestamp, history_days: float) -> dict:
    return {
        "method": method,
        "reason": reason,
        "fitted_at": now.isoformat(),
        "history_days": history_days,
        "model": None,
        "backtest": None,
    }


def _json_model(pipe) -> dict:
    scale, clf = pipe.named_steps["scale"], pipe.named_steps["clf"]
    return {
        "features": list(features.FEATURE_COLUMNS),
        "mean": [float(v) for v in scale.mean_],
        "scale": [float(v) for v in scale.scale_],
        "coef": [float(v) for v in clf.coef_[0]],
        "intercept": float(clf.intercept_[0]),
        "threshold": THRESHOLD,
    }


def json_proba(model: dict, x: pd.DataFrame) -> np.ndarray:
    """Churn probability from a stored model: standardise, dot product, logistic function."""
    names = list(model["features"])
    mean, scale, coef = (np.asarray(model[k], dtype=float) for k in ("mean", "scale", "coef"))
    if not len(names) == len(mean) == len(scale) == len(coef):
        raise ValueError("stored model is malformed")
    z = (x[names].to_numpy(dtype=float) - mean) / scale
    logit = z @ coef + float(model["intercept"])
    return np.exp(-np.logaddexp(0.0, -logit))  # 1 / (1 + e^-logit) without overflow


def _metrics(source: dict) -> dict:
    return {k: (None if source.get(k) is None else float(source[k])) for k in _METRICS}


def _floor_failure(y_train: pd.Series, y_test: pd.Series) -> str | None:
    """The first floor not met, in the spec's order; None when every floor holds."""
    test_churners = int(y_test.sum())
    train_churners = int(y_train.sum())
    if len(y_test) < MIN_TEST_ROWS:
        return "too_few_test_rows"
    if test_churners < MIN_PER_CLASS:
        return "too_few_test_churners"
    if len(y_test) - test_churners < MIN_PER_CLASS:
        return "too_few_test_non_churners"
    if train_churners < MIN_PER_CLASS:
        return "too_few_train_churners"
    if len(y_train) - train_churners < 1:  # a fit needs both classes
        return "too_few_train_non_churners"
    return None


def fit(events: pd.DataFrame, now: pd.Timestamp) -> dict:
    """The ``scoring`` JSON for an upload's events. ``now`` is recorded as ``fitted_at``."""
    if events.empty:
        return _result("unavailable", "short_history", now, 0.0)
    first, through = events["event_timestamp"].min(), events["event_timestamp"].max()
    history_days = round(float((through - first) / _DAY), 1)
    if through - first < features.WINDOW_DAYS * _DAY:
        return _result("unavailable", "short_history", now, history_days)

    cutoffs = features.make_cutoffs(first, through)[-MAX_CUTOFFS:]
    try:
        train_c, test_c, _gap = features.split_by_cutoff(cutoffs, N_TEST)
    except ValueError:
        return _result("rule_unchecked", "not_enough_history_for_test", now, history_days)

    x = features.build_features(events, [*train_c, *test_c])
    y = features.build_labels(events, x.index)
    level = x.index.get_level_values("cutoff")
    in_train, in_test = level.isin(train_c), level.isin(test_c)
    x_train, y_train, x_test, y_test = x[in_train], y[in_train], x[in_test], y[in_test]
    reason = _floor_failure(y_train, y_test)
    if reason is not None:
        return _result("rule_unchecked", reason, now, history_days)

    pipe = train.make_logistic(SEED).fit(x_train[features.FEATURE_COLUMNS], y_train)
    model = _json_model(pipe)
    proba = json_proba(model, x_test)
    model_m = evaluate.classification_metrics(y_test, proba, THRESHOLD)
    rule_m = evaluate.baseline_metrics(y_train, y_test, x_test, inactive_days=RULE_DAYS)[
        "inactive_rule"
    ]
    model_pr, rule_pr = model_m.get("pr_auc"), rule_m.get("pr_auc")
    wins = model_pr is not None and rule_pr is not None and model_pr - rule_pr >= MARGIN - 1e-12
    out = _result("logistic" if wins else "inactive_rule", None, now, history_days)
    out["model"] = model
    out["backtest"] = {
        "train_rows": len(y_train),
        "train_churners": int(y_train.sum()),
        "test_rows": len(y_test),
        "test_churners": int(y_test.sum()),
        "train_cutoffs": [c.isoformat() for c in train_c],
        "test_cutoffs": [c.isoformat() for c in test_c],
        "model": _metrics(model_m),
        "rule": _metrics(rule_m),
    }
    return out
