"""Supplementary churn classifier on the IBM Telco snapshot (not served by the API).

The file has no timestamps, so this uses a stratified random split and makes **no temporal or
prediction-horizon claims**. See data/README.md and docs/data_dictionary.md for provenance.

Usage (from backend/):  PYTHONPATH=. uv run python -m app.ml.train_telco
"""

import argparse
import json
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.ml import evaluate

DEFAULT_CSV = Path("../data/raw/telco_churn.csv")
REPORT_PATH = Path(__file__).parent / "reports" / "telco_eval.json"
NUMERIC = ["tenure", "MonthlyCharges", "TotalCharges"]


def load_telco(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["TotalCharges"] = pd.to_numeric(df["TotalCharges"], errors="coerce")
    blank = df["TotalCharges"].isna()
    if (df.loc[blank, "tenure"] != 0).any():
        raise ValueError("blank TotalCharges for a customer with tenure > 0: inspect the data")
    df.loc[blank, "TotalCharges"] = 0.0  # tenure 0 = nothing billed yet; not data-dependent
    return df


def _pipeline(model, categorical: list[str], scale: bool) -> Pipeline:
    pre = ColumnTransformer(
        [
            ("num", StandardScaler() if scale else "passthrough", NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
        ],
        remainder="passthrough",  # SeniorCitizen is already 0/1
    )
    return Pipeline([("prep", pre), ("clf", model)])


def run(df: pd.DataFrame, seed: int = 42) -> dict:
    y = (df["Churn"] == "Yes").astype(int)
    x = df.drop(columns=["customerID", "Churn"])
    categorical = [c for c in x.columns if x[c].dtype == object or str(x[c].dtype) == "str"]
    x_tr, x_te, y_tr, y_te = train_test_split(x, y, test_size=0.2, stratify=y, random_state=seed)

    models = {
        "logistic_regression": _pipeline(
            LogisticRegression(class_weight="balanced", max_iter=2000, random_state=seed),
            categorical,
            scale=True,
        ),
        "random_forest": _pipeline(
            RandomForestClassifier(
                n_estimators=300,
                min_samples_leaf=3,
                class_weight="balanced_subsample",
                random_state=seed,
                n_jobs=-1,
            ),
            categorical,
            scale=False,
        ),
    }
    out = {}
    for name, pipe in models.items():
        pipe.fit(x_tr, y_tr)  # preprocessing is fitted on the training split only
        out[name] = evaluate.classification_metrics(y_te, pipe.predict_proba(x_te)[:, 1])
    majority = int(y_tr.mean() >= 0.5)
    out["majority_class"] = evaluate.classification_metrics(y_te, [float(majority)] * len(y_te))
    return {
        "dataset": "IBM Telco Customer Churn (static snapshot, no timestamps)",
        "split": {
            "method": "stratified random 80/20; not temporal",
            "train_rows": len(x_tr),
            "test_rows": len(x_te),
            "train_churn_rate": round(float(y_tr.mean()), 4),
            "test_churn_rate": round(float(y_te.mean()), 4),
            "seed": seed,
        },
        "test_metrics": out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--report", type=Path, default=REPORT_PATH)
    a = ap.parse_args()
    report = run(load_telco(a.csv), a.seed)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for name, m in report["test_metrics"].items():
        print(
            f"{name}: precision={m['precision']:.3f} recall={m['recall']:.3f} "
            f"f1={m['f1']:.3f} roc_auc={m['roc_auc']:.3f}"
        )


if __name__ == "__main__":
    main()
