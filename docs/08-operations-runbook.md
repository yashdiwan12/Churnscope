# 8. Operations runbook

## 8.1 Routine tasks

| Task | How |
|---|---|
| Health check | `GET /health` → 200 and DB reachable |
| Load / reload data | run ingestion loader against `/events` (idempotent, safe to repeat) |
| Retrain model | `cd backend && python -m app.ml.train`, review metrics, update model card, deploy new artifact + `model_version` |
| Apply migration | `cd backend && alembic upgrade head` (staging first) |
| Rotate a secret | replace in host secret store → restart service → verify `/health` and a sign-in |

## 8.2 Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| All requests 401 | Wrong JWT secret/JWKS, clock skew, expired session | Check `SUPABASE_*` env; sign out/in |
| Dashboard shows "API unavailable" | API down, wrong `API_BASE_URL`, CORS | Check `/health`, frontend env, `CORS_ORIGINS` |
| 503 on `/churn/predict` only | Artifact missing or schema mismatch | Verify artifact path/version; retrain or redeploy |
| 503 everywhere | DB unreachable / pool exhausted | Check Supabase status, `DATABASE_URL`, pooler |
| Duplicate counts after load | Different `event_id` per run | Ensure loader emits stable IDs |
| Retention looks too low for recent cohorts | Incomplete cohorts | Expected; UI flags them |
| Slow analytics | Missing index / large scan | `EXPLAIN ANALYZE`, add index per real query |
| Dashboard says access not allowed (403) | Email not on `ALLOWED_EMAILS` / `ALLOWED_EMAIL_DOMAINS`, or not a Google sign-in | Update the allow-list, restart the API |
| Dashboard shows service unavailable after a long idle | Free-tier database or API cold start | Click Retry; `/me` has a short timeout so the first load can fail once |
| Churn list looks outdated after loading events | In-process cache keyed by the newest event id | Restart the API; a new event id rescored automatically |
| Upload fails with 409 `storage_full` | The global cap of 300,000 uploaded events (all users) would be exceeded | Delete or purge old uploads (8.2a), then retry; raise `GLOBAL_UPLOADED_EVENTS_CAP` in `services/uploads.py` only after checking free database space |
| Churn Risk says scoring failed, with Retry | Fitting threw an error; the dataset itself is intact | Click Retry (`POST /datasets/{id}/score`); if it keeps failing, check the log for `scoring failed: <ExceptionType>` (type only, by design) |
| Churn Risk for an upload says not available and has no Retry | The import committed but storing the scoring result failed | Re-import the file, or `POST /datasets/{id}/score` |
| Import times out in the UI | Cold free-tier database or a slow connection (the UI waits 60 s) | Retry: the file is re-sent from the session, and a replace that already committed is safe to repeat |
| OAuth redirect error | Redirect URL not registered | Add URL in Supabase + Google Cloud |

## 8.2a Uploads `[Built]` (Phase 6b)

**Purge old uploads.** There is no automatic expiry. From `backend/`, with `DATABASE_URL` in the environment:

```bash
PYTHONPATH=. uv run python scripts/purge_uploads.py --older-than 30 --dry-run   # counts only
PYTHONPATH=. uv run python scripts/purge_uploads.py --older-than 30             # deletes
```

It deletes uploads whose import date (`datasets.created_at`) is older than the given number of days (a positive whole number); customers and events cascade. The demo dataset is never touched. It prints counts only, never customer ids, file names or file content. It is a separate process, so it cannot clear a running API's in-memory churn cache: cached scored rows for a purged dataset can linger until the cache evicts them (it holds 4 entries) or the API restarts, although the dataset can no longer be selected. Restart the API if that matters.

**Import time.** Measured on 2026-11-01 on the Supabase project through the session pooler, with the same table shape as migration 0003, batches of 5,000 in one transaction under the advisory lock: connect and first statement 3.1 s; 10,000 customers 2.0 s; 10,000 customers plus 50,000 events 6.7 s in total; loading those 50,000 events back (as scoring does) 1.5 s; cascade delete of all of them 0.9 s. The pooler's statement timeout is 2 minutes. With the local fit time (0.8 s), a worst-case replace plus scoring is about 10 to 12 s, well inside the UI's 60 s import timeout. A free-tier cold start comes on top and was not measured.

**Storage.** The global cap is 300,000 uploaded events across all users (about 120 MB, a quarter of the 500 MB free tier); a larger import gets 409 `storage_full`. Per file: 5 MB, 50,000 rows, 10,000 customers.

## 8.3 Logging

