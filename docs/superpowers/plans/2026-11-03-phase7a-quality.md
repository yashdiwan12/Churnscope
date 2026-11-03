# Phase 7a Quality, Security and Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining test gaps, fix the minor and code-review findings a user can hit, pass the security checklist, and make the README work from a fresh clone, so Phase 7b can deploy.

**Architecture:** No new subsystems. Small fixes in the existing upload routes, upload scoring, CSV parser, purge script and two Streamlit views; new tests beside the existing ones; documentation in docs 03, 05, 06, 08, 09, the README and the model card.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2, pandas, scikit-learn, Streamlit (AppTest), pytest, ruff, uv, local Docker Postgres.

**Spec:** [docs/superpowers/specs/2026-11-03-phase7a-quality-design.md](../specs/2026-11-03-phase7a-quality-design.md)

## Global Constraints

- Backend tests use `TEST_DATABASE_URL` (local Docker `churnscope_test`) only. Never run anything against Supabase, never read or print `.env`, never read the Google client secret file.
- No commit carries a `Co-Authored-By` line or any AI attribution.
- Error bodies and logs never carry file values, tokens, connection strings or tracebacks; log exception **type names** only (existing pattern: `logger.error("...: %s", type(exc).__name__)`).
- Existing user-facing copy is reused verbatim where the plan names a constant (`NO_SIGNUP`, `SHORT_HISTORY`, `SCORING_FAILED`, `CHURN_SHORT`, `CHURN_OK`).
- Commands: backend `cd backend && uv run pytest -q` and `uv run ruff check . && uv run ruff format --check .`; frontend `cd frontend && uv run pytest -q -W error` and the same ruff pair.
- Each task ends with the full backend and frontend suites green and ruff clean.

## Review Focus

1. A no-signup upload: the page must say "needs a signup event", never "scoring failed" with a Retry that cannot work (Task 2 tests both the backend result and the page).
2. A database blip in the middle of an upload flow must never be stored as a permanent file problem or turn a committed import into an error (Task 2 tests transient errors on `/score` and after import).
3. A user on a slow connection uploading a 5 MB file must not hold a pooled database connection (Task 2 test on call order).
4. A user who picked their upload must still be on it after one failed `GET /datasets` (Task 3 AppTest over three runs).
5. A CSV with a column header written twice must be rejected, not half-read (Task 2 parser test with an exact duplicate).

---

### Task 1: Traceability table, end-to-end and failed-write tests, model card re-check

**Files:**
- Create: `backend/tests/test_end_to_end.py`, `backend/tests/test_failed_writes.py`
- Modify: `docs/08-operations-runbook.md` (new section `## 8.7 Test coverage`), `docs/model_card.md` (only if numbers differ)

**Interfaces:**
- Consumes: `tests.test_analytics_api.ROWS` (import it, do not copy), the `make`-style client setup from `tests/test_events_api.py` (`INGEST_API_KEY`, `get_settings.cache_clear()`), `tests.auth_helpers.act_as_allowed_user`.
- Produces: nothing later tasks call.

