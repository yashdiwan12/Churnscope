# History — Phase 0: Setup

**Status:** done · **Started:** 2026-10-22

## Done
- Reviewed `PLAN.md`; mapped plan structure to `backend/` + `frontend/`.
- Scaffolded repo: `backend/app/{api/routes,core,db,schemas,services,ml/artifacts}`, `backend/{migrations,tests}`, `frontend/pages`, `notebooks/`, `data/`, `docs/`.
- Added `.gitignore`, `.env.example`, root `README.md`, `data/README.md` stub.
- Wrote docs 01–10 and `guide.md`; created per-phase `history.md` files.

- 2026-10-23: scaffolded `backend/` and `frontend/` as uv projects (`pyproject.toml` + `uv.lock`), Python 3.12.
  - Backend deps: fastapi, uvicorn, sqlalchemy, psycopg[binary], pydantic-settings, pyjwt, cryptography, pandas, numpy, scikit-learn, joblib, httpx, alembic; dev: pytest, pytest-cov, ruff.
  - Frontend deps: streamlit, plotly, pandas, httpx; dev: ruff.
- Added minimal FastAPI app (`backend/app/main.py`, `core/config.py`, `api/routes/health.py`) and `tests/test_health.py`.
- Added minimal Streamlit page (`frontend/app.py`) that checks API `/health`.
- Added GitHub Actions CI (`.github/workflows/ci.yml`): ruff + pytest for backend, ruff for frontend.
- Added root `progress.md` tracker.
- Renamed project ProductPulse → Churnscope; moved to its own git repo (`git init`, branch `main`); secret scan clean (only the `.env.example` placeholder).
- Initial commit tagged `v0.1-phase0`.

## Evidence
- `uv run pytest -q` (backend): 1 passed. `ruff check` / `ruff format --check`: clean in both projects.
- First `uv add` timed out on PyPI; retried with `UV_HTTP_TIMEOUT=120` and succeeded.
- Note: FastAPI TestClient emits a Starlette deprecation warning about `httpx`; revisit when upgrading.

- Selected IBM Telco Customer Churn as the public dataset; documented source, unstated licence, and limitations in `data/README.md`.

## Decisions
- Synthetic event log + separate public churn dataset (no fabricated timestamps).
- Backend-enforced ownership, RLS as defence-in-depth.
- Render (API) + Streamlit Community Cloud deployment target.
- 2026-10-23 tech stack finalised: uv + pyproject.toml (separate backend/frontend projects), Python 3.12, Pandas, SQL aggregation + Pandas post-processing, psycopg 3, Alembic, PyJWT, httpx, joblib, Ruff, GitHub Actions. See [Overview](../../01-overview.md).

## Open items
