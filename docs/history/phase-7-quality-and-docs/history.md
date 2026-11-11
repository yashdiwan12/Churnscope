# History — phase-7-quality-and-docs

**Status:** 7a done, merged into `main` on 2026-11-03 · 7b (deploy) not started

Phase 7 is split: **7a** quality, security and docs (local only) and **7b** deploy, which gets its own spec. 7a spec: [2026-11-03-phase7a-quality-design.md](../../superpowers/specs/2026-11-03-phase7a-quality-design.md); plan: [2026-11-03-phase7a-quality.md](../../superpowers/plans/2026-11-03-phase7a-quality.md). Executed subagent-driven on branch `phase-7a-quality`; every task was independently reviewed.

## Done

- **Test coverage and missing tests** (Task 1): doc 08 section 8.7 maps every PLAN.md section 13 test item to its test. New `test_end_to_end.py` posts hand-built events through `POST /events` and checks overview, funnel and retention against hand-calculated numbers. New `test_failed_writes.py` shows a database error on each write path (`POST /events`, `POST /datasets`, `DELETE /datasets/{id}`, `POST /me/reports`) answers 503 and leaves no partial rows. The model card was re-checked against a fresh seeded training run and matches.
- **Backend fixes** (Task 2, review items 1-3, 5, 6, 8-11, 13 of the spec): an upload with no signup event is scored `unavailable` / `no_signup` instead of crashing; transient database errors during scoring answer 503 and are never stored as `failed`; a replace during `/score` gives 404; the import answers 201 with the pre-scoring body; the upload body is read before a database connection is taken; exact duplicate headers are rejected; the scoped 422 handler matches only `/datasets` paths; `.` and `..` filenames get the default name; the purge script prints one error line and exits 1.
- **Frontend and diagram fixes** (Task 3): the chosen dataset survives a failed `GET /datasets`; the Churn Risk page shows the "needs a signup event" message; the Upload preview counts history from exact timestamps; doc 03's module diagram and doc 05's ER diagram are current.
- **Known limitations and security pass** (Task 4): doc 08 section 8.6 lists every accepted minor with its reason. Doc 06 section 6.6: a secret scan of all commits found no real secret; every logging call and error response was checked; `pip-audit` found nothing; the `security-review` skill found nothing; the CORS default is now empty (the dashboard calls the API from its server).
- **Screenshots** (Task 6): seven PNGs in `docs/images/` (sign-in, overview, funnel, retention, engagement, churn risk, upload), all demo data; the signed-in email line was blanked before committing. Linked from the README.
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

  The table is the first run. After the README fixes, a second fresh clone followed the fixed text step by step with the same results (backend 418 passed, 2 skipped; frontend 203 passed). Also added: bash/PowerShell note, port-in-use note. Status paragraph rewritten and a "What it does" section with image links added (images arrive in Task 6). Existing coverage from earlier phases (ingestion, analytics, model and artifact, auth/ownership, RLS tests; GitHub CI on every push) is the starting point for the final audit.

## Decisions
- Phase 7 split into 7a (local) and 7b (deploy); 7b keeps the Google consent screen in Testing mode with named test users (2026-11-02).
- An upload with no signup event is scoring method `unavailable` with reason `no_signup`, an existing method, so no new value reaches the frontend.
- The model card's Random Forest row stays on the database-trained numbers; the CSV run differs in the third decimal, which the card already notes.
- A replace during the import's own scoring step still answers 201 (the import is committed); only `POST /datasets/{id}/score` answers 404.
- Screenshot file names follow what was captured (`sign-in.png`, `churn-risk.png`, plus `engagement.png`).

## Pre-deploy polish (2026-11-04 to 2026-11-06, merged into `main` locally)
- Theme: `[theme.light]` and `[theme.dark]` in `frontend/.streamlit/config.toml` with no `base`, so the OS picks the mode; chart colours shared in `frontend/theme.py` (blue series, red at-risk, blue ramp for the heatmap), checked with the colour-blindness validator on the light, dark and card surfaces. The lightest heatmap step is low contrast on purpose: it means near zero.
- Page renamed **Data & Uploads** (URL stays `/upload`).
- Idle sign-out: a rerun checks `last_seen`; past `IDLE_TIMEOUT_MINUTES` (default 30, 0 = off) the refresh token is revoked and the user lands on sign-in with a notice. An untouched open tab cannot notice until its next click.
- Cold start: `GET /me` is retried every 3 s for `API_WAKE_SECONDS` while the API answers unavailable, with a waking-up notice. Off by default so a down local API fails fast.
- Column matching: optional `columns` form field on `/datasets/check` and `/datasets`; the page reads the header row and shows dropdowns when a required name is missing. A mapped header beats a column already named the same; unknown or repeated headers are refused with `bad_columns`.
- `PLAN.md` and `docs/superpowers/` untracked and git-ignored (local ideation notes); links to them from the docs are left as they are, by decision.
- Backend 436 passed, 2 skipped; frontend 226 passed.

## Results
- Backend: 418 passed, 2 skipped (opt-in timing checks); frontend: 203 passed; ruff clean. All against local Docker Postgres; Supabase was not touched.

## Open
- Phase 7b: deployed; what is left is the live check list (doc 07 section 7.8). See the 7b section below.
- Accepted minors: doc 08 section 8.6.

## Phase 7b - Deploy (2026-11-06)
- API on Render (`churnscope-api`, free tier), dashboard on Streamlit Community Cloud (`churnscope-analytics`), both from `main` of the public repo; database and Google sign-in on the existing Supabase project. The full setup and the values are in doc 07 section 7.7.
- Render start command: a bare `uvicorn` failed with `command not found` (status 127) because the packages are in `backend/.venv`; fixed with `uv run --no-sync uvicorn ...`. The server needed about 23 s to start, so the dashboard's wait is set to 60 s.
- Sign-in on Streamlit Cloud took three tries. The app runs in a sandboxed iframe: a `_self` link kept Google's page inside the frame (Google answered 403), a `_top` link was blocked by the sandbox (the click did nothing), and `_blank` (a new tab) works. A web search confirmed the sandbox does not allow top navigation and the platform gives no way to change it. Same-window sign-in would need the dashboard hosted outside an iframe or `st.login`; neither was chosen.
- After Google, the first return went to `localhost:8501/?code=...`: the dashboard address was not on Supabase's redirect list, so Supabase fell back to its Site URL. Fixed by listing the address (with and without `/**`) and setting the Site URL.
- Google's consent screen stays in Testing; every person who signs in is a test user and on Render's `ALLOWED_EMAILS`.
- Decisions: `INGEST_API_KEY` and `CORS_ORIGINS` unset on Render; no migration on deploy; Python not pinned on Render (3.14, as local).
- Not yet checked on the live stack: a non-listed account, a cold start, all five pages, an upload, idle sign-out (doc 07 section 7.8).