- [ ] **Step 1: Write `test_events_in_analytics_out`** in `test_end_to_end.py`: POST `ROWS` (as `test_analytics_api` builds them: `event_id=f"ev{i}"`, `T00:00:00Z`) to `/events` with the service key in one request, then with an allow-listed user assert: `/analytics/overview?start=2026-01-07T00:00:00Z&end=2026-01-09T00:00:00Z` gives `active_users == 3` and `new_users == 1`; `/analytics/funnel` gives `eligible_users == 4` and step users `[4, 3, 1]` for `signup, onboarding_complete, report_created`; posting the same body again leaves those numbers unchanged (idempotent).
- [ ] **Step 2: Write `test_failed_write_is_never_2xx`** in `test_failed_writes.py`, parametrised over `POST /events`, `POST /datasets` (a valid small CSV), `DELETE /datasets/{id}` (on the user's own upload) and `POST /me/reports`. Make the write fail by monkeypatching the write function each route calls (`ingest_events`, `datasets_db.replace_upload`, `datasets_db.delete_upload`, `reports.create_report` in `app/db/reports.py`) to raise `sqlalchemy.exc.OperationalError("x", {}, Exception())`. Assert status is 503 and, after the call, the relevant table row count equals its count before the call.
- [ ] **Step 3: Run both files.** `cd backend && uv run pytest tests/test_end_to_end.py tests/test_failed_writes.py -v`. Expected: PASS (these pin existing behaviour; if one fails, the failure is a real bug: fix the route so the write is rolled back and the status is non-2xx, then re-run).
- [ ] **Step 4: Model card re-check.** `cd backend && PYTHONPATH=. uv run python -m app.ml.train --source csv --csv-dir ../data/processed --artifact-dir <scratch dir> --report <scratch dir>/report.json`. Scratch dir is outside the repo; the shipped artifact is not touched. Compare test ROC-AUC, precision, recall, F1, PR-AUC and the baseline rows with `docs/model_card.md`; correct the card only where a number differs (3-decimal rounding) and say so in the commit message.
- [ ] **Step 5: Write section 8.7** in doc 08: one table, columns `PLAN.md item | Test file | Test function(s)`, one row per bullet of PLAN.md section 13 (Ingestion 4, Analytics 5, Authentication and authorization 4, ML 6, Integration 3 = 22 rows). Find each test with grep; every row must name an existing test function. "Secrets never appear in responses or logs" names the five existing log/leak tests.
- [ ] **Step 6: Run the full suites and ruff; commit.** `git commit -m "test: end-to-end events-to-analytics and failed-write tests; doc 08 test coverage table"`

### Task 2: Backend fixes (spec 4.2 items 1, 2, 3, 5, 6, 8-11, 13)

**Files:**
- Modify: `backend/app/services/upload_scoring.py`, `backend/app/api/routes/datasets.py`, `backend/app/db/datasets.py`, `backend/app/core/authorization.py`, `backend/app/services/uploads.py`, `backend/app/main.py`, `backend/scripts/purge_uploads.py`
- Test: `backend/tests/test_upload_scoring.py`, `backend/tests/test_at_risk_upload_api.py`, `backend/tests/test_datasets_import_api.py`, `backend/tests/test_datasets_check_api.py`, `backend/tests/test_uploads_parse.py`, `backend/tests/test_purge_uploads.py`

**Interfaces:**
- Produces: `fit()` may return `{"method": "unavailable", "reason": "no_signup", ...}` (Task 3's page relies on `capabilities.retention == False` for it, not on the reason). `set_scoring(session, dataset_id, scoring) -> bool` (True when a row was updated). `ensure_profile(session: Session, user_id: uuid.UUID) -> UserProfile` in `app/core/authorization.py`; `current_profile` calls it.

Ruling on spec item 8: the no-signup result is method `unavailable` with reason `no_signup` (an existing method, so `SCOREABLE`, capabilities and the frontend's `scoring_method` handling need no new value). The spec's item 8 is amended in this task's commit to say so.

- [ ] **Step 1: Write the failing tests.**
  - `test_upload_scoring.py::test_no_signup_is_unavailable_not_an_error`: 300 customers, only `login` events over 90 days → `fit(...)["method"] == "unavailable"` and `["reason"] == "no_signup"`.
  - `test_upload_scoring.py::test_floor_too_few_train_non_churners`: training labels all churners, test floors met → `_floor_failure(...) == "too_few_train_non_churners"` (call `_floor_failure` with hand-built `pd.Series`).
  - `test_at_risk_upload_api.py::test_transient_db_error_on_score_is_503_and_not_stored`: monkeypatch `repositories.load_events` to raise `OperationalError`; `POST /datasets/{id}/score` → 503 `{"detail": "Database unavailable"}`; the row's `scoring` is unchanged.
  - `test_at_risk_upload_api.py::test_replace_during_score_is_404`: monkeypatch `upload_scoring.fit` to delete the dataset row (commit through a second session) before returning → `POST /datasets/{id}/score` is 404 `Dataset not found`.
  - `test_datasets_import_api.py::test_transient_db_error_after_import_keeps_201_and_no_scoring`: `load_events` raises `OperationalError` → 201, body `dataset.scoring_method is None`, the stored row's `scoring` is NULL.
  - `test_datasets_import_api.py::test_scoring_store_failure_emits_no_sql_after_it`: `set_scoring` raises `OperationalError`; count statements with an `event.listen(engine, "before_cursor_execute", ...)` started inside the patched `set_scoring` → 201 and the count after the failure is 0.
  - `test_datasets_import_api.py::test_body_is_read_before_any_db_access` and the same for `/datasets/check` in `test_datasets_check_api.py`: wrap `uploads.read_form` and `authorization.ensure_profile` to append `"read"` / `"profile"` to a list → the list is `["read", "profile"]` for import and `["read"]` for check.
  - `test_uploads_parse.py::test_exact_duplicate_header_is_rejected`: `b"customer_id,customer_id,event_name,event_timestamp\nu,v,login,2026-01-01T00:00:00Z\n"` → `UploadRejected` with code `missing_columns` and message `"A column name appears more than once."`.
  - `test_datasets_check_api.py::test_scoped_422_does_not_cover_other_prefixes`: call `validation_error` directly with a fake request whose path is `/datasets-foo` → it delegates to FastAPI's default handler (body has `input`); with `/datasets/check` it does not.
  - `test_datasets_import_api.py::test_dot_names_become_the_default_filename`: `clean_filename("..")`, `clean_filename(".")`, `clean_filename("a/..")` all return `DEFAULT_FILENAME`.
  - `test_purge_uploads.py::test_connection_error_prints_one_line_and_exits_1`: monkeypatch `get_engine` to an unreachable URL (`postgresql+psycopg://user:secret@127.0.0.1:1/nowhere`) → `main([...]) == 1`, stderr is exactly one line starting `purge failed: ` and contains no `secret`, no `Traceback`.
- [ ] **Step 2: Run them; expected FAIL** (KeyError for no-signup, 200/500 statuses, list order, accepted duplicate header, `..` stored, traceback).
- [ ] **Step 3: Implement.**
  - `fit`: after the empty and short-history checks, return `_result("unavailable", "no_signup", now, history_days)` when no row has `event_name == "signup"`.
  - `run_scoring`: re-raise `OperationalError`, `InterfaceError`, and `DBAPIError` whose `connection_invalidated` is true (before the broad `except`); keep the broad catch for everything else.
  - `set_scoring` returns `result.rowcount == 1`. `run_scoring` returns that bool. `score_dataset` raises 404 `Dataset not found` when it is False or when `session.refresh` raises `sqlalchemy.orm.exc.ObjectDeletedError`.
  - `_score_after_import(session, dataset) -> DatasetOut`: build `before = dataset_out(dataset)` first; return `dataset_out(dataset)` after a successful `run_scoring`, else `before` (on `SQLAlchemyError` or a False result). `import_upload` uses the returned value.
  - Profile after the body: `ensure_profile(session, user_id)` holds today's body of `current_profile`; `current_profile` becomes a one-line call. `check_upload` takes `user: Annotated[AuthUser, Depends(current_user)]` and no session; `import_upload` takes the same plus `SessionDep` and calls `ensure_profile` after `read_form` (inside the threadpool with `replace_upload`).
  - `parse_csv`: before reading with pandas, take the header with `csv.reader` over the first line of `raw.decode("utf-8-sig", errors="replace")`, normalise each name with `.strip().lower()`, and raise the existing duplicate error when any of `REQUIRED_COLUMNS + ("event_id",)` appears more than once. Keep the post-read check for case variants or remove it if the new one covers both.
  - `validation_error`: match `path == "/datasets" or path.startswith("/datasets/")`.
  - `clean_filename`: a result of `.` or `..` becomes `DEFAULT_FILENAME`.
  - `purge_uploads.main`: wrap the session work in `except SQLAlchemyError as exc: print(f"purge failed: {type(exc).__name__}", file=sys.stderr); return 1`.
- [ ] **Step 4: Run the new tests, then the full backend suite and ruff.** Expected: all PASS.
- [ ] **Step 5: Amend spec item 8** to "method `unavailable`, reason `no_signup`" and commit: `git commit -m "fix: no-signup uploads, transient DB errors, import response, body-before-profile, duplicate headers, 422 scope, dot filenames, purge errors"`

### Task 3: Frontend fixes (items 4, 8 page side, 12) and doc diagrams (item 7)

**Files:**
- Modify: `frontend/dataset.py`, `frontend/views/churn.py`, `frontend/views/upload.py`, `docs/03-system-design.md`, `docs/05-data-model.md`
- Test: `frontend/tests/test_dataset.py`, `frontend/tests/test_churn_view.py`, `frontend/tests/test_upload_view.py`

**Interfaces:**
- Consumes: Task 2's no-signup result (`scoring_method == "unavailable"`, `capabilities.retention == False`).

- [ ] **Step 1: Write the failing tests.**
  - `test_dataset.py::test_selection_survives_one_failed_dataset_list`: AppTest, three runs: run 1 lists demo and upload and selects the upload; run 2 `GET /datasets` raises `ServiceUnavailable` (error shown); run 3 lists both again → the selected id is the upload's and no fallback notice is shown.
  - `test_churn_view.py::test_no_signup_upload_shows_needs_signup`: context with `kind="upload"`, `scoring_method="unavailable"`, `capabilities` with `retention=False, churn=False` → `NO_SIGNUP` is shown, `SHORT_HISTORY` is not, no "Retry scoring" button. Replace the existing `scoring_method=None` no-signup test with this one.
  - `test_churn_view.py::test_short_history_with_signup_still_shows_short_history`: `scoring_method="unavailable"`, `retention=True` → `SHORT_HISTORY`.
  - `test_upload_view.py::test_preview_uses_exact_timestamps`: check with `first_event="2026-01-01T23:00:00Z"`, `last_event="2026-01-29T01:00:00Z"` and a mapped signup → churn line is `CHURN_SHORT`; with `last_event="2026-01-29T23:00:00Z"` → `CHURN_OK`.
- [ ] **Step 2: Run; expected FAIL.**
- [ ] **Step 3: Implement.**
  - `dataset.select`: after a successful list, store the chosen id in `st.session_state["dataset_choice"]` (a plain key, not a widget key); before the selectbox, when `"dataset_id"` is absent and `"dataset_choice"` is in `by_id`, set `st.session_state["dataset_id"]` from it. The `next_dataset_id` hand-off still takes precedence.
  - `churn._upload_unavailable`: check "no signup" first: `not ctx.capabilities.get("retention", True)` → `NO_SIGNUP`, whatever the method; then `unavailable` → `SHORT_HISTORY`; then `failed`/`None` → `SCORING_FAILED` with Retry; else `NOT_AVAILABLE`.
  - `upload._history_days(check) -> float | None`: parse both timestamps with `datetime.fromisoformat` (accept a trailing `Z`) and return `(last - first).total_seconds() / 86400`; `_churn` keeps `days < CHURN_MIN_DAYS`.
  - Doc 03: add `datasets` routes, `dependencies.py`, `services/uploads.py`, `services/upload_scoring.py`, `db/datasets.py`, `frontend/dataset.py`, `views/upload.py` to the module diagram; section 3.4 drops "route pending". Doc 05: the ER diagram marks `datasets.owner_id` nullable. Check both diagrams render (Mermaid syntax; the earlier check script lived in the scratchpad, so a local `npx -y @mermaid-js/mermaid-cli` render or the IDE preview is enough).
- [ ] **Step 4: Run the full frontend suite with `-W error`, backend suite and ruff; commit.** `git commit -m "fix: selection survives a failed dataset list, no-signup message, exact preview history; doc 03/05 diagrams"`

### Task 4: Known limitations and security pass

**Files:**
- Modify: `docs/08-operations-runbook.md` (section 8.6), `docs/06-security.md` (section 6.5 and a new `## 6.6 Phase 7a security pass`), `docs/history/phase-5-auth/history.md`, `docs/history/phase-6-dashboard/history.md` (one line each pointing to 8.6), plus code only where a finding needs a fix.

- [ ] **Step 1: Write section 8.6 Known limitations.** One line per accepted item, each "what · why accepted · what would change it": the Phase 5 deferred minors (refresh blip signs out; login CSRF via server-held PKCE verifier), the Phase 6 deferred minors, every Phase 6b deferred minor not fixed in Tasks 2-3, and spec 4.2's "Accepted" list (demo counts frozen at migration, cache lock gap and global generation bump, `risk_asc` per-page re-sort and the repeated max-timestamp query). Product items: no rate limit on `/datasets/check`, no automatic upload expiry (manual `scripts/purge_uploads.py`), the 0.02 margin and floors, no automated profile deletion. Point both history files at it.
- [ ] **Step 2: Secrets in Git history.** Run a local scan over every commit: `git log -p --all | grep -n -i -E "(api[_-]?key|secret|password|service_role|eyJ[a-zA-Z0-9_-]{20,}|postgres(ql)?(\+psycopg)?://[^ ]*:[^ @]*@)"` and read each hit. Test fixtures (`ingest-key-0123...`, `user:secret@127.0.0.1:1`) are expected. A real secret is **not** removed by this task: stop and report it to the user (a history rewrite needs their approval).
- [ ] **Step 3: Logs and errors.** List every `logger.` call and every `HTTPException`/`JSONResponse` in `backend/app` (grep), and confirm each logs type names or fixed text and returns fixed messages. Record the list's size and any fix.
- [ ] **Step 4: CORS and frontend exposure.** Confirm `cors_origin_list` is empty when `CORS_ORIGINS` is unset (add a test in `backend/tests/test_health.py` if none exists) and that the frontend reads only `APP_BASE_URL`, `API_BASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` (grep `os.getenv`, `os.environ` and `st.secrets` in `frontend/`; today only `gate.py` reads them).
- [ ] **Step 5: Dependencies.** `cd backend && uvx pip-audit` (and in `frontend/`) against the locked environments (`uv export --format requirements-txt > <scratch>/req.txt` then `uvx pip-audit -r <scratch>/req.txt`). Upgrade a vulnerable package if a fixed version exists and the suites stay green; otherwise record it with the advisory id.
- [ ] **Step 6: Run the `security-review` skill** on the branch and act on each finding (fix with a test, or record in 6.6 with the reason).
- [ ] **Step 7: Update 6.5** (tick each box with its evidence, or leave open with a named reason) and write 6.6 (date, what was checked, counts, findings and outcomes). Run suites and ruff; commit: `git commit -m "docs: known limitations and Phase 7a security pass"`

### Task 5: Fresh-clone README run

**Files:**
- Modify: `README.md`, `docs/09-local-development.md`, `docs/guide.md` if a step is described there, `docs/history/phase-7-quality-and-docs/history.md`

- [ ] **Step 1: Clone.** `git clone <repo path> <scratchpad>/fresh` from the local repo at the branch head (no network needed). Use a fresh local Docker database name (`churnscope_fresh`) on the existing container; never Supabase. Create the env file the README asks for from `.env.example` with local values only.
- [ ] **Step 2: Follow the README Quick start word for word**: install, generate data, migrate, load, train, run the API, run the tests, start the frontend (stop at the sign-in page: Google sign-in is the user's step). Write down each step's command, whether it worked as written, and its time.
- [ ] **Step 3: Fix every gap** in README or doc 09 (a missing command, an unstated prerequisite, a wrong path, an env var not mentioned). Re-run the failed step from the fixed text to confirm.
- [ ] **Step 4: Rewrite the README Status paragraph** (6b merged; 7a in progress; deploy pending) and add a short "What it does" section with an image placeholder list for Task 6 (`docs/images/*.png`, linked but files added in Task 6).
- [ ] **Step 5: Clean up**: drop `churnscope_fresh`, delete the clone. Record the run (steps, times, fixes) in the 7a history. Commit: `git commit -m "docs: README and local setup fixed from a fresh-clone run"`

### Task 6: Screenshots, progress and history (needs the user)

**Files:**
- Create: `docs/images/signin.png`, `overview.png`, `funnel.png`, `retention.png`, `churn.png`, `upload.png`
- Modify: `README.md`, `progress.md`, `docs/history/phase-7-quality-and-docs/history.md`, `docs/10-project-history.md`

- [ ] **Step 1: The user takes the six screenshots** on the local app, demo dataset, Upload page before a file is chosen, and saves them to `docs/images/` with those names.
- [ ] **Step 2: Check each image** (open with the Read tool): demo data only, no token, no URL containing `code=`, no email except one the user approves. Each file under 500 KB (compress if larger, keeping it readable).
- [ ] **Step 3: Link them** in the README's "What it does" section.
- [ ] **Step 4: Progress and history.** In `progress.md`: Phase 7 heading note that 7a covers the first 9 items and 7b covers Deploy; tick the 9 items with evidence pointers; update the summary row (`Done / Total`) and the updated-date line; inherited items stay for 7b. Fill the 7a history (Done, Decisions incl. the no-signup ruling, Results with test counts, Open). Update doc 10's Phase 7 row.
- [ ] **Step 5: Run suites and ruff; commit:** `git commit -m "docs: screenshots, Phase 7a progress and history"`
