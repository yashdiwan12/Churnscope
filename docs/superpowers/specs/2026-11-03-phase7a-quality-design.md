# Phase 7a — Quality, security and docs (design)

Status: **draft for review** · Date: 2026-11-03 · Phase: 7a of 7 (7b = deploy, its own spec later)

## 1. Goal

Make the local workflow reliable and documented enough to deploy: a new developer can clone the repo, follow the README, and run the documented workflow (PLAN.md Milestone 7 exit). Nothing in 7a writes to Supabase, deploys, or touches Google settings.

## 2. Decisions (agreed 2026-11-02)

| # | Decision | Why |
|---|---|---|
| D1 | Phase 7 is split: **7a** (quality, security, docs; local only) merges first, then **7b** (deploy) gets its own spec and plan | PLAN.md: deploy only after the local workflow is reliable; 7b's outward steps each need the user's approval |
| D2 | The deployed app keeps the Google consent screen in **Testing mode with named test users** (recorded here for 7b; no 7a work) | No domain or privacy page needed; matches the allow-list model |
| D3 | 7a is an **audit and gap-fill**, not a new test suite | The audit (section 3) found most of PLAN.md's testing plan already covered |
| D4 | Minor findings from earlier phases are **triaged**: cheap fixes a user can hit are fixed; the rest are written down as accepted limitations with a reason | Leaves no silent backlog before deploy |
| D5 | Screenshots are **taken by the user by hand** from a fixed list; no headless browser automation | Google sign-in blocks automated capture |
| D6 | progress.md's 10 Phase 7 items: the first 9 belong to 7a, "Deploy" to 7b | The tracker keeps PLAN.md's milestone list |

## 3. Audit result (starting point)

Already covered by tests (no new work, listed in the traceability table): valid/invalid/duplicate events, bad timestamp and oversized payloads (`test_ingestion.py`, `test_events_api.py`, `test_datasets_check_api.py`); active users, funnel, retention incl. incomplete cohorts, empty ranges, time-zone boundaries (`test_metrics.py`, `test_analytics_api.py`, `test_features.py`); missing/invalid/expired token, cross-user access, client-supplied identity (`test_security.py`, `test_authorization.py`, `test_me_api.py`, `test_reports.py`, `test_dataset_routes.py`); feature schema, training-only preprocessing, artifact version, round trip, malformed inputs (`test_ml.py`, `test_features.py`, `test_churn_api.py`); database failures as 503 (`test_db_unavailable.py`); secrets absent from responses and logs (`test_authorization.py`, `test_events_api.py`, upload tests); dashboard API errors (`frontend/tests`).

Gaps: (a) no test runs events through `POST /events` and checks analytics output end to end; (b) no test proves a failed database **write** is never answered with 2xx; (c) no screenshots; (d) the README has never been followed from a fresh clone, and its Status paragraph predates 6b's merge; (e) doc 06 section 6.5 checklist has five open boxes; (f) deferred minors from Phases 5, 6 and 6b are untriaged.

## 4. Work

### 4.1 Traceability and missing tests
- New section **8.7 Test coverage** in `docs/08-operations-runbook.md`: a table with one row per item of PLAN.md section 13 (Ingestion, Analytics, Authentication and authorization, ML, Integration), each naming the test file and test function that covers it.
- New test: a small hand-built set of events posted through `POST /events` (service key), then `GET` overview, funnel and retention for dataset 1 return the hand-calculated numbers.
- New test: for each write path (`POST /events`, `POST /datasets`, `DELETE /datasets/{id}`, `POST /me/reports`), a database error during the write gives a non-2xx status and leaves no partial rows.
- Model evaluation: the model card's numbers are re-checked against a fresh `train` run on the demo data (seeded); any mismatch is corrected in the card. The checkbox "Actual model evaluation documented" is ticked on that evidence.

