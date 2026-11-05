# Churnscope — Progress

Live tracker of implementation progress per phase. Detailed notes, decisions, and evidence live in each phase's `docs/history/<phase>/history.md`; the phase summary table is in [docs/10-project-history.md](docs/10-project-history.md).

**Legend:** ✅ done · 🟡 in progress · ⬜ not started · Updated: 2026-11-06 · Phase 7a and the pre-deploy polish are merged into `main` (not yet pushed): backend 436 (2 opt-in timing tests skipped) and frontend 226 tests pass locally at the last full run

## Summary

| Phase | Milestone | Status | Done / Total |
|---|---|---|---|
| 0 | Setup | ✅ Done | 10 / 10 |
| 1 | Data & metric definitions | ✅ Done | 6 / 6 |
| 2 | Database & ingestion | ✅ Done | 7 / 7 |
| 3 | Analytics | ✅ Done | 6 / 6 |
| 4 | Churn model | ✅ Done | 8 / 8 |
| 5 | Authentication & authorization | ✅ Done | 8 / 8 |
| 6 | Dashboard | ✅ Done (merged) | 7 / 7 |
| 6b | Bring your own data (uploads) | ✅ Done (merged) | 8 / 8 |
| 7 | Quality & documentation | 🟡 7a done (merged); 7b deploy not started | 9 / 10 |

## Phase 0 — Setup ✅  ([history](docs/history/phase-0-setup/history.md))
- [x] Git repository exists
- [x] Repo structure (`backend/`, `frontend/`, `data/`, `notebooks/`, `docs/`)
- [x] `.gitignore`, `.env.example`, README
- [x] Documentation set (docs 01–10 + guide) and per-phase history files
- [x] Tech stack decided
- [x] `backend/pyproject.toml` and `frontend/pyproject.toml` with dependencies (`uv`)
- [x] Minimal FastAPI app with `/health` and a passing test
- [x] Minimal Streamlit app and GitHub Actions CI workflow
- [x] Select and document public churn dataset (IBM Telco; licence unstated, noted) in `data/README.md`
- [x] Initial commit of scaffold (own repo, tagged `v0.1-phase0`)

**Exit:** clean local setup, documented data source, no secrets in Git.

## Phase 1 — Data & metric definitions ✅  ([history](docs/history/phase-1-data-and-metrics/history.md))
- [x] Inspect schema, types, missing values, duplicates, timestamps (synthetic log validated; Telco CSV inspected)
- [x] Write data dictionary
- [x] Define qualifying activity events
- [x] Define funnel steps and conversion rules
- [x] Define cohort and retention periods
- [x] Validate metrics on hand-checkable examples

## Phase 2 — Database & ingestion ✅  ([history](docs/history/phase-2-database-and-ingestion/history.md))
- [x] Supabase project and PostgreSQL schema (migrated via Alembic; verified on local Docker Postgres and Supabase)
- [x] SQLAlchemy configured with driver
- [x] Tables, constraints, initial indexes (Alembic)
- [x] Ingestion service
- [x] Event validation and deduplication
- [x] Safe conflict handling (`ON CONFLICT DO NOTHING`)
- [x] Read/write tests

## Phase 3 — Analytics ✅  ([history](docs/history/phase-3-analytics/history.md))
- [x] Active-user aggregation
- [x] Funnel calculation
- [x] Cohort retention
- [x] Engagement trends
- [x] Validate against hand-checked examples
- [x] Expose through FastAPI (open until Phase 5 adds auth)

## Phase 4 — Churn model ✅  ([history](docs/history/phase-4-churn-model/history.md))
- [x] Document label and horizon
- [x] Leakage-aware features
- [x] Baseline model
- [x] Preprocessing inside a pipeline
- [x] Evaluation with baseline comparison
- [x] Error and class-imbalance review
- [x] Save model, schema, version metadata
- [x] Inference service and tests (endpoint now requires sign-in since Phase 5)
- [x] Post-phase review passes: two independent code reviews, all findings fixed and logged in the history; data regenerated and model retrained

