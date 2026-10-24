"""Telco classifier on a small synthetic frame with the same columns (the real CSV is git-ignored)."""

import numpy as np
import pandas as pd
import pytest

from app.ml import train_telco


def telco_like(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tenure = rng.integers(0, 72, n)
    monthly = rng.uniform(20, 110, n).round(2)
    churn = rng.random(n) < np.clip(0.9 - tenure / 60, 0.05, 0.9)  # short tenure -> likely churn
    return pd.DataFrame(
        {
            "customerID": [f"{i:04d}" for i in range(n)],
            "gender": rng.choice(["Female", "Male"], n),
            "SeniorCitizen": rng.integers(0, 2, n),
            "Partner": rng.choice(["Yes", "No"], n),
            "Contract": rng.choice(["Month-to-month", "One year", "Two year"], n),
            "InternetService": rng.choice(["DSL", "Fiber optic", "No"], n),
            "tenure": tenure,
            "MonthlyCharges": monthly,
            "TotalCharges": (tenure * monthly).round(2).astype(str),
            "Churn": np.where(churn, "Yes", "No"),
        }
    )


def test_blank_total_charges_for_new_customers_become_zero(tmp_path):
    df = telco_like()
    df.loc[df.index[:3], ["tenure", "TotalCharges"]] = [0, " "]
    path = tmp_path / "t.csv"
    df.to_csv(path, index=False)
    loaded = train_telco.load_telco(path)
    assert loaded["TotalCharges"].dtype == float and (loaded.loc[:2, "TotalCharges"] == 0).all()


def test_blank_total_charges_with_tenure_is_rejected(tmp_path):
    df = telco_like()
    df.loc[0, ["tenure", "TotalCharges"]] = [10, " "]
    path = tmp_path / "t.csv"
    df.to_csv(path, index=False)
    with pytest.raises(ValueError, match="tenure > 0"):
        train_telco.load_telco(path)


def test_run_is_stratified_reproducible_and_labelled_non_temporal():
    df = telco_like()
    a = train_telco.run(df, seed=3)
    assert a == train_telco.run(df, seed=3)
    s = a["split"]
    assert s["train_rows"] + s["test_rows"] == len(df) and "not temporal" in s["method"]
    assert abs(s["train_churn_rate"] - s["test_churn_rate"]) < 0.02  # stratification kept the rate
    m = a["test_metrics"]
    assert m["logistic_regression"]["roc_auc"] > 0.55
    assert m["majority_class"]["roc_auc"] == 0.5
