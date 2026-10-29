# History — phase-3-analytics

**Status:** done · **Dates:** 2026-10-24

## Done
- `backend/app/services/metrics.py`: added `new_users`, `returning_users`, `daily_active_users`, `engagement` (active days, events per user, median gap, feature adoption).
- `backend/app/db/repositories.py`: `data_through`, `load_events` (optional SQL-side window filter).
- `backend/app/services/analytics.py`: window validation/defaults and orchestration of repository + metrics.
- `backend/app/schemas/analytics.py`: Pydantic response models.
- `backend/app/api/routes/analytics.py`: `/analytics/overview|funnel|retention|engagement`, mounted in `main.py`.
- Tests: `tests/test_metrics.py` (new/returning, DAU, engagement by hand) and `tests/test_analytics_api.py` (endpoints vs hand-computed values on a seeded Postgres, incl. censoring, incomplete cohorts, invalid parameters, empty database, OpenAPI).
- Docs: `docs/metrics.md` (engagement + API sections), doc 10 table.

## Decisions
- Censoring point is the latest event in the database (`data_through`), not `now()`, so stale data does not look like churn. Returned in every response.
- Funnel endpoint scopes to customers whose signup is in the window; retention always covers all cohorts.
- Metrics are computed in Pandas over rows fetched by the repository (SQL filters by window where possible). Accepted for MVP scale; SQL aggregation is the path if volume grows.
- Endpoints are unauthenticated until Phase 5; the router has a marked place for the auth dependency.

## Evidence
- `uv run pytest -q`: 35 passed; ruff clean.
- Live run on the Supabase copy of the seed-42 synthetic log (default window 2026-05-31..06-30): 815 active users, 196 new, 623 returning; funnel 196 -> 147 -> 64 eligible-user counts. These reflect generator assumptions, not real behaviour.
- Latency (single runs from the dev machine to the Seoul-region Supabase pooler, not benchmarks): overview/engagement ~1.2-1.5 s warm after a SQL-side window filter (first call ~5 s incl. connection setup); funnel and retention ~4 s because they read the full history.

- Re-measured 2026-10-29 on the regenerated data (42,847 events; warm single runs, indicative only): overview ~1.0 s, funnel ~1.5 s, retention ~1.4 s. Default window: 816 active, 196 new, 625 returning; funnel 196 -> 147 -> 88 eligible-user counts (the earlier 64 for the last step was an artifact of the generator drawing events out of order). One earlier run during Docker Desktop startup took 12-53 s, so latency numbers are load-dependent.

## Open items
- Funnel/retention fetch full history; move to SQL aggregation or caching if latency matters. Add indexes only after `EXPLAIN` on those queries.
- Add auth dependency to the router in Phase 5.