## Phase 5 — Authentication & authorization ✅  ([history](docs/history/phase-5-auth/history.md))
- [x] Early hardening (not counted): RLS enabled on all tables and `anon`/`authenticated` grants revoked (migration `0002`, applied on Supabase, tested)
- [x] Design spec written and spike results recorded: [docs/superpowers/specs/2026-10-29-phase5-auth-design.md](docs/superpowers/specs/2026-10-29-phase5-auth-design.md) and plan [docs/superpowers/plans/2026-10-29-phase5-auth.md](docs/superpowers/plans/2026-10-29-phase5-auth.md) (not counted)
- [x] Google OAuth in Supabase and Google Cloud (Web client, Testing-mode consent screen, Email provider and anonymous sign-ins off)
- [x] Redirect URLs (local; `http://localhost:8501/**`; the deployed URL is added in Phase 7)
- [x] Streamlit sign-in/sign-out (PKCE; real sign-in, sign-out and reload checked by hand)
- [x] Token verification in FastAPI (`core/security.py`, forged-token matrix)
- [x] Owner-only access for private data (`/me`, `/me/reports`, `db/reports.py`)
- [x] Document RLS/backend authorization boundary (doc 06 section 6.4a)
- [x] Missing/expired/invalid/wrong-user tests (`test_security.py`, `test_authorization.py`, `test_me_api.py`, `test_reports.py`)
- [x] `POST /events` protected by a service key (`test_events_api.py`)

## Phase 6 — Dashboard ✅  ([history](docs/history/phase-6-dashboard/history.md))
Spec: [docs/superpowers/specs/2026-10-30-phase6-dashboard-design.md](docs/superpowers/specs/2026-10-30-phase6-dashboard-design.md) · plan: [docs/superpowers/plans/2026-10-30-phase6-dashboard.md](docs/superpowers/plans/2026-10-30-phase6-dashboard.md) · executed subagent-driven on branch `phase-6-dashboard`; every task gets an independent review. Counted items below exclude the deferred saved views (7 total). A page is ticked when built, tested and independently reviewed; the user ran the real app against the real API on 2026-10-30 and approved it.
- [x] Backend: `GET /churn/at-risk` ranked list, event-id-keyed cache, read-first `/me` profile (Tasks 1-2, not counted)
- [x] Overview page
- [x] Funnel page
- [x] Retention page (sortable cell-details table)
- [x] Engagement page
- [x] Churn-risk page (ranked list with Sort by: highest risk, lowest risk, customer ID; numeric rank and score columns)
- [x] Connected to FastAPI (gate calls `GET /me` on every rerun; five pages fetch through the cached data layer; verified live by the user)
- [x] Loading, empty, error states (shared `states.py` with fixed messages and Retry, used by every page)
- Saved views (optional, P1): **deferred**, not counted. `/me/reports` already exists; the UI can follow later.

