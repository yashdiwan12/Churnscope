# 9. Local development

> Everything through Phase 6b is real: backend, data, model, Google sign-in and authorization, the Streamlit dashboard and uploads (run `alembic upgrade head` to get migration `0003`). Phase 7a (quality, security, docs) is done; deployment (7b) is still to come. Tag changes in [history](10-project-history.md).

## 9.1 Prerequisites

Python 3.12, [uv](https://docs.astral.sh/uv/), Git, Docker (local Postgres for development and DB tests), and a Supabase project (used from Phase 2). A Google OAuth client configured in Supabase is needed from Phase 5.

Supabase note: use the **Session pooler** connection string; the direct `db.<ref>.supabase.co` host is IPv6-only and may not resolve on home networks. Never point the test suite at Supabase: its fixture drops the `public` schema, so tests use `TEST_DATABASE_URL` (default: the local Docker database).

## 9.2 Setup

```bash
git clone <repo> && cd Churnscope
(cd backend && uv sync)      # creates backend/.venv from pyproject.toml + uv.lock
(cd frontend && uv sync)
cp .env.example .env        # repo root; fill in values; never commit .env
```

For local use set at least `DATABASE_URL=postgresql+psycopg://churnscope:churnscope@localhost:5433/churnscope` (the example file's value is a placeholder) and `INGEST_API_KEY` (`python -c "import secrets; print(secrets.token_urlsafe(32))"`). `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `SUPABASE_ANON_KEY` and `ALLOWED_EMAILS` are needed only to sign in; without them the API still starts (`/health`, `/docs`) but every analytics route answers 401. The backend reads `../.env`, resolved against the working directory, so run backend commands (uvicorn, alembic, scripts, pytest) from `backend/`. Commands below are bash; on Windows use Git Bash (or set `$env:PYTHONPATH='.'` in PowerShell).

## 9.3 Run

First-time flow:

```mermaid
flowchart LR
    dc["docker compose up<br/>Postgres :5433"] --> mig["alembic upgrade head<br/>create schema"]
    mig --> gen["generate_events.py<br/>seeded synthetic data"]
    gen --> load["load_events.py<br/>idempotent ingestion"]
    load --> api["uvicorn app.main:app<br/>API on :8000"]
    api --> ui["streamlit run app.py<br/>:8501"]
    dc --> tst["pytest<br/>DB tests use the same Postgres"]
```

```bash
# Backend (from backend/)
cd backend && uv run uvicorn app.main:app --reload --port 8000   # docs at /docs

# Frontend (second terminal)
cd frontend && uv run --env-file ../.env streamlit run app.py    # http://localhost:8501 (sign-in needs SUPABASE_URL and SUPABASE_ANON_KEY)
```

Launch the frontend from the `frontend/` directory: Streamlit reads `frontend/.streamlit/config.toml` (minimal toolbar, no error details shown to users, no usage tracking) from the directory it is started in, so starting it from elsewhere skips those settings.

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

## 9.4a Uploads

Uploads need nothing beyond `uv sync`: `python-multipart` (multipart parsing for `POST /datasets/check` and `POST /datasets`) is a dependency in `backend/pyproject.toml`, and migration `0003` runs with `alembic upgrade head`. The Streamlit uploader's 5 MB limit is `server.maxUploadSize = 5` in `frontend/.streamlit/config.toml`, read only when Streamlit is started from `frontend/`. Sign in, open **Data & Uploads**, choose a CSV with `customer_id`, `event_name`, `event_timestamp` (and optionally `event_id`), map the event names, import, then pick **My data** in the sidebar. The page offers a template to download. Old uploads can be cleared with `scripts/purge_uploads.py` ([runbook](08-operations-runbook.md)).

## 9.4b Train the churn model

```bash
cd backend
PYTHONPATH=. uv run python -m app.ml.train --source db      # writes app/ml/artifacts/ and app/ml/reports/churn_eval.json
PYTHONPATH=. uv run python -m app.ml.train_telco            # supplementary; needs data/raw/telco_churn.csv
```

The API loads `app/ml/artifacts/churn_model.joblib` at startup (hash, schema and version checked; optionally pinned with `CHURN_MODEL_SHA256`). `/churn/predict` requires a signed-in, allow-listed user, so a bare `curl` answers `401 Not authenticated`; use the interactive docs after signing in, or call it with a Supabase access token:

```bash
curl -X POST localhost:8000/churn/predict -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' -d '{"customer_ids": ["c00100", "c00275"]}'
```

## 9.5 Tests

```bash
(cd frontend && uv run pytest -q)  # no network or database needed
(cd backend && uv run pytest -q)   # about 1 min; 2 skips are opt-in timing checks (CHURNSCOPE_TIMING=1). DB tests need Docker Postgres up; if the summary shows "skipped", it is down (`docker compose up -d`)
(cd backend && uv run ruff check . && uv run ruff format --check .)
```

Database tests use their own `churnscope_test` database on the same Postgres (created automatically; its schema is dropped on every run), so running the tests never touches data you loaded into `churnscope`. Under `CI` a missing database fails the run instead of skipping.

Coverage targets: ingestion (valid/invalid/duplicate), analytics (hand-checked cases), auth (missing/expired/wrong user), ML (schema parity, no leakage).

## 9.6 Conventions

- Business logic in `services/`, SQL in `db/repositories.py`, no logic in routes.
- UTC everywhere; timezone-aware datetimes.
- Small commits per milestone task; update the phase `history.md` when a phase item completes.
- Never commit `.env`, secrets, raw data, or model binaries beyond the small versioned artifact.
