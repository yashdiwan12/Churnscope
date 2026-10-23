# Metric definitions

Status: **[Built]** in `backend/app/services/metrics.py`, verified on hand-checked examples in `backend/tests/test_metrics.py`. All timestamps are tz-aware UTC; naive timestamps are rejected.

## Qualifying events

| Event | Qualifying activity? | Why |
|---|---|---|
| `session_start` | yes | user opened the product |
| `feature_used` | yes | `properties.feature` names the feature |
| `report_created` | yes | key action |
| `report_shared` | yes | key action |
| `signup` | no | account creation, not usage |
| `onboarding_complete` | no | setup step, not ongoing usage |

Event allow-list: the six names above (`EVENT_NAMES`). Anything else is rejected at ingestion (Phase 2).

## Active users

Distinct customers with >= 1 qualifying event in the half-open window `[start, end)`. Empty window or no events: 0.

## Funnel

Steps: `signup -> onboarding_complete -> report_created` (the "first key action").

- **Counting:** per customer, once per step, using the *first* occurrence of the event.
- **Ordering:** a customer reaches step N only if they reached step N-1 and the step-N event is at or after the step N-1 event time.
- **Window:** every step must occur within `window_days` (default 14) of signup.
- **Eligibility (censoring):** only customers whose full window has elapsed at `as_of` are counted, so recent signups do not look like drop-offs.
- **Rates:** `conversion_from_previous = reached N / reached N-1`; `conversion_from_start = reached N / eligible`. NaN when the denominator is 0.

## Cohort retention

- **Cohort:** UTC calendar week (Monday start) of the customer's `signup`.
- **Periods:** *elapsed* 7-day periods from each customer's own signup timestamp (period 0 = days 0-6), not calendar weeks.
- **Retained in period k:** >= 1 qualifying event in that period.
- **Eligibility:** a customer counts toward period k only once the whole period has elapsed at `as_of`. Each cell reports `cohort_size`, `eligible`, `retained`, and `retention = retained / eligible`; NaN when `eligible = 0` (incomplete, shown as such in the UI).

## Engagement (defined now, implemented in Phase 3)

Active days per active user, qualifying events per active user, feature adoption (share of active users using each `properties.feature`), returning-user rate, median time between qualifying activities. Raw event volume is never presented alone.

## Churn label (decided in Phase 4)

Not fixed yet. The working proposal in [System design](03-system-design.md) is inactivity over a future horizon on the synthetic log.