Structured logs (request id, route, status, latency). **Never** log tokens, passwords, or personal data. Rejected-ingestion rows log reason codes only. Upload failures log the exception type only, never a message or file value.

## 8.4 Incident steps

1. Confirm scope (`/health`, host logs).
2. Mitigate (roll back deploy / restore previous model artifact).
3. If a secret may be exposed: rotate immediately, then audit.
4. Record cause and fix in the relevant phase `history.md`.

## 8.5 Backups

Supabase managed backups cover the database; confirm the plan's retention. Demo data is synthetic/public, so loss is recoverable by re-running the generator and loader (seeded, deterministic). Uploads are the owners' own files and are not recoverable from the database: users keep their source file.

## 8.6 Known limitations `[Built]` (Phase 7a)

No performance or scale figures are claimed until measured. The public churn dataset has no temporal validity. Single instance, no HA. Each line below is: what, why it is accepted, what would change it. Items fixed in Phase 7a are listed in the [Phase 7 history](history/phase-7-quality-and-docs/history.md), not here.

**Authentication (Phase 5)**
- A network blip while refreshing the token signs the user out. Accepted: the user signs in again and loses nothing stored. Would change: complaints, or a retry-once on refresh.
- Login CSRF: the PKCE verifier is held by the server process, not the browser that began the flow, so an allow-listed attacker could hand a victim a sign-in link for the attacker's own account. Accepted: the attacker must already be allow-listed and the app shows only the signed-in account's own data. Would change: a cookie-bound state (needs a Streamlit component), or opening sign-up to the public.

**Dashboard (Phase 6)**
- One-time Streamlit log warning on the first sort change; the sort resets to default after an error or empty run. Cosmetic. Would change: a user report.
- `/me` uses a 10 s timeout, so a cold database start shows "unavailable". Accepted: a reload fixes it. Would change: a measured free-tier cold start (Phase 7b).
- Customer-id sort is lexicographic; the page number has no maximum; the default end date uses `date.today()`, not UTC. Cosmetic or off-by-a-day at midnight only. Would change: ids with a numeric meaning, or users in far time zones.

**Uploads, backend (Phase 6b)**
- Demo dataset counts and `data_through` in `GET /datasets` are fixed at migration time. The demo data never changes after the loader runs. Would change: live events into the demo dataset.
- The churn cache removes a per-key lock and inserts the entry in two separate critical sections, so two requests can score the same dataset twice (no corruption). Any eviction bumps one global generation, so other datasets' in-flight results are dropped once. Speed only, at a 4-entry cache. Would change: more concurrent users than the allow-list allows.
- `risk_asc` re-sorts the whole frame for each page and the max event timestamp is queried again per request. Speed only at 50,000 events. Would change: a measured slow page.
- The model-wins test fixture is a 21-day cycle; LRU recency is untested; the tests use a literal 1 for the demo id. Test quality only.
- `default_cutoff` keeps a silent demo default; models drift from migration 0003 (Identity, FK names); E501 is not enforced. Code hygiene. Would change: the next change in those files.
- Mapping value checks run after the parse; up to 5 MiB is parsed before the row limit applies; blank lines count as invalid rows; out-of-range timestamps are reported as `bad_timestamp`, not `timestamp_out_of_range`; optional columns other than `event_id` may repeat under different names. Accepted: results are still correct and the 5 MB cap bounds the work. Would change: abuse, or user confusion about messages.
- `db/datasets.py` imports `services/uploads` (a layering cycle) and the `too_many_customers` message and skip-reason slicing are duplicated. Hygiene. Would change: a third caller.

**Uploads, frontend (Phase 6b)**
- The demo banner no longer shows before sign-in (nothing is shown before sign-in). Would change: a public landing page.
- Import gate and preview compute "has activity" separately; escape tests do not cover backslashes or a render round trip; the replace caption's escaping, the `/datasets/check` timeout path and the `current_upload` test seam restore are untested or loose. Test and hygiene items, no known wrong output.

**Product**
- No rate limit on `POST /datasets/check`. Accepted while access is allow-listed and the body is capped at 5 MB. Would change: public sign-up, then a limit at the host or in the API.
- No automatic upload expiry; `scripts/purge_uploads.py` is run by hand (8.2a). Would change: a retention promise to users, then a scheduled job (Phase 7b).
- The 0.02 PR-AUC margin and the scoring floors are judgement calls. Would change: evidence from real files that they pick the wrong method.
- Profile deletion (`user_profiles`) is not automated; deleting an account's rows is a manual operation. Would change: a user-facing delete-account feature.

## 8.7 Test coverage

