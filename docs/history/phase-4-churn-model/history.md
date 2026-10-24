# History — phase-4-churn-model

**Status:** done · **Dates:** 2026-10-25

## Done
- `backend/app/services/features.py`: leakage-aware features (15), labels, weekly cutoffs whose horizon is fully observed, time-based split with a purge gap.
- `backend/app/ml/train.py`: offline training CLI (`--source db|csv`); Logistic Regression ships, Random Forest and two naive baselines reported; writes artifact + `reports/churn_eval.json`.
- `backend/app/ml/evaluate.py`: metrics, baselines (majority class; "last active >= 7 days ago" rule), error profile.
- `backend/app/ml/artifact.py`: versioned artifact with SHA-256, feature-schema, window and scikit-learn-version checks before loading.
- `backend/app/ml/train_telco.py`: supplementary stratified-split classifier on the Telco snapshot (not served).
- `backend/app/services/prediction.py`, `schemas/churn.py`, `api/routes/churn.py`: `POST /churn/predict`; model loaded once in the app lifespan, 503 if unavailable.
- Committed artifact (`churn_model.joblib` ~2 KB + `churn_model.json`) and reports (`churn_eval.json`, `telco_eval.json`).
- `docs/model_card.md`; docs 01-04, 09, 10 and diagrams synced.
- Tests: `test_features.py` (hand-checked features, half-open boundaries, future-event leakage guard, cutoffs/split), `test_ml.py` (split hygiene, scaler fitted on train only, reproducibility, hand-checked metrics, artifact tamper/schema/version rejection), `test_churn_api.py` (hand-checked scores, eligibility, 503, 422, train/serve parity on Postgres), `test_train_telco.py`.

- CI: added a Postgres service to `.github/workflows/ci.yml` and made the DB test fixture fail instead of skip under `CI`, because without a database about 40 tests (ingestion, analytics API, parity) would have skipped silently. **Not yet verified on GitHub**: the workflow has not been run (nothing pushed).
- `.gitignore`: exception so the single small serving artifact `churn_model.joblib` is committed.

## Decisions
- Label: among customers active in the prior 28 days, no qualifying activity in the next 14 days. Customers already silent are not scored.
- Ship Logistic Regression (chosen before looking at results); no model selection on the test set.
- Class-balanced training, so scores are documented as relative risk scores, not calibrated probabilities.
- `plan` is not a feature (not loaded for the synthetic customers).
- Predictions are not persisted; the `predictions` table stays unused for now.
- Artifact is committed (tiny) so a clone can serve without retraining; integrity is checked on load because joblib files are pickles.
- Endpoint is open until Phase 5, like the analytics routes.

## Evidence
- `uv run pytest -q`: 76 passed; ruff clean.
- Synthetic log (42,580 events, 2,000 customers), test cutoffs 2026-05-21..06-11 (3,494 rows, 35.6% churn): Logistic Regression ROC-AUC 0.874, precision 0.760, recall 0.738, F1 0.749; Random Forest ROC-AUC 0.883, F1 0.748 (train ROC-AUC 0.963, overfits); rule baseline ROC-AUC 0.873, F1 0.742; majority baseline F1 0.
- Finding: the model adds little over the simple inactivity rule on this synthetic data; one feature carries almost all the signal. Recorded in the model card, not hidden.
- Telco (stratified split, 1,409 test rows, 26.5% churn): Logistic Regression ROC-AUC 0.842, F1 0.614, recall 0.783; Random Forest ROC-AUC 0.837, F1 0.618.
- Training from the Supabase copy and from the CSV gave identical Logistic Regression metrics.
- Live check against Supabase: app lifespan loaded `churn-lr-131edb7229`; 17 requested ids returned 7 scored, 9 not eligible, 1 unknown; ~4 s first call (incl. connection setup), ~1 s for a single customer (single runs, not benchmarks).

## Open items
- Phase 5: authenticate `/churn/predict` and add per-user authorization.
- Possible follow-ups (P1): threshold comparison, calibration, model explanations, persisting predictions, loading customer `plan`.

## Code review fixes (2026-10-25)

A code review of `backend/` found 10 issues; all verified and the following fixed, each with a regression test (suite: 76 -> 94 tests):

- **Artifact trust overstated:** the model file is now read once and hashed over the exact bytes that are unpickled (no check/load race). Docs now say the co-located hash detects corruption, not an attacker; optional `CHURN_MODEL_SHA256` pin (env) is checked before unpickling.
- **Bad artifact could stop the whole API:** `load()` now turns every failure (corrupt pickle, non-object or incomplete metadata, invalid threshold, numpy major mismatch, object without `predict_proba`) into `ModelUnavailable`; the lifespan also catches unexpected errors. Tested: API starts and `/health` works with a corrupt artifact; predict returns 503.
- **`predicted_class` vs rounded `risk_score` could disagree:** the class is now derived from the rounded value returned.
- **Known customers reported as "not found" when no events exist:** they are now `not_eligible`, and `cutoff` is `null` instead of a fabricated wall-clock date.
- **503 not guaranteed:** the model dependency now resolves before the DB session, so a missing model is 503 even if the DB is misconfigured.
- **`model_version` too narrow:** now hashes feature schema, windows, qualifying events and pipeline hyperparameters too; the data fingerprint now includes `properties`. Retrained: `churn-lr-131edb7229` -> `churn-lr-6f4625ce88`; the model file is byte-identical and all metrics are unchanged.
- **Duplicate ids:** behaviour kept (answered once, first-seen order) and now documented in the request schema.
- **Database outage gave a generic 500** (known gap, not from the review): added a `DatabaseUnavailable` error and handlers so DB failures return 503 `Database unavailable` without connection details; 10 s connect timeout. Tested for analytics and predict, with an unreachable and an unconfigured database (suite: 94 -> 101 tests).
- Expected sklearn warnings for single-class metrics are now silenced inside the helper (the value is already reported as `null`). The remaining test warning is Starlette's `httpx` deprecation notice (third-party).
- Not fixed here: `/churn/predict` (and analytics) are unauthenticated, which is Phase 5's job.
