# Churnscope — Progress

Live tracker of implementation progress per phase. Detailed notes, decisions, and evidence live in each phase's `docs/history/<phase>/history.md`; the phase summary table is in [docs/10-project-history.md](docs/10-project-history.md).

**Legend:** ✅ done · 🟡 in progress · ⬜ not started · Updated: 2026-10-30 · Phase 6 in progress on branch `phase-6-dashboard` (not merged): backend 270 and frontend 97 tests pass locally at the last check

## Summary

| Phase | Milestone | Status | Done / Total |
|---|---|---|---|
| 0 | Setup | ✅ Done | 10 / 10 |
| 1 | Data & metric definitions | ✅ Done | 6 / 6 |
| 2 | Database & ingestion | ✅ Done | 7 / 7 |
| 3 | Analytics | ✅ Done | 6 / 6 |
| 4 | Churn model | ✅ Done | 8 / 8 |
| 5 | Authentication & authorization | ✅ Done | 8 / 8 |
| 6 | Dashboard | 🟡 In progress | 4 / 7 |
| 6b | Bring your own data (uploads) | ⬜ Not started (design pending) | — |
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
- [x] Inference service and tests (endpoint open until Phase 5 adds auth)
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

## Phase 6 — Dashboard 🟡  ([history](docs/history/phase-6-dashboard/history.md))
Spec: [docs/superpowers/specs/2026-10-30-phase6-dashboard-design.md](docs/superpowers/specs/2026-10-30-phase6-dashboard-design.md) · plan: [docs/superpowers/plans/2026-10-30-phase6-dashboard.md](docs/superpowers/plans/2026-10-30-phase6-dashboard.md) · executed subagent-driven on branch `phase-6-dashboard`; every task gets an independent review. Counted items below exclude the deferred saved views (7 total). A page is ticked when built, tested and independently reviewed; the real-API run-through with the user is Task 9.
- [x] Backend: `GET /churn/at-risk` ranked list, event-id-keyed cache, read-first `/me` profile (Tasks 1-2, not counted)
- [x] Overview page (built, reviewed; real-API check pending in Task 9)
- [x] Funnel page (built, reviewed; real-API check pending in Task 9)
- [x] Retention page (built, reviewed; real-API check pending in Task 9)
- [x] Engagement page (built, reviewed; real-API check pending in Task 9)
- [ ] Churn-risk page (built, independent review in progress)
- [ ] Connected to FastAPI (ticks after the Task 9 real-API run-through; the gate, data layer and four pages already call the API in tests with a fake)
- [ ] Loading, empty, error states (ticks with the Churn-risk page; the shared states module and the four built pages already have them)
- Saved views (optional, P1): **deferred**, not counted. `/me/reports` already exists; the UI can follow later.

## Phase 6b — Bring your own data (uploads) ⬜  (design pending)
Users upload their own events and get the analytics and a churn report on them. Needs its own design before any code: an ownership migration, dataset-scoped queries and cache keys (the Phase 6 shared cache is safe only while data is shared), CSV validation and event-name mapping, size limits for the free database tier, and how to score a user's data with a model trained on synthetic data. Starts only after Phase 6 ships.

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
- Inherited from earlier phases (not counted): add the deployed app URL to Supabase's redirect list and the Google client origins; publish the Google consent screen (needs a domain, privacy page, home page) or stay in Testing with named test users; optional open-access setting (`ALLOW_ANY_GOOGLE_USER`) and GitHub sign-in; move `ALLOWED_EMAILS` and keys into the host's secret store; triage the deferred minors from the Phase 5 and Phase 6 logs; verify the `app.py` page registration on the real app (AppTest cannot navigate callable pages).

## How to maintain this file
When a task lands: tick its box, update the phase's `Done / Total` in the summary, and add the details to that phase's `history.md`.
