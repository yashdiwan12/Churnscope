# Churnscope — Progress

Live tracker of implementation progress per phase. Detailed notes, decisions, and evidence live in each phase's `docs/history/<phase>/history.md`; the phase summary table is in [docs/10-project-history.md](docs/10-project-history.md).

**Legend:** ✅ done · 🟡 in progress · ⬜ not started · Updated: 2026-11-02 · Phase 6b merged into `main`: backend 398 (2 opt-in timing tests skipped) and frontend 200 tests pass locally at the last full run

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
| 7 | Quality & documentation | ⬜ Not started | 0 / 10 |

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

## Phase 7 — Quality & documentation ⬜  ([history](docs/history/phase-7-quality-and-docs/history.md))
Nothing in Phase 7 is ticked: its items are a consolidated final pass. Much of the underlying coverage already exists from earlier phases (ingestion, analytics known-example, model/artifact, auth/ownership and RLS tests) and CI runs on GitHub, so the pass is mostly audit, gaps and documentation, not new test suites. Inherited items are listed after the checklist.
- [ ] Unit/integration tests
- [ ] Duplicate ingestion and malformed payload tests
- [ ] Analytics known-example tests
- [ ] Auth and ownership tests
- [ ] Inference validation and model-loading tests
- [ ] Architecture and schema docs final
- [ ] Actual model evaluation documented
- [ ] Screenshots and setup instructions
- [ ] Secrets/logging/data-exposure review
- [ ] Deploy after local workflow is reliable
- Inherited from earlier phases (not counted): add the deployed app URL to Supabase's redirect list and the Google client origins; publish the Google consent screen (needs a domain, privacy page, home page) or stay in Testing with named test users; optional open-access setting (`ALLOW_ANY_GOOGLE_USER`) and GitHub sign-in; move `ALLOWED_EMAILS` and keys into the host's secret store; triage the deferred minors from the Phase 5 and Phase 6 logs; verify the `app.py` page registration on the real app (AppTest cannot navigate callable pages); apply migration `0003` to the Supabase project (`alembic upgrade head`, with the user's approval) before the deployed app uses uploads; triage the Phase 6b deferred minors listed in its history.

## How to maintain this file
When a task lands: tick its box, update the phase's `Done / Total` in the summary, and add the details to that phase's `history.md`.