### 4.2 Minor findings: fix list
Fixed in 7a (each with a test):
1. A replace during `POST /datasets/{id}/score` or the import's refresh returns 404 `Dataset not found`, not 500.
2. The scoped 422 handler matches `/datasets` and `/datasets/...` only, not `/datasets-foo` (`backend/app/main.py`).
3. `scripts/purge_uploads.py` prints one line naming the error type on a connection failure, never a traceback or the URL, and exits non-zero.
4. The data selector keeps the user's chosen dataset after a transient `GET /datasets` error (shows the error state, does not switch to demo).
5. The `too_few_train_non_churners` floor gets its test.
6. A stored upload name has path components and `..` removed (display only; never used as a path).
7. Doc 03's module diagram shows the 6b modules and section 3.4 no longer says "route pending"; doc 05's ER diagram marks `datasets.owner_id` nullable.

Everything else from the Phase 5, 6 and 6b deferred lists is written into **section 8.6 Known limitations** of doc 08, one line each with the reason it is accepted (for example: login CSRF needs a cookie-bound state and the impact is limited to allow-listed users; no rate limit on `/datasets/check` while access is allow-listed; no automatic upload expiry, manual purge script; the 0.02 margin and floors are judgement calls). The history files point to that section.

### 4.3 Security pass
- Run the `security-review` skill over the repository.
- Secrets in Git history: scan all commits for key, token and password patterns (a local scan; nothing uploaded). Any hit is reported to the user before any history rewrite.
- Logs: list every logging call and confirm none writes tokens, emails beyond what is documented, or file values.
- Error responses: confirm every error handler returns fixed messages (no stack traces, SQL or input echo).
- CORS: default is no origins; only `CORS_ORIGINS` adds them; documented for 7b.
- Frontend exposure: only the anon key and public URLs reach the browser.
- Dependencies: `pip-audit` on backend and frontend lock files; fix or record each finding.
- Result: doc 06 section 6.5 boxes ticked with evidence, or left open with a named reason.

### 4.4 Fresh-clone README run
- Clone the repo into the scratchpad and follow the README's Quick start exactly against local Docker Postgres (never Supabase), through generator, loader, migrations, training, API, tests and frontend start.
- Every step that fails, is missing, or needs knowledge not written down is fixed in the README or doc 09. The run itself is recorded in the 7a history (steps, time, fixes).
- README Status paragraph rewritten for the current state (6b merged, 7a in progress, deploy pending), plus a short "What it does" with the screenshots.

### 4.5 Screenshots
- The user signs in locally on the demo dataset and saves six PNGs: `signin.png`, `overview.png`, `funnel.png`, `retention.png`, `churn.png`, `upload.png` (the Upload page before any file is chosen), into `docs/images/`.
- Before committing, each image is checked for private data: demo data only, no email address other than one the user approves showing, no tokens or URLs with codes.
- README links them; files stay under 500 KB each.

## 5. Out of scope
Deploying, Supabase migrations or writes, Google console changes, new features, saved views UI, automatic upload expiry, rate limiting, the cookie-bound login state.

## 6. Testing and review
- All new and changed code gets tests; backend tests use `TEST_DATABASE_URL` (local Docker `churnscope_test`) only.
- Branch `phase-7a-quality`, executed subagent-driven, each task independently reviewed, then a whole-branch review and a merge with the user's approval.
- Done when: backend and frontend suites and ruff pass; doc 08 section 8.7 has a row for every PLAN.md section 13 item; doc 06 section 6.5 has no unexplained open box; the fresh-clone run finished with no undocumented step; progress.md ticks the 9 7a items with the date and the history file is filled in.

## 7. Plan outline
1. Traceability table and the two missing tests; model card re-check.
2. Backend minor fixes (4.2 items 1, 2, 3, 5, 6).
3. Frontend minor fix (item 4) and doc diagram fixes (item 7); Known limitations section.
4. Security pass (4.3) and its fixes.
5. Fresh-clone README run and README/doc 09 fixes.
6. Screenshots (user step) and README links; progress and history.
