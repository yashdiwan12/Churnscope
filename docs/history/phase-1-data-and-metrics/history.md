# History — phase-1-data-and-metrics

**Status:** done · **Started:** 2026-10-24

## Done
- `docs/metrics.md`: qualifying events, active users, funnel, cohort retention definitions.
- `backend/app/services/metrics.py`: `active_users`, `funnel`, `cohort_retention` (pure Pandas).
- `backend/tests/test_metrics.py`: hand-checked example (ordering, window, right-censoring, incomplete periods, UTC week boundary, naive-timestamp rejection, empty input).
- `backend/scripts/generate_events.py`: seeded synthetic generator; `tests/test_generate_events.py` checks determinism and validity.
- `docs/data_dictionary.md` for the synthetic log.

## Decisions
- Qualifying activity excludes `signup` and `onboarding_complete`.
- Funnel: first occurrence per step, ordered, within 14 days of signup, right-censored customers excluded.
- Retention: signup-week cohorts, elapsed 7-day periods per customer, incomplete cells are NaN with eligible counts reported.

## Evidence
- `uv run pytest -q`: 10 passed; ruff check/format clean.
- Smoke run on seed 42 (2,000 customers, 42,580 events) produced plausible funnel/retention output. These reflect generator assumptions, not real behaviour.

- 2026-10-24: downloaded the Telco CSV (IBM GitHub repo) to `data/raw/telco_churn.csv` and inspected it: 7,043 x 21, unique IDs, no duplicates or nulls, 11 blank `TotalCharges` (all tenure 0), churn 26.54%. Findings and modelling implications are in `docs/data_dictionary.md`.

## Open items
None.
