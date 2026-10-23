# Churnscope — Documentation guide

Start here. Churnscope turns product-activity events into engagement, funnel, retention, and churn-risk insights (FastAPI + PostgreSQL/Supabase + scikit-learn + Streamlit).

## Reading paths

| If you want to… | Read |
|---|---|
| Understand the project in 5 minutes | [1. Overview](01-overview.md) → [2. Architecture](02-architecture.md) |
| Understand how it works internally | [3. System design](03-system-design.md) → [4. Request flows](04-request-flows.md) → [5. Data model](05-data-model.md) |
| Review safety | [6. Security](06-security.md) |
| Run it locally | [9. Local development](09-local-development.md) |
| Deploy or operate it | [7. Infrastructure](07-infrastructure-and-deployment.md) → [8. Runbook](08-operations-runbook.md) |
| See what's built and when | [10. Project history](10-project-history.md) |

## How the docs are maintained

- **Status tags** (`[Planned]`, `[In progress]`, `[Built]`) mark what is real. Docs describe the target design; don't assume a feature exists unless tagged `[Built]`.
- **Phase history**: each phase has `docs/history/<phase>/history.md` recording what was done, decisions, and evidence. Update it as work lands, and update the table in doc 10.
- **Honesty rule**: no performance, scale, or accuracy claims until measured and recorded.

## Repository map

```
backend/    FastAPI app, services, ML, migrations, tests
frontend/   Streamlit + Plotly dashboard
data/       Dataset notes (raw/processed git-ignored)
notebooks/  Exploration
docs/       Documentation + per-phase history
progress.md Live per-phase task tracker
PLAN.md     Original implementation plan (source of truth for scope)
```

## Build order (from PLAN.md)

Datasets → metric definitions → Pandas analytics → DB + ingestion → API → churn model → inference → auth → dashboard → integration/security tests → docs + screenshots → deploy.

## Where to go next

Phase 0 open items are listed in [history/phase-0-setup/history.md](history/phase-0-setup/history.md).
