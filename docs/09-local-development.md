# 9. Local development

> Backend setup, migrations, synthetic data, ingestion, analytics API and tests are real (Phases 0-3). Auth, churn prediction and the dashboard pages are still to come. Tag changes in [history](10-project-history.md).

## 9.1 Prerequisites

Python 3.12, [uv](https://docs.astral.sh/uv/), Git, Docker (local Postgres for development and DB tests), and a Supabase project (used from Phase 2). A Google OAuth client configured in Supabase is needed from Phase 5.

Supabase note: use the **Session pooler** connection string; the direct `db.<ref>.supabase.co` host is IPv6-only and may not resolve on home networks. Never point the test suite at Supabase: its fixture drops the `public` schema, so tests use `TEST_DATABASE_URL` (default: the local Docker database).

## 9.2 Setup

```bash
git clone <repo> && cd Churnscope
(cd backend && uv sync)      # creates backend/.venv from pyproject.toml + uv.lock
(cd frontend && uv sync)
cp .env.example .env        # fill in values; never commit .env
```

## 9.3 Run

```bash
# Backend (from backend/)
cd backend && uv run uvicorn app.main:app --reload --port 8000   # docs at /docs

# Frontend (second terminal)
cd frontend && uv run streamlit run app.py                       # http://localhost:8501
```

## 9.4 Data

```bash
docker compose up -d --wait                        # local Postgres on :5433
cd backend
export DATABASE_URL=postgresql+psycopg://churnscope:churnscope@localhost:5433/churnscope
uv run alembic upgrade head                        # create schema
uv run python scripts/generate_events.py --seed 42 # synthetic events -> data/processed/
PYTHONPATH=. uv run python scripts/load_events.py ../data/processed/events.csv   # idempotent load
```

Public churn dataset: download per `data/README.md` into `data/raw/` (git-ignored).

## 9.5 Tests

```bash
cd backend && uv run pytest -q   # DB tests need `docker compose up -d`; they skip otherwise
cd backend && uv run ruff check . && uv run ruff format --check .
```

Coverage targets: ingestion (valid/invalid/duplicate), analytics (hand-checked cases), auth (missing/expired/wrong user), ML (schema parity, no leakage).

## 9.6 Conventions

- Business logic in `services/`, SQL in `db/repositories.py`, no logic in routes.
- UTC everywhere; timezone-aware datetimes.
- Small commits per milestone task; update the phase `history.md` when a phase item completes.
- Never commit `.env`, secrets, raw data, or model binaries beyond the small versioned artifact.
