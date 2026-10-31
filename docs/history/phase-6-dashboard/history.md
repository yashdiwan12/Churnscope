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
