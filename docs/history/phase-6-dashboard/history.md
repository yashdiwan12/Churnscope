# History — phase-6-dashboard

**Status:** done, merged into `main` · **Started:** 2026-10-30 · branch `phase-6-dashboard` (not merged)

## Done (each task independently reviewed; fix rounds logged in the SDD ledger, not in git)
- Design spec and plan written, then revised after an external review (cache key by `max(events.id)` so late events cannot leave a stale list; inclusive end date sent as next-day midnight; 422 handling; time basis per page; gate stops on 403/503 even with cached data; model note pinned to the model version; low-n rule per cell).
- Task 1: `latest_event_id`, `customer_external_ids`, read-first `current_profile` (no database write on every `/me`).
- Task 2: `GET /churn/at-risk` (ranked, paged, 10-bin histogram from rounded scores with integer math, evaluation block from artifact metadata, in-process cache). Review fix: one shared scoring helper instead of a copy.
- Task 3: date range conversion, labels, 30 s analytics timeout.
- Task 4: gate (`GET /me` on every rerun), `st.navigation`, fixed-message states, cached data layer, Overview page.
- Tasks 5-7: Funnel, Retention (incomplete and low-n cells, honest hover text), Engagement pages. Review fixes: shared percent formatter, tests proving slider/date values reach the request, a greying test that can actually fail, exact inclusive-end assertion.
- Task 8: Churn Risk page (ranked at-risk list, histogram, collapsed "About this model" with evaluation and baseline note).
- Sign-in fix: the Google link now continues in the same tab (anchor with `target="_self"`; `st.link_button` always opened a new tab).
- UI cleanup: Streamlit toolbar, footer and error details hidden; event names, model details and baseline note moved into collapsed expanders.
- Sorting: `GET /churn/at-risk` takes `sort` (`risk_desc`, `risk_asc`, `customer_asc`; rank always stays the global risk rank); Churn Risk has a Sort by selector that resets to page 1; rank and score are numeric columns; Retention cell details is a sortable table with numeric retention and status.
- Repository history: Co-Authored-By trailers were removed from all commits (rewrite, then the user recreated the GitHub repo and a clean history was pushed), so hashes in older notes are stale.
- Final state: backend 281 tests, frontend 115 tests, CI green on the branch.

## Decisions
- Uploads become Phase 6b with its own design; saved views deferred; open-access mode and GitHub sign-in left to Phase 7.
- Views take `render(api)` (not `render(api, filters)`); date validation also enforces the API's 366-day limit.

## Open
- Deferred minors (ledger): one-time Streamlit log warning on the first sort change, sort resets to default after an error or empty run, `/me` uses a 10 s timeout so a cold database start shows "unavailable", customer-id sort is lexicographic, page number has no maximum, `date.today()` vs UTC default end date.
- Phase 6b (uploads) needs its own design; Phase 7 inherits the deployment and consent-screen items.

## Phase 6b — Bring your own data (uploads)

**Status:** built on branch `phase-6b-uploads`, merge pending · **Date:** 2026-11-01 · spec: [2026-11-01-phase6b-uploads-design.md](../../superpowers/specs/2026-11-01-phase6b-uploads-design.md) · plan: [2026-11-01-phase6b-uploads.md](../../superpowers/plans/2026-11-01-phase6b-uploads.md) · executed subagent-driven, every task independently reviewed.

### Done
- Task 1: migration `0003_datasets` (datasets table, demo = id 1, `dataset_id` on customers and events, per-dataset uniques, composite FK, new indexes, RLS), `db/datasets.py` ownership rules, ingestion conflict targets per dataset, `POST /events` pinned to dataset 1.
- Task 2: `?dataset_id=` on analytics and churn routes with a visibility dependency (404 `Dataset not found`), churn cache keyed per dataset and bounded to 4 entries.
- Task 3: CSV parsing and `POST /datasets/check` (multipart, size limits enforced while reading, scoped 422 handler, first-week share and the approximate-signup warning).
- Task 4: `POST /datasets` (mapping, derived signup, 5% invalid rule, one transaction under a global advisory lock, 300,000-event cap with 409 `storage_full`), `GET /datasets`, `DELETE /datasets/{id}` with cache eviction.
- Task 5: Data selector (`dataset.py`), dataset- and user-keyed caches, banner, notes for derived signup and missing capabilities, fallback to demo on 404.
- Task 6: Upload data page (template, notice, check, mapping, replace confirmation, import, delete). Review fixes: the replace confirmation and Delete are offered whenever the user has an upload, whichever dataset is selected.
- Task 7: churn on uploads (`services/upload_scoring.py`): weekly cutoffs, purge gap, logistic vs days-since-last-activity rule, floors and fallbacks (`rule_unchecked`, `unavailable`, `failed` with Retry), model stored as JSON numbers, `POST /datasets/{id}/score`, upload branch of `/churn/at-risk` and the Churn Risk page. Fit on 50,000 events and 10,000 customers took 0.8 s.
- Task 8: `scripts/purge_uploads.py --older-than DAYS [--dry-run]` (counts only), docs 03-06, 08-10, metrics, model card, README, progress.

### Decisions
- Churn on an upload is learned and tested on that file's own history; the synthetic-data model is never used on uploads (spec D9). The model is JSON numbers, not a pickle (D10).
- One upload per user, replace in one transaction, 404 (never 403) for other people's ids (D3, D5).
- "First event counts as signup" derives a `signup` event (D6); the left-censoring warning fires at 25% of customers starting in the file's first week and needs an acknowledgement (D6a).
- 5% invalid rows reject the file, ignored and duplicate rows excluded from the denominator (D8).

### Results / evidence
- Scoring trial run (2026-11-01, local, throwaway script, five versions of the demo file): full file (180 days, 2,000 customers) checked, rule won (PR-AUC 0.821 vs 0.820), 1.4 s; last 10 weeks with derived signup checked, rule won (0.809 vs 0.796), 0.4 s; last 6 weeks `rule_unchecked`; 150 customers `rule_unchecked` (135 test rows); five copies (10,000 customers, 214,235 events) 2.7 s. No leakage; the JSON model matched scikit-learn exactly. The trial also showed the 50% censoring threshold stayed silent at 45% (a 10-week slice), so it became 25%.
- Task 0, import timing on the real Supabase project (2026-11-01, session pooler, scratch schema dropped afterwards): connect and first statement 3.1 s; 10,000 customers 2.0 s; 10,000 customers plus 50,000 events 6.7 s; loading 50,000 events back 1.5 s; cascade delete 0.9 s; statement timeout 2 min. A worst-case replace plus scoring is about 10 to 12 s, so the 5 MB, 50,000-row and 10,000-customer limits stand. Free-tier cold start not measured.
- Tests: backend 392 passed (2 opt-in timing tests skipped), frontend 192 passed with `-W error`; ruff clean.

### Open
- Run-through with the user on three files (no signup event, zoneless timestamps, starts mid-history), whole-branch review and merge are still to do at the time of writing.
- Deferred minors (SDD ledger): no Retry when storing the scoring result fails (scoring stays empty until a re-import or `/score`); the exact 0.02 margin is compared without a float tolerance; a replace during scoring can give a 500 instead of 404; the check endpoint has no rate limit; the 0.02 margin and floors are judgement calls to revisit after the run-through; deleting profiles is not automated.
- No automatic expiry of uploads: manual purge script only; automatic expiry waits for Phase 7.
- The 300,000-event cap size estimate is re-measured on the real project before deploy (Phase 7).
