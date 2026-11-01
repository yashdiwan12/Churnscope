# Phase 6b Bring Your Own Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in, allow-listed user uploads one CSV of their own events, maps their event names to ours, and sees the five dashboard pages for that file only; the churn page on an upload is trained and backtested on the file's own history.

**Architecture:** A `datasets` table owns every customer and event row (the demo data is dataset 1). One module, `db/datasets.py`, holds the ownership checks; every repository function takes a `dataset_id`; every analytics and churn route takes `?dataset_id=` through one visibility dependency (404 when not visible). Uploads go through a stateless check call and a transactional import call (multipart). Scoring an upload reuses the training pipeline and stores the fitted model as JSON on the dataset row. The frontend adds a dataset selector checked against a fresh `GET /datasets` on every rerun, dataset- and user-keyed caches, and an Upload data page.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, pandas, scikit-learn, `python-multipart` (new), pytest (backend); Streamlit (`st.file_uploader`, `st.cache_data`, `AppTest`), httpx (frontend).

**Spec:** `docs/superpowers/specs/2026-11-01-phase6b-uploads-design.md` (executors read both; section numbers below refer to it).

## Global Constraints

- `DEMO_DATASET_ID = 1` lives in `backend/app/db/datasets.py`; every other module imports it from there.
- A dataset is visible when it is the demo dataset or `owner_id` equals the caller's profile id. Anything else, including a missing id, is **404** with detail `Dataset not found`. Never 403.
- `POST /churn/predict` stays demo-only (no `dataset_id`): the shipped synthetic-data model is never applied to an upload.
- Upload limits, all in `backend/app/services/uploads.py`: `MAX_REQUEST_BYTES = 5_767_168` (5.5 MiB), `MAX_FILE_BYTES = 5_242_880` (5 MiB), `MAX_ROWS = 50_000`, `MAX_CUSTOMERS = 10_000`, `MAX_EVENT_NAMES = 50`, `MAX_VALUE_CHARS = 100`, `MAX_INVALID_SHARE = 0.05`, `MAX_REASONS = 20`, `GLOBAL_UPLOADED_EVENTS_CAP = 300_000`, `CENSOR_WARN_SHARE = 0.25`, `CENSOR_WINDOW_DAYS = 7`, `IMPORT_LOCK_KEY = 6_202_611`, `INSERT_BATCH = 5_000`. Task 0 may lower the first four; nothing else changes them.
- Scoring constants, all in `backend/app/services/upload_scoring.py`: `MAX_CUTOFFS = 26`, `N_TEST = 2`, `MARGIN = 0.02`, `MIN_TEST_ROWS = 200`, `MIN_PER_CLASS = 20`, `RULE_DAYS = 7.0`, `SEED = 42`.
- Whole-file rejection codes (HTTP 422, body `{"detail": {"code": CODE, "message": TEXT}}`): `empty_file`, `not_utf8`, `missing_columns`, `too_many_rows`, `too_many_customers`, `too_many_event_names`, `too_many_invalid`, `no_activity_event`, `bad_mapping`, `derive_not_allowed`, `acknowledgement_required`. 413 `file_too_large`, 411 when Content-Length is missing, 409 `storage_full`. Row skip codes: `missing_customer_id`, `missing_event_name`, `bad_timestamp`, `timestamp_out_of_range`, `value_too_long`. A skip reason is `{"row": N, "code": CODE}` (1-based data row number); **no response, log line or exception message ever contains a value from the file.**
- `/datasets` routes use a 422 handler that returns only `loc` and `msg` per error, never `input` or `ctx`.
- Frontend fixed copy (exact):
  - Demo banner unchanged: `Demo data: synthetic events from a seeded generator, not real customers.`
  - Upload banner: `Your uploaded data: {filename}, private to you.`
  - Upload notice: `Your file is kept until you delete it or your access is removed. Do not upload personal data you are not allowed to share.`
  - Fallback notice: `Your selected dataset is no longer available. Showing demo data.`
  - Derived-signup notes: Overview `Signup dates are derived from each customer's first event in your file, so New users includes customers who joined before the file starts.`; Retention `Signup dates are derived from each customer's first event in your file, so the first cohort includes customers who joined before the file starts.`; Churn `Account age is unreliable: signup dates are derived from each customer's first event in your file.`
  - Censor warning: `Most customers' first event falls in the first week of your file. They probably joined earlier, so signup dates, new users and the first retention cohort will be approximate.` Acknowledgement checkbox: `I understand signup dates are approximate`.
  - Churn not yet available: `Churn scoring is not available for this dataset yet.`
