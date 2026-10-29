# History — phase-5-auth

**Status:** in progress · **Started:** 2026-10-29

## Done
- **RLS hardening (done first, as a standalone fix).** A read-only check of the Supabase project showed RLS off on all six tables and full `anon` privileges (including TRUNCATE on `events`); Supabase exposes `public` through its REST API, so the public anon key could have read or wiped the data. Nothing had been shared, so no exposure is known. Migration `0002_enable_rls` enables RLS on every table and revokes `anon`/`authenticated` grants plus their default privileges (guarded so it also runs on plain Postgres). Applied to Supabase with the user's approval; verified afterwards: RLS on for all 6 tables, 0 grants for `anon` and `authenticated`, backend role still sees all 42,847 events, and `/analytics/overview`, `/analytics/funnel`, `/churn/predict` still answer correctly.
- Tests (`tests/test_rls.py`): RLS flag on every table; a non-owner role with SELECT/INSERT granted sees 0 rows and cannot insert (functional proof, like Supabase's `anon`); the backend role still reads and writes. Migration downgrade/upgrade round-trips on the local test database. Suite: 112 passed.

## Decisions (brainstorming, 2026-10-29)
- Access: allow-list of Google accounts (`ALLOWED_EMAILS`, optional domains); everyone else gets 403.
- `POST /events`: service API key (`X-API-Key`), not a user login.
- Ownership: build minimal `/me/reports` (owner-filtered, 404 on other users' ids) so cross-user isolation tests protect something real.
- Design written as a spec for review: `docs/superpowers/specs/2026-10-29-phase5-auth-design.md`.

## Open items
- User review of the spec, then an implementation plan, then implementation.
- User setup needed at implementation time: Google OAuth client, Supabase Google provider and redirect URLs, `SUPABASE_URL`, anon key, JWT secret or JWKS confirmation, `ALLOWED_EMAILS`, `INGEST_API_KEY`.
