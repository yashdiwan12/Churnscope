# Churnscope

Product analytics and churn-intelligence platform: turns user-activity events into engagement, funnel, retention, and churn-risk insights. See [PLAN.md](PLAN.md) for scope and [docs/guide.md](docs/guide.md) for the documentation map.

## What it does

A signed-in user sees a Streamlit dashboard over product-event data, backed by a FastAPI API: **Overview** (active users, events, trends), **Funnel** (step conversion), **Retention** (cohort grid), **Engagement** (activity and feature use) and **Churn Risk** (customers ranked by predicted churn, sortable). **Upload data** lets a user import their own events CSV, map its event names, and see the same pages for their file only, with churn scored by a method trained on that file.

Screenshots (demo data):

![Sign-in](docs/images/sign-in.png)
![Overview](docs/images/overview.png)
![Funnel](docs/images/funnel.png)
![Retention](docs/images/retention.png)
![Engagement](docs/images/engagement.png)
![Churn risk](docs/images/churn-risk.png)
![Upload](docs/images/upload.png)

## Status

Phases 0-7a are done and merged: data and metric definitions, database and idempotent ingestion, analytics API, churn model (see the [model card](docs/model_card.md)), Google sign-in through Supabase with an email allow-list, the Streamlit dashboard, per-user CSV uploads with churn trained on the file (6b), and a quality, security and docs pass (7a: test coverage table, fixes, security review, a README checked from a fresh clone). Phase 7b (deploy to Render and Streamlit Community Cloud, Google sign-in in Testing mode with named users) is still to come. Live tracker: [progress.md](progress.md).

The event data is **synthetic** (seeded generator); funnel and retention figures reflect its assumptions, not real customer behaviour. The IBM Telco dataset is used only as a supplementary tabular churn dataset (see [data/README.md](data/README.md)).

## Quick start

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Git, Docker. Commands are bash (on Windows use Git Bash, or set `PYTHONPATH` the PowerShell way).

```bash
cp .env.example .env     # at the repo root
docker compose up -d --wait                            # local Postgres on :5433
```

Now edit `.env`. Set at least `DATABASE_URL=postgresql+psycopg://churnscope:churnscope@localhost:5433/churnscope` (the local Docker login from `docker-compose.yml`; the file's default is a placeholder) and `INGEST_API_KEY` (generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Leave `ALLOWED_EMAILS` empty until you sign in. The `SUPABASE_*` values are only needed for sign-in and the frontend; every analytics route requires a signed-in user, so without them the API runs but returns 401 (`/health` and `/docs` work).

Then set up the database, data and model. Run the backend commands from `backend/` (it reads `../.env` relative to that directory):

```bash
cd backend && uv sync
uv run alembic upgrade head
uv run python scripts/generate_events.py               # synthetic events -> data/processed/
PYTHONPATH=. uv run python scripts/load_events.py ../data/processed/events.csv   # about 40 s
PYTHONPATH=. uv run python -m app.ml.train --source db # train churn model -> app/ml/artifacts/
uv run uvicorn app.main:app --reload                   # API docs at http://localhost:8000/docs
```

In another terminal, from the repo root, run the tests (about 1 minute each; the backend's 2 skips are opt-in timing checks):

```bash
(cd backend && uv run pytest -q)
(cd frontend && uv sync && uv run pytest -q)
```

And the dashboard (needs `SUPABASE_URL` and `SUPABASE_ANON_KEY` to get past the sign-in page):

```bash
(cd frontend && uv run --env-file ../.env streamlit run app.py)   # http://localhost:8501
```

If port 8000 or 8501 is taken, pass `--port` to uvicorn or streamlit (and set `API_BASE_URL` / `APP_BASE_URL` to match).

Full instructions: [docs/09-local-development.md](docs/09-local-development.md).