- Frontend caches: every cached function in `data.py` takes `dataset_id: int` and `user_id: str` right after `_api`. After an import or delete the acting session calls `st.cache_data.clear()`.
- Tests never touch the Supabase project (`TEST_DATABASE_URL`). Never print or commit `.env`. Ruff line length 100; backend commands from `backend/`, frontend from `frontend/`, both with `uv run`. **Commit messages carry no `Co-Authored-By` or other AI attribution line** (the user's standing rule).

## Review Focus

Each line is pinned by a test in the task named in brackets.

1. Another user's dataset id, a deleted id, or a huge id on **any** route (`/analytics/*`, `/churn/at-risk`, `DELETE /datasets/{id}`, `POST /datasets/{id}/score`) is a 404 and returns no data [Tasks 1, 2, 4, 7].
2. An import that fails halfway (forced exception after the old dataset is deleted) leaves the old upload fully intact, and two concurrent imports by one user leave exactly one complete upload [Task 4].
3. A CSV with a UTF-8 BOM, CRLF line endings, quoted fields containing commas, mixed-case headers with spaces, and zoneless timestamps parses correctly; a Latin-1 file is `not_utf8`, not a crash [Task 3].
4. After a delete or replace, neither the backend churn cache nor the frontend cache can serve the old dataset, including from a second browser session that still holds the old id [Tasks 2, 4, 5].
5. Degenerate uploads (one customer; every row identical; every name ignored but one activity event; history under 28 days) never divide by zero or crash, and the churn page shows the right fallback [Tasks 3, 4, 7].

---

### Task 0: Import timing on the real database (controller task, needs the user's approval)

Not dispatched to a subagent. Ask the user first: it writes to their Supabase project.

- [ ] **Step 1:** If the user declines, record "local numbers only: 42,847 events in 11.5 s" in the ledger, keep the limits in Global Constraints, and go to Task 1.
- [ ] **Step 2:** If approved, run a throwaway script (scratchpad, never committed) that creates schema `timing_6b` on Supabase with copies of `customers` and `events`, inserts 50,000 synthetic events for 10,000 customers in batches of `INSERT_BATCH` inside one transaction, deletes them in a second transaction, records both times and the pooler's `statement_timeout`, then drops the schema. Read nothing from `.env` into output.
- [ ] **Step 3:** If insert plus delete exceeds 40 s, lower `MAX_ROWS` and `MAX_CUSTOMERS` in proportion; record the numbers and any change in the ledger and in spec section 12.

---

### Task 1: Datasets table, migration and dataset-scoped data access

**Files:**
- Create: `backend/migrations/versions/0003_datasets.py`, `backend/app/db/datasets.py`
- Modify: `backend/app/db/models.py`, `backend/app/db/repositories.py`, `backend/app/services/ingestion.py`, `backend/app/services/analytics.py`, `backend/app/services/prediction.py` (pass `DEMO_DATASET_ID` only), `backend/app/api/routes/events.py`, `backend/scripts/load_events.py`
- Test: `backend/tests/test_datasets_db.py` (new); update callers in existing tests (`test_ingestion.py`, `test_repositories_phase6.py`, `test_rls.py`, others the full run shows)

**Interfaces:**
- Produces (`models.py`): `Dataset` (columns as spec section 4, `scoring: dict | None`); `Customer.dataset_id`, `Event.dataset_id` (both `int`, NOT NULL).
- Produces (`db/datasets.py`): `DEMO_DATASET_ID = 1`; `visible(session, user_id: uuid.UUID, dataset_id: int) -> Dataset | None`; `list_visible(session, user_id) -> list[Dataset]` (demo first, then the caller's upload); `own_upload(session, user_id) -> Dataset | None`; `delete_upload(session, user_id, dataset_id) -> bool` (False for demo, missing, or someone else's).
- Produces (`repositories.py`), `dataset_id` always the second positional argument: `data_through(session, dataset_id)`, `latest_event_id(session, dataset_id)`, `customer_external_ids(session, dataset_id, pks)`, `resolve_customers(session, dataset_id, external_ids)`, `load_events(session, dataset_id, until=None, since=None, customer_ids=None)`.
- Produces (`analytics.py`): `resolve_window(session, dataset_id, start, end)`, `overview(session, dataset_id, start, end)`, `funnel_report(session, dataset_id, start, end, window_days)`, `retention_report(session, dataset_id, periods)`, `engagement_report(session, dataset_id, start, end)`.
- Produces (`ingestion.py`): `ingest_events(session, raw_events, dataset_id: int = DEMO_DATASET_ID)`; conflict targets `["dataset_id", "event_id"]` and `["dataset_id", "external_customer_id"]`.

- [ ] **Step 1: Write failing tests** in `test_datasets_db.py`: `test_migration_creates_demo_dataset` (row 1, `kind == "demo"`, `owner_id is None`); `test_existing_rows_backfilled_to_demo` (ingest via `ingest_events`, every row has `dataset_id == 1`); `test_same_event_id_in_two_datasets_both_import` (insert a second dataset row directly, ingest the same `event_id` into each; both counts 1); `test_event_cannot_reference_other_datasets_customer` (direct insert raises `IntegrityError`); `test_one_upload_per_owner` (second `kind="upload"` row for one owner raises `IntegrityError`); `test_profile_delete_cascades_upload` (delete the `user_profiles` row; dataset, customers and events gone); `test_visible_and_delete_upload_rules` (demo visible to anyone, upload only to its owner, `delete_upload` False for demo and for a stranger); `test_repositories_scope_to_dataset` (two datasets with different events: `load_events`, `data_through`, `latest_event_id`, `resolve_customers` each see only their own); `test_downgrade_refuses_when_uploads_exist` (run `command.downgrade(cfg, "0002")` with an upload row present → raises; then upgrade back to head).
- [ ] **Step 2: Run** `uv run pytest tests/test_datasets_db.py -q` → FAIL.
- [ ] **Step 3: Implement migration `0003`** per spec section 4: create `datasets` (CHECKs on `kind` and `signup_rule`, `owner_id` FK `ON DELETE CASCADE`, partial unique index `uq_datasets_one_upload_per_owner` on `owner_id` WHERE `kind = 'upload'`); insert row 1 (`kind 'demo'`, `name 'Demo data (synthetic)'`, `signup_rule 'event'`); add `dataset_id` to `customers` and `events` with `server_default '1'`, then drop the default; drop the two global unique constraints from `0001` (look up their real names in `0001`); add `uq_customers_dataset_external (dataset_id, external_customer_id)`, `uq_customers_dataset_id (dataset_id, id)`, `uq_events_dataset_event_id (dataset_id, event_id)`, `fk_events_dataset_customer (dataset_id, customer_id) → customers (dataset_id, id)`; replace `ix_events_customer_ts`, `ix_events_name_ts` with `ix_events_dataset_customer_ts`, `ix_events_dataset_name_ts`, and add `ix_events_dataset_id (dataset_id, id)`; enable RLS on `datasets` and run the same revoke block as `0002`. The downgrade raises if any `kind = 'upload'` row exists.
- [ ] **Step 4: Implement** the models, `db/datasets.py`, the repository signatures, the conflict targets, and pass `DEMO_DATASET_ID` explicitly from `routes/events.py`, `scripts/load_events.py` and every current caller in `analytics.py` and `prediction.py`. No route changes yet.
- [ ] **Step 5: Run** the new tests, the full backend suite and ruff → green. Add `datasets` to the table list asserted in `test_rls.py`.
- [ ] **Step 6: Commit** `feat: datasets table and dataset-scoped data access (migration 0003)`.

---

### Task 2: `dataset_id` on analytics and churn routes; churn cache per dataset

**Files:**
- Create: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/routes/analytics.py`, `backend/app/api/routes/churn.py`, `backend/app/services/prediction.py`
- Test: `backend/tests/test_dataset_routes.py` (new); `backend/tests/test_at_risk_api.py`

**Interfaces:**
- Consumes: `db/datasets.visible`, `current_profile`, Task 1 service signatures.
- Produces (`dependencies.py`): `visible_dataset(dataset_id: Annotated[int, Query(ge=1, le=2**63 - 1)] = 1, profile=Depends(current_profile), session=Depends(get_session)) -> Dataset` (404 `Dataset not found`); `DatasetDep = Annotated[Dataset, Depends(visible_dataset)]`.
- Produces (`prediction.py`): `at_risk(session, bundle, dataset: Dataset, limit, offset, sort)`; the cache becomes an `OrderedDict` bounded to 4 entries with key `(dataset.id, bundle.version, cutoff, latest_event_id)` for the demo; `evict_dataset(dataset_id: int) -> None`; `clear_at_risk_cache()` unchanged. For an upload, `at_risk` raises `ScoringUnavailable` until Task 7, and the route maps it to **409** `Churn scoring is not available for this dataset`.

- [ ] **Step 1: Write failing tests:** `test_analytics_routes_accept_demo_default` (no param is identical to `?dataset_id=1`); `test_foreign_dataset_is_404_on_every_route` (parametrised over the four analytics paths and `/churn/at-risk`: a dataset owned by user B, requested by user A → 404, body exactly `{"detail": "Dataset not found"}`); `test_missing_and_huge_ids_are_404_or_422` (`999999` → 404, `2**63` → 422, `0` → 422); `test_owner_sees_own_dataset_numbers` (user A's upload rows only, via direct inserts); `test_at_risk_cache_keyed_per_dataset_and_bounded` (5 distinct keys → oldest evicted; `evict_dataset(1)` removes only dataset 1's entries); `test_upload_at_risk_is_409_before_scoring`.
- [ ] **Step 2: Run** `uv run pytest tests/test_dataset_routes.py tests/test_at_risk_api.py -q` → FAIL.
- [ ] **Step 3: Implement** the dependency and wire `DatasetDep` into the four analytics routes and `/churn/at-risk` (the model dependency stays declared first). Use the two-user token helpers in `tests/auth_helpers.py`.
- [ ] **Step 4: Run** the full suite and ruff → green.
- [ ] **Step 5: Commit** `feat: dataset_id on analytics and churn routes; churn cache per dataset`.

---

### Task 3: CSV parsing and `POST /datasets/check`

**Files:**
- Create: `backend/app/services/uploads.py`, `backend/app/schemas/datasets.py`, `backend/app/api/routes/datasets.py`
- Modify: `backend/app/main.py` (router, scoped 422 handler), `backend/pyproject.toml` / `uv.lock` (`uv add python-multipart`)
- Test: `backend/tests/test_uploads_parse.py` (pure, no DB), `backend/tests/test_datasets_check_api.py`

**Interfaces:**
- Produces (`uploads.py`): the Global Constraints limits; `class UploadRejected(Exception)` with `.code`, `.message`, `.status` (422 default); `@dataclass ParsedFile(rows: pd.DataFrame, skipped: list[tuple[int, str]], total_rows: int, zoneless: bool)` where `rows` has `row`, `customer_id`, `source_name`, `event_timestamp` (UTC), `event_id` (str or None); `parse_csv(raw: bytes, now: pd.Timestamp) -> ParsedFile`; `normalise(name: str) -> str` (lower case, trimmed, spaces and hyphens to `_`); `suggest_mapping(names: list[str]) -> dict[str, str | None]` (exact normalised match to `metrics.EVENT_NAMES`, else `None`); `first_week_share(rows) -> float` (customers whose first event is before `min + CENSOR_WINDOW_DAYS` divided by customers; 0.0 when empty); `async read_upload(request: Request, file: UploadFile) -> bytes` (411 / 413 checks, chunked read stopping at `MAX_FILE_BYTES + 1`).
- Produces (`schemas/datasets.py`): `SkipReason(row: int, code: str)`; `EventNameCount(name: str, count: int)`; `CheckOut(total_rows, valid_rows, customers, first_event: datetime | None, last_event: datetime | None, event_names: list[EventNameCount], suggested_mapping: dict[str, str | None], skipped_count: int, skipped: list[SkipReason], zoneless_timestamps: bool, first_week_share: float, censor_warning: bool, our_event_names: list[str], qualifying_events: list[str], funnel_steps: list[str])`. The last three come from `metrics` so the frontend never hard-codes them.
- Produces (route): `POST /datasets/check` (`current_profile` dependency, multipart `file`).

- [ ] **Step 1: Write failing parse tests:** `test_parses_bom_crlf_quotes_and_header_case` (`"﻿Customer_ID , Event Name,EVENT_TIMESTAMP\r\n"` style header; a quoted name with a comma) — wait, header matching is on exact trimmed lower-case names `customer_id`, `event_name`, `event_timestamp`, `event_id`, so use ` Customer_ID ` and ` EVENT_NAME `; `test_zoneless_timestamp_is_utc_and_flagged`; `test_latin1_is_not_utf8`; `test_missing_column_rejected` (`code == "missing_columns"`); `test_row_skip_codes` (one row per skip code; `skipped == [(1, ...), ...]`); `test_timestamp_bounds` (before 2000-01-01 and more than 5 minutes after `now` → `timestamp_out_of_range`); `test_limits` (`MAX_ROWS + 1` rows → `too_many_rows`; `MAX_CUSTOMERS + 1` → `too_many_customers`; `MAX_EVENT_NAMES + 1` names → `too_many_event_names`; empty body or header only → `empty_file`); `test_extra_columns_ignored`; `test_suggest_mapping_normalises` (`"Session Start"` → `session_start`, `"login"` → `None`); `test_first_week_share` (hand-computed 3 of 4 → 0.75; empty → 0.0); `test_no_file_value_in_any_message` (a file with a distinctive value `SECRET-123` in every bad row: no `UploadRejected.message`, no skip tuple, and no captured log record contains it).
- [ ] **Step 2: Write failing API tests:** `test_check_returns_summary_and_stores_nothing` (row counts in DB unchanged); `test_check_requires_sign_in` (401 without token); `test_check_411_without_content_length`; `test_check_413_over_limit`; `test_check_422_never_echoes_input` (send a non-file `file` field: the body has `loc` and `msg` only; `SECRET-123` absent); `test_censor_warning_at_threshold` (share exactly 0.25 → `censor_warning` true; 0.24 → false).
- [ ] **Step 3: Run** both files → FAIL.
- [ ] **Step 4: Implement** with `pandas.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="utf-8-sig")` after a strict `raw.decode("utf-8")` check; timestamps with `pd.to_datetime(..., utc=False, errors="coerce", format="ISO8601")`, localising zoneless values to UTC and setting `zoneless`; register the router; add the 422 handler for paths starting with `/datasets`.
- [ ] **Step 5: Run** the full suite and ruff → green.
- [ ] **Step 6: Commit** `feat: CSV parsing and POST /datasets/check`.

---

### Task 4: Import, list and delete

**Files:**
- Modify: `backend/app/services/uploads.py`, `backend/app/db/datasets.py`, `backend/app/schemas/datasets.py`, `backend/app/api/routes/datasets.py`
- Test: `backend/tests/test_uploads_prepare.py` (pure), `backend/tests/test_datasets_import_api.py`

**Interfaces:**
- Consumes: Task 3 `parse_csv`, `read_upload`, `first_week_share`; Task 2 `prediction.evict_dataset`; `metrics.EVENT_NAMES`, `QUALIFYING_EVENTS`, `FUNNEL_STEPS`.
- Produces (`uploads.py`): `@dataclass Prepared(events: pd.DataFrame, customers: pd.DataFrame, mapping: dict, signup_rule: str, mapped_counts: dict[str, int], invalid_rows: int, ignored_rows: int, duplicate_rows: int, derived_signups: int, skipped: list[tuple[int, str]])`; `prepare(parsed: ParsedFile, mapping: dict[str, str | None], derive_signup: bool, acknowledged: bool) -> Prepared`; `derive_event_id(customer_id: str, event_name: str, ts: pd.Timestamp) -> str` = first 32 hex chars of SHA-256 of `f"{customer_id}|{event_name}|{ts.isoformat()}"`; `capabilities(dataset: Dataset) -> dict` with keys `overview`, `engagement`, `retention`, `funnel`, `churn` (bools) and `funnel_missing: list[str]` (from `metrics.FUNNEL_STEPS`; the demo has everything; `churn` is `False` for every upload until Task 7).
- Produces (`db/datasets.py`): `class StorageFull(Exception)`; `replace_upload(session, user_id, filename: str, prepared: Prepared) -> Dataset`.
- Produces (schemas): `Capabilities`; `DatasetOut(id, kind, name, source_filename, signup_rule, customer_count, event_count, data_through, created_at, capabilities: Capabilities, scoring_method: str | None)`; `ImportOut(dataset: DatasetOut, imported_events, derived_signups, ignored_rows, duplicate_rows, invalid_rows, skipped: list[SkipReason])`.
- Produces (routes): `GET /datasets -> list[DatasetOut]`; `POST /datasets` (multipart `file`, form `mapping` JSON string, `derive_signup: bool = False`, `acknowledge_approximate_signup: bool = False`) `-> ImportOut` (201); `DELETE /datasets/{dataset_id}` (204; 404 for demo, missing or foreign; `dataset_id` `Path(ge=1, le=2**63 - 1)`). The filename shown is `PurePath(file.filename).name` cut to 100 chars, `upload.csv` when absent.

- [ ] **Step 1: Write failing pure tests** (`test_uploads_prepare.py`): `test_identical_rows_are_duplicates` (two identical rows → one event, `duplicate_rows == 1`); `test_derived_event_id_is_stable` (same inputs → same id; differs when the timestamp differs by 1 s); `test_supplied_event_id_duplicates_keep_first`; `test_invalid_share_excludes_ignored_and_duplicates` (100 rows: 4 invalid, 30 mapped to ignore, 10 duplicates → accepted; 7 invalid of 100 with none ignored → `too_many_invalid`); `test_mapping_must_target_known_names` (`bad_mapping`); `test_needs_an_activity_event` (`no_activity_event` when only `signup` is mapped); `test_derive_only_when_nothing_maps_to_signup` (`derive_not_allowed`); `test_derived_signup_per_customer_at_first_event` (properties `{"derived": True}`, timestamp equals that customer's first mapped event); `test_acknowledgement_required_when_censored` (share ≥ 0.25 with `derive_signup` and not acknowledged → `acknowledgement_required`); `test_capabilities_shapes` (no signup → retention False, funnel False with all of `FUNNEL_STEPS` missing that are absent; derived signup → retention True; demo → all True except nothing).
- [ ] **Step 2: Write failing API tests** (`test_datasets_import_api.py`): `test_import_then_list_shows_demo_and_upload`; `test_reimport_same_file_gives_identical_counts`; `test_replace_keeps_one_upload_and_old_rows_gone`; `test_failed_import_keeps_old_upload` (monkeypatch the events insert to raise after the delete statement ran → 500 or 503, old dataset and its row counts intact); `test_concurrent_imports_one_user_leave_one_complete_upload` (two threads, two sessions, the advisory lock serialises them; afterwards exactly one upload and its `event_count` equals its rows in `events`); `test_global_cap_returns_409` (monkeypatch `GLOBAL_UPLOADED_EVENTS_CAP` small; user A fills it, user B's import → 409 `storage_full`; user A's replace of the same size still succeeds because its own old rows are excluded from the sum); `test_delete_rules` (own → 204 and its customers and events counted as 0; demo → 404; stranger's → 404); `test_delete_and_import_evict_churn_cache` (seed the cache with the dataset's key, delete → key gone); `test_post_events_cannot_touch_uploads` (`POST /events` with the ingest key lands in dataset 1 even if the same customer id exists in an upload); `test_metrics_on_upload_match_demo_load` (import a 30-row hand-checked file, then load the same rows into a fresh demo database through `ingest_events`; `/analytics/overview` and `/analytics/retention` bodies are equal apart from `dataset_id`-dependent fields).
- [ ] **Step 3: Run** both files → FAIL.
- [ ] **Step 4: Implement** `replace_upload` in one transaction: `SELECT pg_advisory_xact_lock(:key)`; sum `event_count` of other users' uploads, plus the new count, against the cap (`StorageFull`); `DELETE` the caller's upload (cascade); insert the dataset row; insert customers (`created_at` = first event) with `RETURNING id`; insert events in batches of `INSERT_BATCH` via `session.execute(insert(Event), rows)`; set counts, `mapped_counts`, `data_through`; commit; then `prediction.evict_dataset` for the old and new ids. Any exception rolls back.
- [ ] **Step 5: Run** the full suite and ruff → green.
- [ ] **Step 6: Commit** `feat: import, list and delete uploads in one transaction`.

---

### Task 5: Frontend dataset selector, dataset-keyed caches, banner and notes

**Files:**
- Create: `frontend/dataset.py`
- Modify: `frontend/app.py`, `frontend/data.py`, `frontend/api_client.py` (`post_file`), `frontend/states.py` (404 message), `frontend/views/{overview,funnel,retention,engagement,churn}.py`
- Test: `frontend/tests/test_dataset.py` (new), update `fake_api.py`, `test_data.py`, `test_chrome.py` and the view tests

**Interfaces:**
- Produces (`api_client.py`): `ApiClient.post_file(path, *, file: tuple[str, bytes, str], data: dict[str, str], timeout: float | None = None) -> Any`; `IMPORT_TIMEOUT = 60`.
- Produces (`dataset.py`): `@dataclass(frozen=True) class Context(dataset_id: int, user_id: str, kind: str, name: str, signup_rule: str, capabilities: dict, scoring_method: str | None)`; `select(api, me: dict) -> Context` (calls `GET /datasets` uncached on every rerun; sidebar `st.selectbox("Data", ...)` with key `dataset_id`; an id that is no longer listed falls back to 1 and shows the fallback notice); `banner_text(ctx) -> str`.
- Produces (`data.py`): every function `(_api, dataset_id: int, user_id: str, ...)` and sends `dataset_id`.
- Produces (views): `render(api, ctx: Context)`. A missing capability renders the fixed empty message and makes **no** API call: Retention `Retention needs a signup event. Map one of your events to signup, or re-upload with "first event counts as signup".`; Funnel `The funnel needs these steps: {comma-separated missing}.`; Churn (upload, `churn` false) the Churn-not-yet-available copy. Derived-signup notes per Global Constraints. `states.render_error` maps `ApiError(404)` to `That dataset is no longer available. Choose a dataset in the sidebar.`.
- `app.py`: banner from `banner_text`, `PAGES` unchanged in this task, views get `partial(view.render, api, ctx)`.

- [ ] **Step 1: Write failing tests:** `test_selector_lists_demo_and_upload`; `test_unknown_selected_id_falls_back_with_notice` (session holds 7, `GET /datasets` lists only 1 → context id 1, notice shown); `test_banner_follows_dataset` (exact copy for both kinds); `test_cache_key_includes_dataset_and_user` (two calls differing only in `dataset_id`, then only in `user_id`, each hit the fake API); `test_deleted_dataset_never_served_from_cache` (fill the cache for id 7, then `GET /datasets` no longer lists 7: the page shows demo numbers and the fake API saw a demo request); `test_missing_capability_makes_no_request` (retention and funnel); `test_derived_notes_shown` (overview, retention, churn); `test_404_message`.
- [ ] **Step 2: Run** `uv run pytest -q -W error` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the frontend suite with `-W error` and ruff → green.
- [ ] **Step 5: Commit** `feat: dataset selector, dataset-keyed caches, banner and notes`.

---

### Task 6: Upload data page

**Files:**
- Create: `frontend/views/upload.py`
- Modify: `frontend/app.py` (add `(upload, "Upload data", "upload")` to `PAGES`), `frontend/.streamlit/config.toml` (`[server]` `maxUploadSize = 5`)
- Test: `frontend/tests/test_upload_view.py`, `frontend/tests/test_chrome.py` (config value)

**Interfaces:**
- Consumes: `/datasets/check` (`CheckOut`), `POST /datasets` (`ImportOut`), `DELETE /datasets/{id}`, `ApiClient.post_file`, `IMPORT_TIMEOUT`, `Context`.
- Produces: `render(api, ctx)`; `TEMPLATE_CSV` (header `customer_id,event_name,event_timestamp,event_id` and three example rows); `preview(mapping, derive_signup, check: dict) -> dict` (pure: which pages will work, from `check["qualifying_events"]` and `check["funnel_steps"]`).
- Flow: notice, template download, `st.file_uploader("CSV file", type=["csv"])`, **Check file** (stores the bytes and result in `session_state`), a mapping selectbox per name (`Ignore` plus `our_event_names`, default from `suggested_mapping`), the derive checkbox disabled when a name maps to `signup`, the censor warning with the acknowledgement checkbox, the preview, a replace-confirmation checkbox when an upload exists, **Import**, and **Delete my data** with a confirmation checkbox. After import or delete: `st.cache_data.clear()`, set `session_state["dataset_id"]` (new id or 1), `st.rerun()`. A 422 shows the server's `code` mapped to a fixed message per code (never the server text).

- [ ] **Step 1: Write failing tests:** `test_notice_and_template_shown`; `test_check_then_mapping_defaults_from_suggestion`; `test_import_button_disabled_until_acknowledged` (censor warning case); `test_derive_disabled_when_signup_mapped`; `test_preview_names_unavailable_pages`; `test_import_success_switches_dataset_and_clears_cache`; `test_rejection_code_shows_fixed_message` (each code; no server text); `test_delete_requires_confirmation_and_falls_back_to_demo`; `test_max_upload_size_config` (`config.toml` has `maxUploadSize = 5`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the frontend suite with `-W error` and ruff → green.
- [ ] **Step 5: Commit** `feat: Upload data page`.

---

### Task 7: Churn on uploads, learned from the file (separable)

If this task is dropped, uploads keep `churn = False` and the Task 5 copy; nothing else changes.

**Files:**
- Create: `backend/app/services/upload_scoring.py`
- Modify: `backend/app/services/prediction.py`, `backend/app/schemas/churn.py`, `backend/app/services/uploads.py` (`capabilities`), `backend/app/db/datasets.py` (`set_scoring`), `backend/app/api/routes/datasets.py` (score after import; `POST /datasets/{id}/score`), `frontend/views/churn.py`, `frontend/charts.py`
- Test: `backend/tests/test_upload_scoring.py`, `backend/tests/test_at_risk_upload_api.py`, `frontend/tests/test_churn_view.py`

**Interfaces:**
- Consumes: `features.make_cutoffs`, `split_by_cutoff(cutoffs, N_TEST)`, `build_features`, `build_labels`, `FEATURE_COLUMNS`, `WINDOW_DAYS`, `HORIZON_DAYS`; `train.make_logistic(SEED)`; `evaluate.classification_metrics`, `evaluate.baseline_metrics(y_train, y_test, x_test, inactive_days=RULE_DAYS)`.
- Produces (`upload_scoring.py`): `fit(events: pd.DataFrame, now: pd.Timestamp) -> dict`, the `scoring` JSON: `method` in `logistic`, `inactive_rule`, `rule_unchecked`, `unavailable`; `reason: str | None`; `fitted_at` (ISO); `history_days`; `model: {features, mean, scale, coef, intercept, threshold} | None`; `backtest: {train_rows, train_churners, test_rows, test_churners, train_cutoffs, test_cutoffs, model: {pr_auc, roc_auc, precision, recall}, rule: {...}} | None`. A failure is stored by the caller as `{"method": "failed", "reason": "scoring_failed"}`. `json_proba(model: dict, x: pd.DataFrame) -> np.ndarray`.
- Produces (`schemas/churn.py`): `AtRiskRow.risk_score: float | None` and new `days_inactive: float | None`; `AtRiskOut` gains `dataset_id: int`, `method: Literal["shipped_model", "logistic", "inactive_rule", "rule_unchecked"]`, `histogram_unit: Literal["risk_score", "days_inactive"]`, `backtest: dict | None`; `evaluation` stays for the demo and is `None` for uploads. The rule's histogram has 4 bins of 7 days over [0, 28). `UPLOAD_CAVEAT = "Churn here means no activity for 14 days, not cancellation. Results are measured on your file's own history, which shows the method worked recently, not that it will keep working."`
- `capabilities`: upload `churn` is True when `scoring.method` is `logistic`, `inactive_rule` or `rule_unchecked` and a signup exists. Upload cache key `(dataset.id, scoring["fitted_at"], cutoff)`.

- [ ] **Step 1: Write failing tests** (`test_upload_scoring.py`, pure): `test_recency_file_ranks_quiet_customers_first` (hand-built: churners go quiet before the cutoff; both methods' PR-AUC ≥ 0.9); `test_model_wins_when_churn_is_not_recency` (hand-built: every customer active daily; those with no `report_shared` in their window stop entirely in the next 14 days → `method == "logistic"`, model PR-AUC exceeds rule PR-AUC by more than `MARGIN`); `test_tie_goes_to_rule` (monkeypatch metrics so model − rule = 0.019 → `inactive_rule`); `test_no_training_label_inside_test_period` (`max(train_cutoffs) + HORIZON_DAYS <= min(test_cutoffs)`); `test_floors` (one fixture per floor at the limit and one below → `rule_unchecked`); `test_short_history` (27 days → `unavailable`; 28 days → `rule_unchecked`); `test_json_model_matches_sklearn` (max abs diff < 1e-9; `json.dumps` round trip holds only numbers and strings); `test_single_customer_and_identical_rows_do_not_crash`.
- [ ] **Step 2: Write failing API and view tests:** `test_import_runs_scoring_and_at_risk_serves_upload` (method and backtest present, `evaluation is None`, caveat equals `UPLOAD_CAVEAT`); `test_rule_view_shows_days_not_probability` (rows have `days_inactive`, `risk_score is None`, `histogram_unit == "days_inactive"`); `test_scoring_failure_keeps_dataset_and_retry_works` (monkeypatch `fit` to raise → import 201, `scoring_method == "failed"`; `POST /datasets/{id}/score` with `fit` restored → method set); `test_score_endpoint_404_for_foreign_or_demo`; frontend `test_upload_churn_shows_backtest_counts`, `test_upload_churn_never_shows_synthetic_metrics`, `test_rule_unchecked_label`.
- [ ] **Step 3: Run** → FAIL. **Step 4: Implement** (scoring runs after the import commits, in its own transaction; time it on a 50,000-event, 10,000-customer fixture and keep it under 20 s, lowering `MAX_CUTOFFS` if not). **Step 5: Run** both suites and ruff → green.
- [ ] **Step 6: Commit** `feat: churn on uploads trained and backtested on the file's own history`.

