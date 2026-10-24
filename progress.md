# Churnscope — Progress

Live tracker of implementation progress per phase. Detailed notes, decisions, and evidence live in each phase's `docs/history/<phase>/history.md`; the phase summary table is in [docs/10-project-history.md](docs/10-project-history.md).

**Legend:** ✅ done · 🟡 in progress · ⬜ not started · Updated: 2026-10-25

## Summary

| Phase | Milestone | Status | Done / Total |
|---|---|---|---|
| 0 | Setup | ✅ Done | 10 / 10 |
| 1 | Data & metric definitions | ✅ Done | 6 / 6 |
| 2 | Database & ingestion | ✅ Done | 7 / 7 |
| 3 | Analytics | ✅ Done | 6 / 6 |
| 4 | Churn model | ✅ Done | 8 / 8 |
| 5 | Authentication & authorization | ⬜ Not started | 0 / 7 |
| 6 | Dashboard | ⬜ Not started | 0 / 8 |
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

## Phase 5 — Authentication & authorization ⬜  ([history](docs/history/phase-5-auth/history.md))
- [ ] Google OAuth in Supabase and Google Cloud
- [ ] Redirect URLs (local and deployed)
- [ ] Streamlit sign-in/sign-out
- [ ] Token verification in FastAPI
- [ ] Owner-only access for private data
- [ ] Document RLS/backend authorization boundary
- [ ] Missing/expired/invalid/wrong-user tests

## Phase 6 — Dashboard ⬜  ([history](docs/history/phase-6-dashboard/history.md))
- [ ] Overview page
- [ ] Funnel page
- [ ] Retention page
- [ ] Engagement page
- [ ] Churn-risk page
- [ ] Connected to FastAPI
- [ ] Loading, empty, error states
- [ ] Saved views (optional, P1)

## Phase 7 — Quality & documentation ⬜  ([history](docs/history/phase-7-quality-and-docs/history.md))
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

## How to maintain this file
When a task lands: tick its box, update the phase's `Done / Total` in the summary, and add the details to that phase's `history.md`.
