# History — phase-7-quality-and-docs

**Status:** not started

## Done

- **Fresh-clone README run** (Task 5): clone of branch `phase-7a-quality` into a scratch folder, `.env` from `.env.example` with local values, a throwaway database `churnscope_fresh` on the existing Docker Postgres (dropped afterwards; Supabase never touched). Ports 8000/8501 were busy, so 8010/8511 were used.

| Step | Worked as written | Time | Gap and fix |
|---|---|---|---|
| `cp .env.example .env` | partly | - | "set DATABASE_URL" gave no local value (example is a placeholder); `INGEST_API_KEY` not mentioned. README and doc 09 now give both |
| `docker compose up -d --wait` | yes (existing container reused) | - | - |
| `uv sync` (backend) | yes | 2 s warm | - |
| `alembic upgrade head` | yes (0001-0003) | 9 s | - |
| `generate_events.py` | yes (2000 customers, 42,847 events) | 9 s | - |
| `load_events.py` | yes | 39 s | time noted in README |
| `app.ml.train --source db` | yes (test ROC AUC 0.879) | 5 s | - |
| `uvicorn` | yes (`/health`, `/docs` 200) | - | README now says analytics routes return 401 without Supabase values |
| `uv run pytest -q` (backend) | yes, 418 passed, 2 skipped | 65 s | skips are opt-in timing checks; stated |
| frontend `uv sync` + `pytest -q` | not in README | 63 s, 203 passed | added to README |
| Streamlit start | not in README | - | added; page and health respond; sign-in is the user's step |
| doc 09 `curl /churn/predict` | no, 401 | - | doc now explains the bearer token |

  Also added: bash/PowerShell note, port-in-use note. Status paragraph rewritten and a "What it does" section with image links added (images arrive in Task 6). Existing coverage from earlier phases (ingestion, analytics, model and artifact, auth/ownership, RLS tests; GitHub CI on every push) is the starting point for the final audit.

## Decisions

## Notes
- Inherited items are listed at the end of the Phase 7 section in `progress.md`.
