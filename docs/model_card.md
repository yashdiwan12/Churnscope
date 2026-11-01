# Model card: churn risk

Status: **[Built]** in `backend/app/ml/`, `backend/app/services/features.py`, `backend/app/services/prediction.py`. Numbers below are copied from `backend/app/ml/reports/churn_eval.json` and `telco_eval.json`, produced by the commands in [Reproducing](#reproducing).

> **Everything here is measured on synthetic data.** The event log comes from a seeded generator in which customers stop being active after a random "churn week". Results show how well the pipeline recovers that behaviour, **not** how well it would predict real customers.

## Scope: the shipped model is demo-only

The model described below is trained on the synthetic demo data and is used **only for the demo dataset**. Uploaded data (Phase 6b) is never scored with it. An upload is scored by a method that is **trained and backtested on that file's own history**: weekly cutoffs, the same 28-day features and 14-day label as below, the latest 2 weekly cutoffs held out (with a 14-day purge gap), and a logistic regression compared with the days-since-last-activity rule (7 days or more) on the held-out rows. The model is used only if its PR-AUC beats the rule's by at least 0.02, otherwise the rule is used. If the file is too short for a fair test (floors: 200 test rows, 20 churners and 20 non-churners in the test, 20 churners in training) the page falls back to the rule marked "not checked on your data" (needs at least 28 days of history) or to nothing. A checked result needs roughly 9 weeks of history. The page shows the file's own numbers (test rows, churners, PR-AUC of model and rule), never the synthetic model's metrics. The fitted model is stored as JSON numbers, not a pickle. In a trial on slices of the demo data the rule won every time (PR-AUC 0.821 vs 0.820 on the full file), as expected because the generator's churn is inactivity itself. "Churn" for an upload means 14 days of inactivity, not cancellation, and a backtest on the recent past does not show the method will keep working. Design: [Phase 6b spec, section 5a](superpowers/specs/2026-11-01-phase6b-uploads-design.md).

## Summary

| | |
|---|---|
| Task | Among customers active in the last 28 days, will they have **no qualifying activity in the next 14 days**? |
| Shipped model | `churn-lr-e330fa34d3`: Logistic Regression (class-balanced) on 15 standardised behavioural features |
| Test result | ROC-AUC **0.879**, precision 0.750, recall 0.741, F1 0.746 at threshold 0.5 (churn rate in test: 34.5%) |
| Honest headline | It beats "always predict no churn" clearly, but it **does not clearly beat a one-line rule** ("last active 7 or more days ago"): F1 0.746 vs 0.742, ROC-AUC 0.879 vs 0.881 (the rule is slightly ahead on ROC-AUC) |
| Served by | (demo data only) `POST /churn/predict` and `GET /churn/at-risk` (the ranked list behind the dashboard's Churn Risk page; both require a signed-in, allow-listed user) |

## Label and population

For a **cutoff** `t` (weekly, midnight UTC) and a customer:

- **Eligible** if they signed up before `t` and had at least one qualifying event (`session_start`, `feature_used`, `report_created`, `report_shared`) in `[t - 28d, t)`. A customer already silent for 28 days has already churned and is not scored.
- **Label** `churn = 1` if they have **no** qualifying event in `[t, t + 14d)`, else 0.
- Cutoffs run weekly from 28 days after the first event until the last one whose 14-day horizon is fully observed in the data.

Timeline diagram: [System design 3.5](03-system-design.md). Qualifying events: [Metrics](metrics.md).

## Features

All computed from events in `[t - 28d, t)` plus first-occurrence times strictly before `t` (`features.py`). Windows are half-open, so an event exactly at `t` is a label event, never a feature.

| Feature | Definition |
|---|---|
| `days_since_last_activity` | days from the last qualifying event to `t` |
| `active_days_28d`, `active_days_14d` | distinct UTC days with a qualifying event in the last 28 / 14 days |
| `events_28d` | qualifying events in the window |
| `sessions_28d`, `features_used_28d`, `reports_created_28d`, `reports_shared_28d` | counts by event type |
| `events_last_14d`, `events_prev_14d` | qualifying events in the recent and earlier half of the window |
| `activity_change` | `(last14 - prev14) / (last14 + prev14)`, in [-1, 1] |
| `distinct_features_28d` | distinct `properties.feature` values used |
| `onboarding_complete`, `has_created_report` | 1 if the first such event happened before `t` |
| `account_age_days` | days from signup to `t` |

Not used: `plan` (the customer table has no plan loaded for the synthetic data, and the generator does not make behaviour depend on it).

## Evaluation design

- **Time-based split by cutoff:** the last 4 weekly cutoffs are test (2026-05-21 to 2026-06-11, 3,494 rows); training uses earlier cutoffs (2026-01-29 to 2026-05-07, 9,580 rows). The cutoff 2026-05-14 is dropped so every training label's 14-day horizon closes by the first test cutoff. Data: 42,847 events, 2,000 customers (synthetic, seed 42).
- Preprocessing (standardisation) is fitted **inside the pipeline on training rows only**; a test checks this.
- Nothing is tuned or selected on the test set. Logistic Regression was chosen up front as the interpretable baseline; Random Forest and two naive baselines are reported for comparison on the same rows.
- **Caveat:** the same customers appear in train and test at different cutoffs, so this measures generalisation over time, not to unseen customers.
- Class balance: 34.9% churn in train, 34.5% in test (moderate imbalance). Models use class weighting, so scores are **relative risk scores, not calibrated probabilities**.

## Results (test set, threshold 0.5)

| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|---|
| **Logistic Regression (shipped)** | 0.826 | 0.750 | 0.741 | 0.746 | 0.879 | 0.829 |
| Random Forest | 0.827 | 0.754 | 0.740 | 0.747 | 0.884 | 0.834 |
| Baseline: last active >= 7 days ago | 0.830 | 0.780 | 0.707 | 0.742 | 0.881 | 0.827 |
| Baseline: always "no churn" | 0.655 | 0.000 | 0.000 | 0.000 | 0.500 | 0.345 |

Logistic Regression confusion matrix: TN 1,992 · FP 297 · FN 312 · TP 893.

What this does and does not show:

- Accuracy alone is misleading here: always predicting "no churn" already scores 65.5%.
- On this synthetic data **one feature (`days_since_last_activity`) carries almost all the signal**; the 15-feature model adds nothing measurable over the simple rule (F1 0.746 vs 0.742, ROC-AUC 0.879 vs 0.881). Random Forest is within 0.005 ROC-AUC of Logistic Regression and overfits: train ROC-AUC 0.964 vs test 0.884, while Logistic Regression shows no gap (0.879 train vs 0.879 test).
- Logistic Regression's standardised coefficient for `days_since_last_activity` is +2.13, far larger than any other (next largest in magnitude: 0.35). Several features are strongly correlated (`activity_change`, `events_last_14d`, `events_prev_14d`, `active_days_*`), so the signs of their individual coefficients are **not** reliable explanations.

## Error review

Mean feature values by outcome for the shipped model (full table in `churn_eval.json`):

| Group | n | days since last activity | events (28d) | active days (14d) |
|---|---|---|---|---|
| False negative (missed churn) | 312 | 3.1 | 8.2 | 3.9 |
| False positive (false alarm) | 297 | 10.7 | 4.8 | 1.6 |
| True positive | 893 | 16.9 | 5.1 | 0.8 |
| True negative | 1,992 | 1.8 | 11.7 | 5.0 |

Missed churners look like healthy, recently active customers who then went silent; that is behaviour no feature can foresee in this generator (a customer's activity stops abruptly at a random week). False alarms are customers who were quiet for about 11 days but came back within the horizon.

## Supplementary: IBM Telco classifier

A separate tabular classifier on the static Telco snapshot (`backend/app/ml/train_telco.py`), **not served by the API**. The data has no timestamps, so it uses a stratified random 80/20 split (5,634 train / 1,409 test, 26.5% churn in both) and makes **no temporal or horizon claims**.

| Model | Accuracy | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---|---|---|
| Logistic Regression | 0.738 | 0.504 | 0.783 | 0.614 | 0.842 |
| Random Forest | 0.775 | 0.563 | 0.684 | 0.618 | 0.837 |
| Always "no churn" | 0.735 | 0.000 | 0.000 | 0.000 | 0.500 |

Accuracy barely moves over the majority baseline because of the class imbalance; compare ROC-AUC and recall instead. Blank `TotalCharges` (11 rows, all `tenure = 0`) are set to 0, since nothing has been billed yet; the loader refuses blanks for customers with tenure above 0. Licence and provenance: [data/README.md](../data/README.md).

## Artifact and serving

- Files: `backend/app/ml/artifacts/churn_model.joblib` (fitted pipeline, ~2 KB) and `churn_model.json` (version, feature schema, windows, label definition, data fingerprint, split, test metrics, seed, library versions, SHA-256 of the model file).
- The API loads it once at startup. It **refuses** an artifact whose SHA-256, feature columns, window/horizon, scikit-learn minor or numpy major version does not match, whose metadata is malformed, or that cannot be unpickled; then `/churn/predict` returns 503 `Churn model is unavailable` and the rest of the API keeps working (tested with a corrupt artifact).
- **What the hash does and does not protect.** Joblib files are pickles and can run code when loaded. The model file is read once and the hash is computed over exactly the bytes that are unpickled. The hash in `churn_model.json` sits next to the model, so it catches corruption and mismatches but **not** someone who can write to that folder. For that, set `CHURN_MODEL_SHA256` (from a trusted place such as the host's secret store); it is checked before anything is unpickled. Only artifacts we trained ourselves should ever be placed there.
- The version (`churn-lr-…`) hashes the data fingerprint (all event columns, including `properties`), seed, split size, threshold, feature schema, windows, qualifying events and pipeline hyperparameters, so any of those changing gives a new version.
- Serving builds features with the same `features.build_features` used in training (a test asserts API scores equal the pipeline's scores on directly built features).
- Prediction cutoff is the last midnight (UTC) at or before the latest event (`null` if no events exist yet), so it always has complete data before it, as in training; the partial latest day is not used. A customer with no qualifying activity in the prior 28 days is returned as `not_eligible`, not scored; unknown ids as `unknown_customer`; repeated ids are answered once. `predicted_class` is derived from the same rounded `risk_score` that is returned, so the two never disagree. Predictions are not stored (the `predictions` table is unused so far).
- Measured latency (single warm runs from the dev machine to the Seoul-region Supabase pooler on 2026-10-29, not benchmarks): about 0.9 s for one customer and about 1.3 s for 17 customers. One earlier run, taken while Docker Desktop was starting on the same machine, was far slower (12 to 53 s for analytics calls), so treat all of these as indicative only.

## Limitations

- Synthetic data; the churn mechanism is the generator's, so absolute numbers say nothing about real products.
- Weak evidence that the model adds value beyond a simple inactivity rule.
- Scores are uncalibrated; the 0.5 threshold is a default, not tuned to any cost trade-off (threshold comparison is a P1 item).
- Same customers in train and test (different times). No fairness or subgroup analysis: the data has no demographic attributes.
- Weekly cutoffs overlap in time for a customer, so rows are correlated; no confidence intervals are reported.

## Reproducing

```bash
cd backend
PYTHONPATH=. uv run python -m app.ml.train --source db        # or: --source csv --csv-dir ../data/processed
PYTHONPATH=. uv run python -m app.ml.train_telco              # needs data/raw/telco_churn.csv
uv run pytest -q tests/test_features.py tests/test_ml.py tests/test_churn_api.py tests/test_train_telco.py
```

The same seed and data give the same `model_version`, test metrics, and coefficients (tested). Training from the database and from the CSV gave identical Logistic Regression metrics, while Random Forest figures differed in the third decimal between the two (0.884 vs 0.883 ROC-AUC, measured on the earlier data); the versions differ because the fingerprint hashes customer ids as given (internal ids vs external ids).
