# Churnscope

Product analytics and churn-intelligence platform: turns user-activity events into engagement, funnel, retention, and churn-risk insights. See [PLAN.md](PLAN.md) for scope and [docs/guide.md](docs/guide.md) for the documentation map.

## Status

Phases 0-3 are done (setup, data and metric definitions, database and idempotent ingestion, analytics API). Churn model, authentication, dashboard, and deployment are still to come. Live tracker: [progress.md](progress.md).

The event data is **synthetic** (seeded generator); funnel and retention figures reflect its assumptions, not real customer behaviour. The IBM Telco dataset is used only as a supplementary tabular churn dataset (see [data/README.md](data/README.md)).

## Quick start

```bash
cp .env.example .env                                   # set DATABASE_URL
docker compose up -d --wait                            # local Postgres on :5433
cd backend && uv sync
uv run alembic upgrade head
uv run python scripts/generate_events.py               # synthetic events -> data/processed/
PYTHONPATH=. uv run python scripts/load_events.py ../data/processed/events.csv
uv run uvicorn app.main:app --reload                   # API docs at http://localhost:8000/docs
uv run pytest -q
```

Full instructions: [docs/09-local-development.md](docs/09-local-development.md).
