"""Offline training of the churn model. Never runs in the request path.

Usage (from backend/):
    PYTHONPATH=. uv run python -m app.ml.train --source db           # events from DATABASE_URL
    PYTHONPATH=. uv run python -m app.ml.train --source csv --csv-dir ../data/processed

Logistic Regression is the model that ships (interpretable baseline, decided up front). Random
Forest and two naive baselines are evaluated on the same untouched test cutoffs for comparison;
nothing is tuned or selected on the test set.
"""

import argparse
import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml import artifact, evaluate
from app.services import features
from app.services.metrics import QUALIFYING_EVENTS

REPORT_PATH = Path(__file__).parent / "reports" / "churn_eval.json"
DECISION_THRESHOLD = 0.5


@dataclass
class Dataset:
    x_train: pd.DataFrame
    y_train: pd.Series
    x_test: pd.DataFrame
    y_test: pd.Series
    train_cutoffs: list[pd.Timestamp]
    test_cutoffs: list[pd.Timestamp]
    gap_cutoffs: list[pd.Timestamp]


@dataclass
class TrainResult:
    pipeline: Pipeline
    metadata: dict
    report: dict


def data_fingerprint(events: pd.DataFrame) -> dict:
    """Order-independent summary identifying the training data.

    Covers every column the features read, including ``properties``. Customer ids are hashed as
    given, so the same events loaded from the database (internal ids) and from CSV (external ids)
    have different fingerprints.
    """
    cols = ["customer_id", "event_name", "event_timestamp", "properties"]
    ordered = (
        events[cols]
        .assign(
            customer_id=events["customer_id"].astype(str),
            properties=events["properties"].map(lambda p: json.dumps(p, sort_keys=True)),
        )
        .sort_values(cols)
        .reset_index(drop=True)
    )
    digest = hashlib.sha256(pd.util.hash_pandas_object(ordered, index=False).values.tobytes())
    return {
        "n_events": len(events),
        "n_customers": int(events["customer_id"].nunique()),
        "first_event": events["event_timestamp"].min().isoformat(),
        "last_event": events["event_timestamp"].max().isoformat(),
        "sha256": digest.hexdigest(),
    }


def build_dataset(events: pd.DataFrame, n_test: int = 4) -> Dataset:
    cutoffs = features.make_cutoffs(
        events["event_timestamp"].min(), events["event_timestamp"].max()
    )
    train_c, test_c, gap_c = features.split_by_cutoff(cutoffs, n_test)
    x = features.build_features(events, [*train_c, *test_c])
    y = features.build_labels(events, x.index)
    level = x.index.get_level_values("cutoff")
    tr, te = level.isin(train_c), level.isin(test_c)
    return Dataset(x[tr], y[tr], x[te], y[te], train_c, test_c, gap_c)


def make_logistic(seed: int) -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),  # fitted on training rows only, inside the pipeline
            (
                "clf",
                LogisticRegression(class_weight="balanced", max_iter=1000, random_state=seed),
            ),
        ]
    )


def make_forest(seed: int) -> Pipeline:
    return Pipeline(
        [
            (
                "clf",
                RandomForestClassifier(
                    n_estimators=200,
                    min_samples_leaf=5,
                    class_weight="balanced_subsample",
                    random_state=seed,
                    n_jobs=-1,
                ),
            )
        ]
    )


def _iso(ts: list[pd.Timestamp]) -> list[str]:
    return [t.strftime("%Y-%m-%d") for t in ts]


