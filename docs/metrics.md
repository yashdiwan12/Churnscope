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

## Uploaded data: derived signup `[Built]` (Phase 6b)

Funnel, retention, new/returning users and churn features all need a `signup` event. A file with no event mapped to `signup` can instead use **"first event counts as signup"**: each customer gets a derived `signup` event at the time of their first mapped event (`properties.derived = true`), and the dataset's `signup_rule` is `derived_from_first_event`. It is allowed only when nothing maps to `signup`.

**Approximate-signup warning.** A customer who really joined before the file starts gets a derived signup at the file's start, which inflates the first cohort and "new users" and makes `account_age_days` mean "days since the file began". The check step computes the share of customers whose first event is in the file's first 7 days. At **25% or more** it shows a red warning and the import button stays disabled until the user ticks "I understand signup dates are approximate" (the server enforces this too). Afterwards Overview (new users), Retention (first cohort) and Churn Risk (account age) carry a fixed note. The threshold was 50% until a trial run: a 10-week slice of the demo data had 45% of customers starting in its first week (about 10% expected with even arrivals) and the warning stayed silent.

## Cohort retention

- **Cohort:** UTC calendar week (Monday start) of the customer's `signup`.
- **Periods:** *elapsed* 7-day periods from each customer's own signup timestamp (period 0 = days 0-6), not calendar weeks.
- **Retained in period k:** >= 1 qualifying event in that period.
- **Eligibility:** a customer counts toward period k only once the whole period has elapsed at `as_of`. Each cell reports `cohort_size`, `eligible`, `retained`, and `retention = retained / eligible`; NaN when `eligible = 0` (incomplete, shown as such in the UI).

## Engagement

Computed for customers active in `[start, end)`:

- **Active days per user:** mean and median count of distinct UTC days with a qualifying event.
- **Events per active user:** qualifying events / active users.
- **Feature adoption:** share of *active users* (not events) with >= 1 `feature_used` event for each `properties.feature`.
- **Median hours between activities:** median gap between a customer's consecutive qualifying events, over customers with >= 2 events (`null` if none).
- **New users:** signups in the window. **Returning users:** active in the window and signed up before `start`; returning-user rate = returning / active. Customers with no signup event are neither.
- Raw event volume is never presented alone.

## API (`/analytics/*`)

Windows are `[start, end)`, tz-aware (naive timestamps -> 422), max 366 days; default is the 30 days ending the day after the latest event. Every response reports `data_through` (latest event in the database). Funnel and retention are right-censored at `data_through`, not at the wall clock, so a stale dataset is not mistaken for dropped-off users.

| Endpoint | Parameters | Notes |
|---|---|---|
| `GET /analytics/overview` | `start`, `end` | active / new / returning users, qualifying events, daily active users |
| `GET /analytics/funnel` | `start`, `end`, `window_days` (1-90, default 14) | customers whose **first** signup is in the window (the same anchor the funnel uses) |
| `GET /analytics/retention` | `periods` (1-26, default 8) | all signup-week cohorts; cells carry `eligible` and `complete` |
| `GET /analytics/engagement` | `start`, `end` | see above |

Empty data returns zeros / `null` rates, not errors. These endpoints require a signed-in, allow-listed user (Phase 5). Since Phase 6b each takes an optional `dataset_id` (default 1, the demo); `data_through` and the right-censoring then refer to that dataset.

### Dashboard display rules (Phase 6)

These are presentation rules, not metric definitions:
- **Inclusive end date.** The UI date picker's end date is inclusive; the app sends midnight UTC of the next day as the API's exclusive `end`. Ranges are limited to 366 days, matching the API.
- **Low n.** A retention cell is labelled "low n" when its `eligible` count (the denominator of the rate shown) is below 20 (`LOW_N_MIN_ELIGIBLE` in `frontend/charts.py`). The unit is the cell, not the cohort.
- **Incomplete cells** (not every cohort member has had the full period) are drawn grey and labelled, never coloured by their rate.
- **Rates** are shown to one decimal with their counts (`n=`); a missing rate shows `n/a`, never `NaN`.

## Churn label (decided in Phase 4)

Fixed in Phase 4: among customers active in the prior 28 days, `churn = 1` if there is no qualifying activity in the next 14 days. Definition, features, and measured results: [Model card](model_card.md).
