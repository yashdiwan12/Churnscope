# History — phase-6-dashboard

**Status:** in progress · **Started:** 2026-10-30 · branch `phase-6-dashboard` (not merged)

## Done so far (each task independently reviewed; fix rounds logged in the SDD ledger, not in git)
- Design spec and plan written, then revised after an external review (cache key by `max(events.id)` so late events cannot leave a stale list; inclusive end date sent as next-day midnight; 422 handling; time basis per page; gate stops on 403/503 even with cached data; model note pinned to the model version; low-n rule per cell).
- Task 1: `latest_event_id`, `customer_external_ids`, read-first `current_profile` (no database write on every `/me`).
- Task 2: `GET /churn/at-risk` (ranked, paged, 10-bin histogram from rounded scores with integer math, evaluation block from artifact metadata, in-process cache). Review fix: one shared scoring helper instead of a copy.
- Task 3: date range conversion, labels, 30 s analytics timeout.
- Task 4: gate (`GET /me` on every rerun), `st.navigation`, fixed-message states, cached data layer, Overview page.
- Tasks 5-7: Funnel, Retention (incomplete and low-n cells, honest hover text), Engagement pages. Review fixes: shared percent formatter, tests proving slider/date values reach the request, a greying test that can actually fail, exact inclusive-end assertion.
- Task 8 (Churn Risk page): built (commit 24f607b), independent review in progress.

## Decisions
- Uploads become Phase 6b with its own design; saved views deferred; open-access mode and GitHub sign-in left to Phase 7.
- Views take `render(api)` (not `render(api, filters)`); date validation also enforces the API's 366-day limit.

## Open
- Task 9: real-API run-through with the user (also verifies the `app.py` page registration), docs, final whole-branch review, merge decision.
- Deferred minors are tracked in the SDD ledger and will be triaged by the final review.
