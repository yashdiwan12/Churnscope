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
| OAuth redirect error | Redirect URL not registered | Add URL in Supabase + Google Cloud |

## 8.3 Logging

Structured logs (request id, route, status, latency). **Never** log tokens, passwords, or personal data. Rejected-ingestion rows log reason codes only.

## 8.4 Incident steps

1. Confirm scope (`/health`, host logs).
2. Mitigate (roll back deploy / restore previous model artifact).
3. If a secret may be exposed: rotate immediately, then audit.
4. Record cause and fix in the relevant phase `history.md`.

## 8.5 Backups

Supabase managed backups cover the database; confirm the plan's retention. Data is synthetic/public, so loss is recoverable by re-running the generator and loader (seeded, deterministic).

## 8.6 Known limitations

No performance or scale figures are claimed until measured. The public churn dataset has no temporal validity. Single instance, no HA.