---

### Task 8: Purge script, docs, progress, review and real run-through

**Files:**
- Create: `backend/scripts/purge_uploads.py`
- Modify: `docs/03-system-design.md` (API table, frontend structure), `docs/04-request-flows.md` (upload flow), `docs/05-data-model.md` (datasets, migration 0003), `docs/06-security.md` (ownership, privacy, caches), `docs/08-operations-runbook.md` (purge, storage full), `docs/09-local-development.md`, `docs/metrics.md` (derived signup), `docs/model_card.md` (uploads use their own backtest), `docs/10-project-history.md`, `docs/history/phase-6-dashboard/history.md` (6b section), `progress.md` (Phase 6b items, summary row, date, test counts), `README.md`
- Test: `backend/tests/test_purge_uploads.py`

- [ ] **Step 1:** `purge_uploads.py --older-than DAYS [--dry-run]` deletes uploads whose `created_at` is older than DAYS (cascade) and prints only counts; a test covers dry run and delete.
- [ ] **Step 2:** Update the docs listed; validate every Mermaid block; tick `progress.md` and add the Phase 6b history.
- [ ] **Step 3:** Whole-branch review on the most capable model; one fix round.
- [ ] **Step 4:** Real run-through with the user on three files: one with no signup event, one with a zoneless timestamp column, one that starts mid-history (the D6a warning must appear). Record what was seen.
- [ ] **Step 5:** Commit `docs: Phase 6b docs, purge script, progress`; push; confirm CI; ask the user before merging.
