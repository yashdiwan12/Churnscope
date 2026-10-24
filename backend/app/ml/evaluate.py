"""Evaluation helpers: metrics, naive baselines, and error profiling. No fitting happens here."""

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def _safe(fn, *args, **kwargs):
    """Metric as a float, or None when undefined (e.g. only one class present in y_true)."""
    try:
        value = float(fn(*args, **kwargs))
    except ValueError:
        return None
    return None if np.isnan(value) else value


def classification_metrics(y_true, proba, threshold: float = 0.5) -> dict:
    y_true = np.asarray(y_true)
    proba = np.asarray(proba)
    pred = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "n": len(y_true),
        "positives": int(y_true.sum()),
        "base_rate": float(y_true.mean()) if len(y_true) else None,
        "threshold": threshold,
        "accuracy": float((pred == y_true).mean()) if len(y_true) else None,
        "precision": _safe(precision_score, y_true, pred, zero_division=0),
        "recall": _safe(recall_score, y_true, pred, zero_division=0),
        "f1": _safe(f1_score, y_true, pred, zero_division=0),
        "roc_auc": _safe(roc_auc_score, y_true, proba),
        "pr_auc": _safe(average_precision_score, y_true, proba),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def baseline_metrics(y_train, y_test, x_test: pd.DataFrame, inactive_days: float = 7.0) -> dict:
    """Naive reference points the model must beat.

    * majority_class: always predict the most common training class
    * inactive_rule: predict churn if the customer's last activity was >= ``inactive_days`` ago
      (scored by days_since_last_activity for the ranking metrics)
    """
    majority = int(np.mean(y_train) >= 0.5)
    out = {
        "majority_class": classification_metrics(y_test, np.full(len(y_test), float(majority))),
    }
    days = x_test["days_since_last_activity"].to_numpy()
    rule = classification_metrics(y_test, (days >= inactive_days).astype(float), threshold=0.5)
    rule["roc_auc"] = _safe(roc_auc_score, np.asarray(y_test), days)
    rule["pr_auc"] = _safe(average_precision_score, np.asarray(y_test), days)
    rule["rule"] = f"days_since_last_activity >= {inactive_days:g}"
    out["inactive_rule"] = rule
    return out


def error_profile(x_test: pd.DataFrame, y_true, proba, threshold: float = 0.5) -> dict:
    """Mean feature values by outcome group, to see what false positives/negatives look like."""
    y_true = np.asarray(y_true)
    pred = (np.asarray(proba) >= threshold).astype(int)
    groups = {
        "true_positive": (y_true == 1) & (pred == 1),
        "false_positive": (y_true == 0) & (pred == 1),
        "false_negative": (y_true == 1) & (pred == 0),
        "true_negative": (y_true == 0) & (pred == 0),
    }
    profile = {}
    for name, mask in groups.items():
        profile[name] = {
            "n": int(mask.sum()),
            "feature_means": (
                {k: round(float(v), 3) for k, v in x_test[mask].mean().items()}
                if mask.any()
                else {}
            ),
        }
    return profile
