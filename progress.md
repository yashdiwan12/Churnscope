# Churnscope — Progress

Live tracker of implementation progress per phase. Detailed notes, decisions, and evidence live in each phase's `docs/history/<phase>/history.md`; the phase summary table is in [docs/10-project-history.md](docs/10-project-history.md).

**Legend:** ✅ done · 🟡 in progress · ⬜ not started · Updated: 2026-10-24

## Summary

| Phase | Milestone | Status | Done / Total |
|---|---|---|---|
| 0 | Setup | ✅ Done | 10 / 10 |
| 1 | Data & metric definitions | 🟡 In progress | 5 / 6 |
| 2 | Database & ingestion | 🟡 In progress | 6 / 7 |
| 3 | Analytics | ⬜ Not started | 0 / 6 |
| 4 | Churn model | ⬜ Not started | 0 / 8 |
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

## Phase 1 — Data & metric definitions 🟡  ([history](docs/history/phase-1-data-and-metrics/history.md))
- [ ] Inspect schema, types, missing values, duplicates, timestamps (synthetic log validated; Telco CSV still to download and inspect)
- [x] Write data dictionary
- [x] Define qualifying activity events
- [x] Define funnel steps and conversion rules
- [x] Define cohort and retention periods
- [x] Validate metrics on hand-checkable examples

## Phase 2 — Database & ingestion 🟡  ([history](docs/history/phase-2-database-and-ingestion/history.md))
- [ ] Supabase project and PostgreSQL schema (schema done and verified on local Postgres via Docker; Supabase project still to be created by the user)
- [x] SQLAlchemy configured with driver
- [x] Tables, constraints, initial indexes (Alembic)
- [x] Ingestion service
- [x] Event validation and deduplication
- [x] Safe conflict handling (`ON CONFLICT DO NOTHING`)
- [x] Read/write tests

## Phase 3 — Analytics ⬜  ([history](docs/history/phase-3-analytics/history.md))
- [ ] Active-user aggregation
- [ ] Funnel calculation
- [ ] Cohort retention
- [ ] Engagement trends
- [ ] Validate against hand-checked examples
- [ ] Expose through FastAPI

## Phase 4 — Churn model ⬜  ([history](docs/history/phase-4-churn-model/history.md))
- [ ] Document label and horizon
- [ ] Leakage-aware features
- [ ] Baseline model
- [ ] Preprocessing inside a pipeline
- [ ] Evaluation with baseline comparison
- [ ] Error and class-imbalance review
- [ ] Save model, schema, version metadata
- [ ] Inference service and tests

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