Each bullet of PLAN.md section 13 and the test that checks it. Backend tests are in `backend/tests/`, frontend tests in `frontend/tests/`.

| PLAN.md item | Test file | Test function(s) |
|---|---|---|
| Valid event accepted | `test_ingestion.py` | `test_valid_events_inserted_and_customer_created` |
| Invalid event rejected | `test_ingestion.py` | `test_invalid_events_rejected_with_reason_and_valid_ones_kept` |
| Duplicate event handled safely | `test_ingestion.py` | `test_reingesting_same_batch_creates_no_duplicates`, `test_duplicate_within_one_batch_and_overlapping_batches`, `test_concurrent_ingestion_of_same_events_does_not_duplicate` |
| Invalid timestamp or oversized payload rejected | `test_ingestion.py`, `test_events_api.py` | `test_future_and_ancient_timestamps_are_rejected`, `test_body_over_5mb_is_413_before_parsing`, `test_more_than_5000_events_is_422` |
| Active-user counts match hand-calculated examples | `test_metrics.py`, `test_analytics_api.py` | `test_active_users_counts_distinct_qualifying_in_half_open_window`, `test_overview_hand_checked` |
| Funnel ordering and denominator are correct | `test_metrics.py`, `test_analytics_api.py` | `test_funnel_ordering_window_and_censoring`, `test_funnel_hand_checked_with_default_window` |
| Retention handles incomplete cohorts | `test_metrics.py`, `test_analytics_api.py` | `test_retention_cells_and_incomplete_periods`, `test_retention_marks_incomplete_cells` |
| Empty ranges return meaningful results | `test_metrics.py`, `test_analytics_api.py` | `test_active_users_empty_range_is_zero`, `test_empty_database_returns_zeros_not_errors` |
| Time-zone boundaries are consistent | `test_metrics.py` | `test_rejects_naive_timestamps`, `test_week_boundary_uses_utc_monday` |
| Missing/invalid token is rejected for protected endpoints | `test_authorization.py`, `test_security.py` | `test_missing_or_malformed_authorization_is_401`, `test_invalid_tokens_are_401`, `test_rejected_with_invalid_token` |
| User A cannot access User B's private records | `test_me_api.py`, `test_reports.py` | `test_users_cannot_list_or_delete_each_others_reports_in_either_direction`, `test_users_only_see_their_own_reports` |
| Client-supplied identity cannot override verified identity | `test_me_api.py` | `test_bad_report_bodies_are_422` (a `user_id` field is a 422), `test_me_returns_token_identity_and_creates_the_profile_once` |
| Secrets never appear in responses or logs | `test_events_api.py`, `test_authorization.py`, `test_security.py`, `test_datasets_import_api.py`, `test_uploads_parse.py` | `test_key_never_appears_in_responses_or_logs`, `test_responses_and_logs_do_not_contain_the_token`, `test_error_messages_never_contain_the_token`, `test_database_error_on_import_never_logs_file_values`, `test_no_file_value_in_any_message` |
| Training and inference use the same feature schema | `test_ml.py`, `test_churn_api.py` | `test_model_uses_exactly_the_feature_schema`, `test_serving_matches_training_features_exactly` |
| Preprocessing is fitted on training data only | `test_ml.py` | `test_preprocessing_is_fitted_on_training_rows_only` |
| Future information does not enter features | `test_features.py` | `test_future_events_never_change_features`, `test_labels_use_only_the_horizon` |
| Model artifact/version is recorded | `test_ml.py`, `test_churn_api.py` | `test_artifact_round_trip_preserves_predictions`, `test_model_version_changes_with_hyperparameters`, `test_scores_hand_checked_and_preserves_request_order` |
| Malformed inputs are handled | `test_churn_api.py`, `test_ml.py` | `test_invalid_requests_are_422`, `test_malformed_metadata_is_unavailable_not_a_crash` |
| Evaluation can be reproduced | `test_ml.py` | `test_training_is_reproducible` |
| Dashboard handles API errors | `frontend/tests/test_api_client.py`, `frontend/tests/test_gate.py` | `test_status_mapping`, `test_me_other_4xx_shows_the_unavailable_message_not_a_traceback` |
| Database failures do not appear as successful writes | `test_failed_writes.py`, `test_ingestion.py`, `test_db_unavailable.py` | `test_failed_write_is_never_2xx`, `test_failed_write_rolls_back_everything`, `test_database_failures_are_503_without_details` |
| Event-to-analytics flow works on a small test dataset | `test_end_to_end.py` | `test_events_in_analytics_out` |
