# Phase 6 Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five Streamlit pages (Overview, Funnel, Retention, Engagement, Churn Risk) behind the existing Google sign-in, each with labelled time basis, denominators, freshness and loading/empty/error states, plus one new API endpoint for a ranked churn-risk list.

**Architecture:** `app.py` runs a gate (sign-in, then `GET /me` on every rerun, stop on 403/503) and then `st.navigation` over five view functions. Views read through a cached `data.py` and draw with pure functions in `charts.py`; fixed-message error handling lives in `states.py`. The backend adds `GET /churn/at-risk` (scored once per data change, cached in-process) and makes `current_profile` read-first.

**Tech Stack:** FastAPI, SQLAlchemy, pandas/numpy, pytest (backend); Streamlit (`st.navigation`, `st.cache_data`, `AppTest`), Plotly, httpx (frontend).

**Spec:** `docs/superpowers/specs/2026-10-30-phase6-dashboard-design.md` (executors read both; section numbers below refer to it).

## Global Constraints

- Auth and access control are unchanged from Phase 5: allow-list, token checks, Google-sign-in requirement. No `ALLOW_ANY_GOOGLE_USER`, no GitHub sign-in in this phase.
- Banner on every page, exact text: `Demo data: synthetic events from a seeded generator, not real customers.`
- Frontend result cache: `st.cache_data(ttl=300)`, the `ApiClient` argument excluded from the cache key, only successes cached. Analytics reads use a 30 s timeout (`ANALYTICS_TIMEOUT = 30`); the client default stays 10 s.
- Date inputs: the end date is **inclusive** in the UI; the API gets `end` = midnight UTC of the **next** day. Start after end, or a span over 366 days (`MAX_RANGE_DAYS = 366`, the API's limit), is an inline sidebar message and **no API call**.
- Date filter on Overview, Funnel, Engagement only. Funnel also has a window slider 1-90 (default 14). Retention has a periods slider 1-26 (default 8) and no date filter. Churn Risk has no filter.
- Time basis lines: Overview/Funnel/Engagement `Window: 1 Oct to 30 Oct 2026 (31 days)` (exclusive end shown as the previous day) and `Data through DATE`; Retention `Cohorts as of AS_OF` / `Data through AS_OF`; Churn `Scored at cutoff CUTOFF using the 28 days before it` (from `window_days`) / `Data through DATA_THROUGH`.
- Fixed error copy: 422 and other 4xx (`ApiError`): `Those settings are not valid. Change the filters and try again.`; 403: `This account is not allowed to use Churnscope.`; 503/timeout: `The service is unavailable. Please try again shortly.` with a **Retry** button and `Results may be up to 5 minutes old.`; 401 returns to sign-in. No server text is ever shown.
- Rates shown to one decimal with `n=` denominators; scores labelled `risk score (relative)`, never "probability"; no chart is drawn from empty data (the empty state is shown instead).
- `LOW_N_MIN_ELIGIBLE = 20` in `charts.py`; a retention **cell** is "low n" when its `eligible` is below it.
- `BASELINE_NOTE_FOR_VERSION = "churn-lr-e330fa34d3"`: the "does not clearly beat the 'inactive 7 or more days' rule" sentence is shown only when `model_version` equals it; otherwise show `Compare with the naive baselines in the model card.`
- `/churn/at-risk`: `limit` 1-100 (default 50), `offset` 0-1,000,000, 10 equal histogram bins over [0, 1] built from the **rounded (4 dp) scores with integer arithmetic**, ranks distinct and 1-based by (`risk_score` desc, `customer_id` asc), cache key `(model_version, cutoff, max(events.id))`.
- Tests never touch the Supabase project (`TEST_DATABASE_URL`). Never print or commit `.env`. Ruff line length 100; run backend commands from `backend/`, frontend from `frontend/` with `uv run`. Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

Each line is pinned by a test in the task named in brackets.

1. Empty database (no events at all): every page shows its empty state and `/churn/at-risk` returns `cutoff = null`, zero counts and ten zero bins, never a crash or an empty chart [Tasks 2, 4-8].
2. A date range longer than 366 days or reversed is stopped in the sidebar; a single-day range (start = end) is valid and includes that day [Task 3].
3. Scores that sit exactly on a bin edge (0.0, 0.3, 0.7, 1.0) land in the right histogram bin, and a customer at exactly the threshold is `at_risk` in both the table and `at_risk_count` [Task 2].
4. A user who is removed from access or whose token expires between reruns sees no page content even though results are cached [Task 4].
5. Retention with all cohorts incomplete, a single cohort, or no cells; funnel with zero users at the first step (no division by zero, no `NaN` shown) [Tasks 5, 6].

---

### Task 1: Backend helpers and read-first profile

**Files:**
- Modify: `backend/app/db/repositories.py`, `backend/app/core/authorization.py` (`current_profile`)
- Test: `backend/tests/test_repositories_phase6.py`, `backend/tests/test_profile.py`

**Interfaces:**
- Produces: `repositories.latest_event_id(session: Session) -> int | None` (`max(events.id)`, `None` when empty); `repositories.customer_external_ids(session: Session, pks: list[int]) -> dict[int, str]`; `current_profile` unchanged in signature, now read-first.
- Consumes: `ingest_events(session, rows)` and the `session`/`engine` fixtures.

- [ ] **Step 1: Write failing tests.** `test_latest_event_id_none_when_empty`; `test_latest_event_id_grows_with_each_insert_even_when_timestamp_is_older` (ingest an event dated 2026-01-10, then one dated 2026-01-01; assert the id increased and `data_through` did not); `test_customer_external_ids_maps_pks_and_ignores_unknown`; `test_current_profile_inserts_once` (attach a SQLAlchemy `before_cursor_execute` listener to `engine`, count statements starting with `INSERT INTO user_profiles`; first call 1, second call 0, `created_at` unchanged).
- [ ] **Step 2: Run** `uv run pytest tests/test_repositories_phase6.py tests/test_profile.py -q` → FAIL (names missing / second call still inserts).
- [ ] **Step 3: Implement** the two repository helpers, and change `current_profile` to `session.get(UserProfile, user.id)` first, inserting with `ON CONFLICT DO NOTHING` and committing only when it is `None`.
- [ ] **Step 4: Run** the new tests and the full backend suite and ruff → green.
- [ ] **Step 5: Commit** `feat: latest_event_id, customer_external_ids and read-first current_profile`.

---

### Task 2: `GET /churn/at-risk`

**Files:**
- Modify: `backend/app/schemas/churn.py`, `backend/app/services/prediction.py`, `backend/app/api/routes/churn.py`
- Test: `backend/tests/test_at_risk_api.py`; add `("get", "/churn/at-risk", None)` to `PROTECTED` in `backend/tests/test_authorization.py`

**Interfaces:**
- Consumes: `repositories.load_events`, `latest_event_id`, `customer_external_ids`, `data_through` (Task 1); `features.build_features`, `features.WINDOW_DAYS/HORIZON_DAYS`; `ModelBundle(pipeline, metadata)` with `.version`, `.threshold`; `prediction.default_cutoff`, `prediction.CAVEAT`; the stub bundle pattern in `tests/test_churn_api.py` (`stub_bundle`, `StubPipeline`, `ingest`, `make_client`) which the new tests reuse by import or copy.
- Produces (`schemas/churn.py`): `HistogramBin(bin_start: float, bin_end: float, count: int)`; `AtRiskRow(rank: int, customer_id: str, risk_score: float, predicted_class: Literal["at_risk","not_at_risk"])`; `Evaluation(roc_auc: float|None, f1: float|None, precision: float|None, recall: float|None, threshold: float|None, test_churn_rate: float|None, n: int|None, synthetic: bool|None)`; `AtRiskOut(model_version, cutoff: datetime|None, data_through: datetime|None, window_days, horizon_days, decision_threshold, eligible_customers: int, at_risk_count: int, score_histogram: list[HistogramBin], rows: list[AtRiskRow], evaluation: Evaluation, caveat: str)`.
- Produces (`prediction.py`): `score_all(session, bundle, cutoff: pd.Timestamp) -> pd.DataFrame` (columns `customer_id` external id, `risk_score` rounded to 4 dp; sorted by score desc then id asc; empty frame when nobody is eligible); `at_risk(session, bundle, limit: int, offset: int) -> AtRiskOut`; `clear_at_risk_cache() -> None`.
- Produces (route): `GET /churn/at-risk` with the model dependency declared before the session dependency, `limit: Query(50, ge=1, le=100)`, `offset: Query(0, ge=0, le=1_000_000)`.

- [ ] **Step 1: Write failing tests** (hand-computed small dataset with the stub model; fixtures call `prediction.clear_at_risk_cache()` before each test). Names and assertions:
  - `test_counts_ranks_and_ordering`: known customers give exact `eligible_customers`, `at_risk_count`, `rows` order, ranks `1..n`; two customers with an identical score get distinct ranks ordered by `customer_id`.
  - `test_histogram_from_rounded_scores`: bin counts sum to `eligible_customers`; counts in bins at or above the threshold bin equal `at_risk_count`; scores 0.0, 0.3, 0.7, 1.0 land in bins 0, 3, 7 and 9 (Review Focus 3); a customer exactly at the threshold is `at_risk` in `rows` and counted in `at_risk_count`.
  - `test_paging_and_offset_beyond_end`: `limit=2&offset=2` returns ranks 3-4; offset past the end returns `rows == []` with counts unchanged.
  - `test_evaluation_comes_from_artifact_metadata`: metadata `test_metrics` and `data.synthetic` appear in `evaluation`; metadata without them gives `None` fields, not an error.
  - `test_empty_database` (Review Focus 1): 200, `cutoff is None`, `data_through is None`, `eligible_customers == 0`, ten zero-count bins, `rows == []`.
  - `test_cache_hit_and_invalidation`: spy on `features.build_features`; two identical calls build once; after ingesting a new event it builds again; **after ingesting a backdated event** (a new customer with activity in the 28 days before the cutoff, timestamp older than the current max) the next call rescored and `eligible_customers` grew by one.
  - `test_model_unavailable_is_503_even_when_db_broken`; `test_bounds_are_422` (`limit` 0, 101; `offset` -1, 1,000,001); 401/403/503 come from the shared `PROTECTED` matrix.
- [ ] **Step 2: Run** `uv run pytest tests/test_at_risk_api.py -q` → FAIL.
- [ ] **Step 3: Implement** schemas, `score_all` (load all events before the cutoff, build features at that one cutoff, predict with the artifact's `feature_columns`, map pks to external ids, round to 4 dp, sort), `at_risk` (cache lookup by `(bundle.version, cutoff, latest_event_id)` guarded by a lock holding one entry; histogram via integer arithmetic `min(round(score*10000)//1000, 9)`; `predicted_class` from the rounded score vs `bundle.threshold`), and the route. `evaluation` reads `bundle.metadata.get("test_metrics", {})` and `metadata.get("data", {}).get("synthetic")`.
- [ ] **Step 4: Run** the new tests, the authorization matrix and the full suite plus ruff → green.
- [ ] **Step 5: Commit** `feat: GET /churn/at-risk ranked list with event-id-keyed cache`.

---

### Task 3: Filters, labels and API client timeout (pure frontend code)

**Files:**
- Create: `frontend/filters.py`, `frontend/labels.py`
- Modify: `frontend/api_client.py`
- Test: `frontend/tests/test_filters.py`, `frontend/tests/test_labels.py`; extend `frontend/tests/test_api_client.py`

**Interfaces:**
- Produces (`filters.py`): `MAX_RANGE_DAYS = 366`; `validate_range(start: date, end: date) -> str | None` (message when `start > end` or `(end - start).days + 1 > MAX_RANGE_DAYS`, else `None`; `start == end` is valid); `to_api_range(start: date, end: date) -> tuple[str, str]` (`start` → `YYYY-MM-DDT00:00:00Z` of the start date, `end` → midnight of the **day after** the end date); `@dataclass DateSelection(start: str | None, end: str | None, error: str | None)`; `date_range_sidebar() -> DateSelection` (Streamlit: a "Latest 30 days" checkbox on by default returning `None, None, None`; otherwise two date inputs, calling `validate_range` and `to_api_range`).
- Produces (`labels.py`, no Streamlit): `window_label(window: dict) -> str`; `freshness_label(ts: str | None) -> str` (`Data through 30 Oct 2026` or `No data yet`); `cohorts_label(as_of: str | None) -> str`; `cutoff_label(cutoff: str | None, window_days: int) -> str`.
- Produces (`api_client.py`): `ANALYTICS_TIMEOUT = 30`; `get/post/delete(path, *, timeout: float | None = None, ...)` using the per-call timeout when given, else the client default `TIMEOUT`.

- [ ] **Step 1: Write failing tests**: `validate_range` (reversed → message; equal dates → `None`; 366 days → `None`; 367 → message; Review Focus 2); `to_api_range(date(2026,10,30), date(2026,10,30)) == ("2026-10-30T00:00:00Z", "2026-10-31T00:00:00Z")` and across a month end (`date(2026,10,31)` → `2026-11-01T00:00:00Z`); `window_label` for start `2026-10-01T00:00Z`, end `2026-10-31T00:00Z` → `Window: 1 Oct to 30 Oct 2026 (30 days)` and a 31-day example; `freshness_label(None) == "No data yet"`; `cutoff_label(..., 28)` text; `ApiClient.get(path, timeout=30)` passes `timeout=30` to the transport (MockTransport records `request.extensions["timeout"]`), default stays 10.
- [ ] **Step 2: Run** `uv run pytest tests/test_filters.py tests/test_labels.py tests/test_api_client.py -q` → FAIL.
- [ ] **Step 3: Implement** per Interfaces (labels parse ISO strings; month names via `strftime("%b")`, no locale).
- [ ] **Step 4: Run** the frontend suite and `uv run ruff check . && uv run ruff format --check .` → green.
- [ ] **Step 5: Commit** `feat: date range conversion, labels and per-call API timeout`.

---

### Task 4: Gate, navigation, states, data layer and the Overview page

**Files:**
- Create: `frontend/gate.py`, `frontend/states.py`, `frontend/data.py`, `frontend/charts.py`, `frontend/views/__init__.py`, `frontend/views/overview.py`, `frontend/tests/fake_api.py`
- Modify: `frontend/app.py` (reduce to config, banner, gate, navigation)
- Test: `frontend/tests/test_gate.py`, `frontend/tests/test_overview.py`, `frontend/tests/test_charts.py`; the old `tests/test_app.py` cases move into `test_gate.py` (sign-in link, unconfigured message, flow reuse stay green)

**Interfaces:**
- Consumes: `ApiClient`, `NotSignedIn`, `NotAllowed`, `ServiceUnavailable`, `ApiError`, `ANALYTICS_TIMEOUT` (Task 3); `auth.*` (Phase 5); `filters.date_range_sidebar`, `labels.*`.
- Produces (`gate.py`): `require_session() -> tuple[ApiClient, dict]` (the API client and the `/me` payload). Runs the sign-in flow when there are no tokens; refreshes tokens; calls `GET /me` on **every** rerun; 401 clears the session and shows sign-in; `NotAllowed` and `ServiceUnavailable` render the fixed message and a sign-out button then `st.stop()`; never returns on failure.
- Produces (`states.py`): `render_error(exc: Exception, retry_key: str) -> None` (fixed copy per the Global Constraints: `ApiError` text, `ServiceUnavailable` text + Retry button + stale note); `render_empty(message: str) -> None`.
- Produces (`data.py`): `overview(_api, start: str | None, end: str | None) -> dict`, `funnel(_api, start, end, window_days: int) -> dict`, `retention(_api, periods: int) -> dict`, `engagement(_api, start, end) -> dict`, `at_risk(_api, limit: int, offset: int) -> dict`; each `@st.cache_data(ttl=300, show_spinner=False)` and calls `api.get(path, timeout=ANALYTICS_TIMEOUT, **params)` omitting `None` params.
- Produces (`charts.py`): `LOW_N_MIN_ELIGIBLE = 20`; `dau_line(daily_active_users: list[dict]) -> go.Figure | None` (`None` for an empty list).
- Produces (`views/overview.py`): `render(api: ApiClient) -> None`.
- Produces (`tests/fake_api.py`): `install(monkeypatch, routes: dict[str, tuple[int, dict | None]]) -> list[str]` patching `httpx.Client.request` to answer by URL path from `routes` (missing path → test failure) and returning the list of requested paths; plus `ME_OK` and `OVERVIEW_OK` canned payloads.
- Produces (`app.py`): banner, `api, me = gate.require_session()`, sidebar "Signed in as" and sign-out, `st.navigation` over `st.Page(partial(view.render, api), title=..., url_path=...)` for the views built so far (only Overview in this task; later tasks append). The spec's `render(api, filters)` becomes `render(api)`: views read their own sidebar controls because only three pages have a date filter.

- [ ] **Step 1: Write failing tests** (a fixture clears `st.cache_data` and pre-sets `at.session_state["tokens"]` to a valid `Tokens`):
  - `test_no_session_shows_sign_in_and_no_page_content`; `test_401_from_me_returns_to_sign_in`.
  - `test_me_403_stops_with_no_page_content_even_with_cached_data` (Review Focus 4): run once with `/me` 200 and overview 200 (cache warm, "Active users" visible), switch `/me` to 403, rerun → fixed 403 text, a sign-out button, no "Active users", no further `/analytics/overview` request; same for 503.
  - `test_overview_renders_labels_denominators_and_banner`: banner text, `Window:` line, `Data through`, KPI labels and values, returning rate with `n=`.
  - `test_overview_empty_window_shows_empty_state` (`active_users == 0` and no daily rows): "No events in this window", no chart; `test_overview_503_shows_retry_and_stale_note`; `test_overview_other_4xx_shows_fixed_message_without_server_text`.
  - `test_sidebar_start_after_end_shows_message_and_makes_no_overview_call` (uncheck "Latest 30 days", set start after end; the recorded paths contain no `/analytics/overview`).
  - `test_dau_line_none_for_empty_and_figure_for_data` in `test_charts.py`; `test_data_caches_successes_only` (a 503 then a 200 for the same params both hit the API; two 200s hit once).
- [ ] **Step 2: Run** `uv run pytest -q` in `frontend/` → FAIL.
- [ ] **Step 3: Implement** the units per Interfaces. Move the existing sign-in functions from `app.py` into `gate.py` unchanged in behaviour; keep `FLOW_REUSE_SECONDS` there.
- [ ] **Step 4: Run** the frontend suite and ruff → green; run the app locally against the real API with the user's session only if the user is present (otherwise leave to Task 9).
- [ ] **Step 5: Commit** `feat: gate, navigation, states, cached data layer and Overview page`.

---

### Task 5: Funnel page

**Files:**
- Create: `frontend/views/funnel.py`
- Modify: `frontend/charts.py`, `frontend/app.py` (append the page)
- Test: `frontend/tests/test_funnel.py`; extend `test_charts.py`

**Interfaces:**
- Consumes: `data.funnel(_api, start, end, window_days)`, `filters.date_range_sidebar`, `labels.window_label/freshness_label`, `states.*` (Task 4); API payload `FunnelOut` (`window`, `window_days`, `eligible_users`, `steps[{step, users, conversion_from_previous, conversion_from_start}]`, `note`).
- Produces: `charts.funnel_bar(steps: list[dict]) -> go.Figure | None` (`None` when `steps` is empty or the first step has 0 users); `views/funnel.render(api)`.

- [ ] **Step 1: Write failing tests**: `funnel_bar` returns `None` for no steps and for zero users at step one (Review Focus 5), a figure with one bar per step otherwise; page smoke test shows the window slider (1-90, default 14), the `Window:` and `Data through` lines, `eligible_users` with `n=`, each step's count and conversion to one decimal, the API's `note`, no `NaN` text when a conversion is `None`; empty state; 503 retry.
- [ ] **Step 2: Run** the new tests → FAIL.
- [ ] **Step 3: Implement** `funnel_bar` and the view; add the page to the navigation.
- [ ] **Step 4: Run** the frontend suite and ruff → green.
- [ ] **Step 5: Commit** `feat: Funnel page`.

---

### Task 6: Retention page

**Files:**
- Create: `frontend/views/retention.py`
- Modify: `frontend/charts.py`, `frontend/app.py`
- Test: `frontend/tests/test_retention.py`; extend `test_charts.py`

**Interfaces:**
- Consumes: `data.retention(_api, periods)`; API payload `RetentionOut` (`as_of`, `period_days`, `periods`, `cells[{cohort, period, cohort_size, eligible, retained, retention, complete}]`).
- Produces: `charts.retention_matrix(cells: list[dict]) -> pd.DataFrame` (one row per cell with added boolean `low_n = eligible < LOW_N_MIN_ELIGIBLE` and a text `label`: rate to one decimal with `n=eligible`, `incomplete` or `low n` suffixes); `charts.retention_heatmap(matrix: pd.DataFrame) -> go.Figure | None` (`None` when the matrix is empty; incomplete cells drawn grey, not coloured by their rate); `views/retention.render(api)`.

- [ ] **Step 1: Write failing tests**: `retention_matrix` flags `low_n` exactly below 20 (19 yes, 20 no) and keeps `complete` as given; `retention_heatmap(empty) is None`; page smoke test: `Cohorts as of` and `Data through` lines, periods slider 1-26 default 8, **no date filter widgets**, a warning when any cell is incomplete (also when **all** cohorts are incomplete and when there is a single cohort — Review Focus 5), `low n` label present, empty state when `cells == []`, retention `None` cells shown as "not enough data" not `NaN`.
- [ ] **Step 2: Run** the new tests → FAIL.
- [ ] **Step 3: Implement** matrix, heatmap and view; add the page.
- [ ] **Step 4: Run** the frontend suite and ruff → green.
- [ ] **Step 5: Commit** `feat: Retention page with incomplete and low-n labelling`.

---

### Task 7: Engagement page

**Files:**
- Create: `frontend/views/engagement.py`
- Modify: `frontend/charts.py`, `frontend/app.py`
- Test: `frontend/tests/test_engagement.py`; extend `test_charts.py`

**Interfaces:**
- Consumes: `data.engagement(_api, start, end)`; API payload `EngagementOut` (`window`, `active_users`, `active_days_per_user_mean/median`, `events_per_active_user`, `median_hours_between_activities`, `feature_adoption: dict[str, float]`).
- Produces: `charts.adoption_bars(feature_adoption: dict[str, float]) -> go.Figure | None` (`None` when empty; values are shares of active users shown as percentages with one decimal); `views/engagement.render(api)`.

- [ ] **Step 1: Write failing tests**: `adoption_bars({}) is None`, bars sorted by share descending; page smoke test: window and freshness lines, metrics with `n=` active users, `None` metrics shown as `n/a`, empty state when `active_users == 0`, date-filter validation blocks the call, 503 retry.
- [ ] **Step 2: Run** the new tests → FAIL.
- [ ] **Step 3: Implement** and add the page.
- [ ] **Step 4: Run** the frontend suite and ruff → green.
- [ ] **Step 5: Commit** `feat: Engagement page`.

---

### Task 8: Churn Risk page

**Files:**
- Create: `frontend/views/churn.py`
- Modify: `frontend/charts.py`, `frontend/app.py`
- Test: `frontend/tests/test_churn_view.py`; extend `test_charts.py`

**Interfaces:**
- Consumes: `data.at_risk(_api, limit, offset)`; payload `AtRiskOut` (Task 2); `labels.cutoff_label/freshness_label`.
- Produces: `charts.risk_histogram(bins: list[dict], threshold: float) -> go.Figure | None` (`None` when every count is 0; a vertical line at `threshold`); `views/churn.BASELINE_NOTE_FOR_VERSION = "churn-lr-e330fa34d3"`; `views/churn.baseline_note(model_version: str) -> str`; `views/churn.render(api)` (page size 50 with a page number control, ranked table with columns rank, customer, risk score (relative), predicted class).

- [ ] **Step 1: Write failing tests**: `risk_histogram` returns `None` for all-zero counts and a figure whose layout has a vertical line at the threshold; `baseline_note("churn-lr-e330fa34d3")` contains `does not clearly beat`, any other version returns `Compare with the naive baselines in the model card.`; page smoke test: cutoff and `Data through` lines, model version, eligible and at-risk counts, the API caveat text, the evaluation block (ROC-AUC, F1, test churn rate, `synthetic` flag) and the label `risk score (relative)` with no "probability" anywhere; ranked table rows and paging (page 2 requests `offset=50`); empty state when `eligible_customers == 0` or `cutoff is None` (Review Focus 1); model unavailable (503) shows the retry message.
- [ ] **Step 2: Run** the new tests → FAIL.
- [ ] **Step 3: Implement** and add the page (all five now in the navigation).
- [ ] **Step 4: Run** the full frontend suite, the full backend suite and ruff on both → green.
- [ ] **Step 5: Commit** `feat: Churn Risk page`.

---

### Task 9: Manual end-to-end, docs and progress

**Files:**
- Modify: `docs/metrics.md` (low-n display rule), `docs/03-system-design.md` (API table: `GET /churn/at-risk`), `docs/04-request-flows.md` (dashboard and gate flow, at-risk flow, diagrams), `docs/model_card.md` (served-by list, the pinned baseline note), `docs/09-local-development.md` (run commands), `README.md`, `PLAN.md` (add Phase 6b roadmap entry), `docs/10-project-history.md` (Phase 6 row, add Phase 6b row), `docs/history/phase-6-dashboard/history.md`, `progress.md`, `.github/workflows/ci.yml` only if new env is needed

- [ ] **Step 1:** Run both servers with the user's `.env` (`uv run uvicorn app.main:app --port 8000` in `backend/`; `uv run --env-file ../.env streamlit run app.py` in `frontend/`), stop any stale processes first. Ask the user to sign in and visit all five pages, change the date range, trigger a reversed range, and confirm the banner, labels and caveats; record what they report. Stop both servers and delete any log files created.
- [ ] **Step 2:** Update the docs listed above to match what was built (real test counts from the final run, real endpoint shape); add Phase 6b ("Bring your own data": ownership migration, dataset-scoped queries and cache keys, CSV validation and mapping, limits, a churn report on a user's data) to `progress.md`, `PLAN.md` and doc 10; mark "Saved views" deferred and excluded from the count (phase total 7 of 7); validate all Mermaid diagrams render with the scratchpad `mm/check.py`.
- [ ] **Step 3:** Update `progress.md` per the standing instruction: tick Overview, Funnel, Retention, Engagement, Churn-risk, "Connected to FastAPI" and "Loading, empty, error states", set the summary row and date, and write the phase log (decisions, review findings, deferred minors).
- [ ] **Step 4:** Run `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .` in both `backend/` and `frontend/`; push the branch and confirm the GitHub CI run is green with `gh run watch`.
- [ ] **Step 5: Commit** `docs: Phase 6 dashboard complete`. Then the whole-branch review by a fresh most-capable-model reviewer, one fix pass with a failing test per finding, and the merge decision goes to the user.

---

## Self-Review

- **Spec coverage:** sections 3-4 (architecture, gate, navigation, filters, labels, states, pages) → Tasks 3-8; 5.1 endpoint → Task 2; 5.2 read-first profile → Task 1; 5.3 no access change → Global Constraints; 6 setup → Task 9 and the user's test-user step; 7 threat table → tests in Tasks 1-8 (cache invalidation T2, gate stop T4, inclusive end date T3, 422 T3/T4, model note T8, bounds T2, profile writes T1); 8 testing → per-task tests plus T9 manual run; 9 order/progress mapping → task order and T9 step 3; 10 risks → T9 notes.
- **Deviation from the spec, ledgered here:** views take `render(api)` instead of `render(api, filters)`, because only three of five pages have a date filter and each reads its own sidebar controls. Added a 366-day cap to `validate_range` (the API's own limit) which the spec did not mention.
- **Type consistency:** `validate_range`/`to_api_range`/`DateSelection` (T3) are used by T4-T7; `data.*` signatures (T4) match their callers in T5-T8; `AtRiskOut`/`Evaluation` (T2) match T8's use; `LOW_N_MIN_ELIGIBLE` (T4) used in T6; `BASELINE_NOTE_FOR_VERSION` defined in T8 only.
- **Proportion:** code appears only as signatures and test names with assertions.
