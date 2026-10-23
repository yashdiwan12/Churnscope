# 9. Local development

> Commands below describe the target workflow; they become real as Phase 0/2 land. Tag changes in [history](10-project-history.md).

## 9.1 Prerequisites

Python 3.12, [uv](https://docs.astral.sh/uv/), Git, a Supabase project (or local Postgres), Google OAuth client configured in Supabase.

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
python -m app.scripts.generate_events --seed 42   # synthetic events (planned)
python -m app.scripts.load_events                  # idempotent load
```

Public churn dataset: download per `data/README.md` into `data/raw/` (git-ignored).

## 9.5 Tests

```bash
cd backend && uv run pytest -q
cd backend && uv run ruff check . && uv run ruff format --check .
```

Coverage targets: ingestion (valid/invalid/duplicate), analytics (hand-checked cases), auth (missing/expired/wrong user), ML (schema parity, no leakage).

## 9.6 Conventions

- Business logic in `services/`, SQL in `db/repositories.py`, no logic in routes.
- UTC everywhere; timezone-aware datetimes.
- Small commits per milestone task; update the phase `history.md` when a phase item completes.
- Never commit `.env`, secrets, raw data, or model binaries beyond the small versioned artifact.