## Phase 6b — Bring your own data (uploads) ✅  ([history](docs/history/phase-6-dashboard/history.md#phase-6b--bring-your-own-data-uploads))
Spec: [docs/superpowers/specs/2026-11-01-phase6b-uploads-design.md](docs/superpowers/specs/2026-11-01-phase6b-uploads-design.md) · plan: [docs/superpowers/plans/2026-11-01-phase6b-uploads.md](docs/superpowers/plans/2026-11-01-phase6b-uploads.md) · executed subagent-driven on branch `phase-6b-uploads`; every task independently reviewed. Merged into `main` on 2026-11-02.
- [x] Datasets table and migration `0003`, dataset-scoped queries, ownership rules (404 for others' ids)
- [x] `?dataset_id=` on analytics and churn routes; dataset-keyed churn cache
- [x] CSV parsing and `POST /datasets/check` (limits, scoped 422, approximate-signup warning)
- [x] Import (mapping, derived signup, one transaction, global cap), list and delete
- [x] Data selector, dataset- and user-keyed frontend caches, banner and notes
- [x] Upload data page
- [x] Churn on uploads trained and backtested on the file's own history (JSON model, floors, Retry)
- [x] Purge script (`scripts/purge_uploads.py`), docs, progress
- Not counted: whole-branch review done (ready with fixes; fix round and re-review done, plus a guard for files with no usable rows); test files for the run-through prepared in `data/processed/trial/`; merged with the user's approval on 2026-11-02. Import timing on the real Supabase project was measured 2026-11-01 (50,000 events plus 10,000 customers in 6.7 s; limits stand).

## Phase 7 — Quality & documentation 🟡  ([history](docs/history/phase-7-quality-and-docs/history.md))
Split in two (decided 2026-11-02): **7a** quality, security and docs, local only (the first 9 items); **7b** deploy (the last item), with its own spec later. 7a spec: [docs/superpowers/specs/2026-11-03-phase7a-quality-design.md](docs/superpowers/specs/2026-11-03-phase7a-quality-design.md) · plan: [docs/superpowers/plans/2026-11-03-phase7a-quality.md](docs/superpowers/plans/2026-11-03-phase7a-quality.md) · executed subagent-driven on branch `phase-7a-quality`; every task independently reviewed. Merged into `main` on 2026-11-03.
- [x] Unit/integration tests (coverage table in doc 08 section 8.7; new end-to-end events-to-analytics test)
- [x] Duplicate ingestion and malformed payload tests (existing; failed-write test added: no 2xx, no partial rows)
- [x] Analytics known-example tests
- [x] Auth and ownership tests
- [x] Inference validation and model-loading tests
- [x] Architecture and schema docs final (doc 03 module diagram, doc 05 ER diagram)
- [x] Actual model evaluation documented (model card re-checked against a fresh seeded training run)
- [x] Screenshots and setup instructions (seven screenshots in `docs/images/`, sign-in email removed; README followed from a fresh clone, gaps fixed)
- [x] Secrets/logging/data-exposure review (doc 06 section 6.6: no secrets in history, logs and errors checked, pip-audit clean, CORS default empty)
- [ ] Deploy after local workflow is reliable (Phase 7b)
- Done in 7a (not counted): deferred minors from Phases 5, 6 and 6b triaged; cheap ones fixed (no-signup uploads, transient database errors, duplicate headers, 422 scope, selection after a failed list, preview history and others), the rest listed with reasons in doc 08 section 8.6 Known limitations.
- Done after 7a, before 7b (not counted; merged into `main` 2026-11-06): OS-following light and dark theme with shared chart colours; the Upload page renamed **Data & Uploads**; idle sign-out (`IDLE_TIMEOUT_MINUTES`, default 30); a wait for a sleeping API on first load (`API_WAKE_SECONDS`, off by default, set about 45 in the deployment); column matching for CSVs whose headers are not ours (`columns` form field on check and import); `PLAN.md` and `docs/superpowers/` no longer tracked. Column matching was tried by hand on `data/processed/trial/4_own_column_names.csv`. The wake-up wait is untested against a real Render service.
- For 7b (not counted): set `API_WAKE_SECONDS` on the deployed frontend and confirm a real cold start fits it; add the deployed app URL to Supabase's redirect list and the Google client origins; keep the Google consent screen in Testing with named test users (decided); set `CORS_ORIGINS` only if a browser calls the API; optional open-access setting (`ALLOW_ANY_GOOGLE_USER`) and GitHub sign-in; move `ALLOWED_EMAILS` and keys into the host's secret store; verify the `app.py` page registration on the real app (AppTest cannot navigate callable pages); apply migration `0003` to the Supabase project (`alembic upgrade head`, with the user's approval) before the deployed app uses uploads.

## How to maintain this file
When a task lands: tick its box, update the phase's `Done / Total` in the summary, and add the details to that phase's `history.md`.