def train(events: pd.DataFrame, seed: int = 42, n_test: int = 4) -> TrainResult:
    ds = build_dataset(events, n_test)
    fingerprint = data_fingerprint(events)

    models = {"logistic_regression": make_logistic(seed), "random_forest": make_forest(seed)}
    report_models, probas = {}, {}
    for name, pipe in models.items():
        pipe.fit(ds.x_train, ds.y_train)
        probas[name] = pipe.predict_proba(ds.x_test)[:, 1]
        report_models[name] = {
            "test": evaluate.classification_metrics(ds.y_test, probas[name], DECISION_THRESHOLD),
            "train": evaluate.classification_metrics(
                ds.y_train, pipe.predict_proba(ds.x_train)[:, 1], DECISION_THRESHOLD
            ),
        }

    shipped = models["logistic_regression"]
    coefficients = dict(
        zip(
            features.FEATURE_COLUMNS,
            shipped.named_steps["clf"].coef_[0].round(4).tolist(),
            strict=True,
        )
    )
    # The version identifies everything that changes the model: data, split, threshold, feature
    # schema and windows, qualifying events, and the pipeline's hyperparameters.
    params = {
        "data": fingerprint["sha256"],
        "seed": seed,
        "n_test": n_test,
        "threshold": DECISION_THRESHOLD,
        "feature_columns": features.FEATURE_COLUMNS,
        "window_days": features.WINDOW_DAYS,
        "horizon_days": features.HORIZON_DAYS,
        "qualifying_events": list(QUALIFYING_EVENTS),
        "pipeline": {k: repr(v) for k, v in shipped.get_params(deep=True).items()},
    }
    version = (
        "churn-lr-" + hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:10]
    )

    split = {
        "train_cutoffs": _iso(ds.train_cutoffs),
        "gap_cutoffs_dropped": _iso(ds.gap_cutoffs),
        "test_cutoffs": _iso(ds.test_cutoffs),
        "train_rows": len(ds.x_train),
        "test_rows": len(ds.x_test),
        "train_churn_rate": evaluate_rate(ds.y_train),
        "test_churn_rate": evaluate_rate(ds.y_test),
        "note": "Time-based split by cutoff date; train labels close before the first test cutoff. "
        "The same customers can appear in train and test at different cutoffs.",
    }
    label = {
        "definition": "churn = 1 if the customer has no qualifying event in the horizon after the "
        "cutoff",
        "window_days": features.WINDOW_DAYS,
        "horizon_days": features.HORIZON_DAYS,
        "population": "customers who signed up before the cutoff and had >= 1 qualifying event in "
        "the feature window",
        "qualifying_events": list(QUALIFYING_EVENTS),
    }
    metadata = {
        "model_version": version,
        "model_type": "LogisticRegression(class_weight=balanced) on standardised features",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "decision_threshold": DECISION_THRESHOLD,
        "feature_columns": features.FEATURE_COLUMNS,
        "window_days": features.WINDOW_DAYS,
        "horizon_days": features.HORIZON_DAYS,
        "label": label,
        "data": {**fingerprint, "synthetic": True},
        "split": split,
        "seed": seed,
        "test_metrics": report_models["logistic_regression"]["test"],
        "sklearn_version": sklearn.__version__,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "python_version": platform.python_version(),
    }
    report = {
        "model_version": version,
        "label": label,
        "data": metadata["data"],
        "split": split,
        "models": report_models,
        "baselines": evaluate.baseline_metrics(ds.y_train, ds.y_test, ds.x_test),
        "shipped_model_error_profile": evaluate.error_profile(
            ds.x_test, ds.y_test, probas["logistic_regression"], DECISION_THRESHOLD
        ),
        "shipped_model_standardised_coefficients": coefficients,
    }
    return TrainResult(pipeline=shipped, metadata=metadata, report=report)


def evaluate_rate(y: pd.Series) -> float:
    return round(float(y.mean()), 4)


def _load_events(source: str, csv_dir: Path) -> pd.DataFrame:
    if source == "csv":
        df = pd.read_csv(csv_dir / "events.csv")
        df["properties"] = df["properties"].map(json.loads)
        df["event_timestamp"] = pd.to_datetime(df["event_timestamp"], utc=True)
        return df[["customer_id", "event_name", "event_timestamp", "properties"]]

    from sqlalchemy.orm import Session

    from app.db import repositories
    from app.db.datasets import DEMO_DATASET_ID
    from app.db.session import get_engine

    with Session(get_engine()) as session:
        return repositories.load_events(session, DEMO_DATASET_ID)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--source", choices=["db", "csv"], default="db")
    ap.add_argument("--csv-dir", type=Path, default=Path("../data/processed"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-test", type=int, default=4)
    ap.add_argument("--artifact-dir", type=Path, default=artifact.ARTIFACT_DIR)
    ap.add_argument("--report", type=Path, default=REPORT_PATH)
    a = ap.parse_args()

    result = train(_load_events(a.source, a.csv_dir), a.seed, a.n_test)
    meta = artifact.save(result.pipeline, result.metadata, a.artifact_dir)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result.report, indent=2, sort_keys=True) + "\n")
    t = result.metadata["test_metrics"]
    print(f"saved {meta['model_version']} -> {a.artifact_dir}")
    print(
        f"test: n={t['n']} base_rate={t['base_rate']:.3f} precision={t['precision']:.3f} "
        f"recall={t['recall']:.3f} f1={t['f1']:.3f} roc_auc={t['roc_auc']:.3f}"
    )


if __name__ == "__main__":
    main()
