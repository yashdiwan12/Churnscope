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

## 8.6 Known limitations

No performance or scale figures are claimed until measured. The public churn dataset has no temporal validity. Single instance, no HA.
