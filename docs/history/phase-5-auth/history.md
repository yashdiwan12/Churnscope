# History — phase-5-auth

**Status:** done · **Started:** 2026-10-29 · **Finished:** 2026-10-30

## Done
- **RLS hardening (first, as a standalone fix).** A read-only check of the Supabase project showed RLS off on all six tables and full `anon` privileges (including TRUNCATE on `events`); Supabase exposes `public` through its REST API, so the public anon key could have read or wiped the data. Nothing had been shared, so no exposure is known. Migration `0002_enable_rls` enables RLS on every table and revokes `anon`/`authenticated` grants plus default privileges (guarded for plain Postgres). Applied to Supabase with the user's approval and verified.
- **Token verification** (`core/security.py`): ES256/RS256 from the project's JWKS, HS256 only with a configured secret, `none` and everything else rejected; `exp`, `sub` (UUID), `aud`, `iss`, `role`, not anonymous; fails closed (503) when keys cannot be fetched. Forged-token test matrix with locally minted keys, no network.
- **Authorization** (`core/authorization.py`): allow-list by exact lower-cased email or domain, empty list allows nobody, Google sign-in required; applied as a router dependency to analytics and churn.
- **`/me` and `/me/reports`** with ownership enforced only in `db/reports.py`; foreign ids are 404; max 100 reports per user, enforced under a row lock; two-user isolation tests in both directions.
- **`POST /events`** with `X-API-Key` (constant-time compare, closed with 503 until configured), 5 MB and 5,000-event limits.
- **Streamlit** sign-in with PKCE (`frontend/auth.py`), API client mapping 401/403/503, sign-out, refresh before expiry.
- **Real sign-in spike** (2026-10-30): the five unknowns settled and recorded in spec section 3.1. The project uses an ES256 signing key; `?flow=` matches the redirect allow-list; sign-in, sign-out and a reload (asks to sign in again) were checked by hand.
- Docs: security doc section 6.4a, API table, request flows, README, model card.

## Review
One independent whole-branch review (most capable model, read-only). No auth bypass, IDOR, algorithm confusion or secret leak found. Fixed, each with a test that failed first:
- a non-string `alg` header crashed the verifier with an unauthenticated 500 (`test_non_string_alg_header_is_invalid_token`);
- huge integers in `/me/reports?offset=` and `DELETE /me/reports/{id}` were a database error and a 500 (`test_list_bounds_are_422`, `test_invalid_report_ids_are_422`);
- a malformed or broken JWKS response was a 500 instead of 503 (`test_malformed_or_broken_jwks_response_is_auth_unavailable`);
- a test read the real `.env` allow-list and failed on the developer machine (the test now ignores the env file);
- `Content-Length` parsing used `isdigit()` (now `int()` with a 411 on failure; `test_missing_content_length_is_411` added);
- reruns of the signed-out page created one pending sign-in each, which could flush others' pending flows (now one per browser session).
A chunked request with a conflicting `Content-Length` was checked live: the server answers 400 before our code runs.

## Deferred minors
Accepted and written up in [doc 08 section 8.6](../../08-operations-runbook.md#86-known-limitations-built-phase-7a).
- A network blip while refreshing the token signs the user out (any refresh failure clears the session).
- Login CSRF: the PKCE verifier is tied to the server process, not the browser that started the flow, so an allow-listed attacker could hand a victim a sign-in link for the attacker's own account. Low impact (the attacker must be allow-listed; the app shows only the account's own data). A cookie-bound state needs a Streamlit component and is left for a later hardening pass.

## Decisions (brainstorming, 2026-10-29)
- Access: allow-list of Google accounts (`ALLOWED_EMAILS`, optional domains); everyone else gets 403.
- `POST /events`: service API key (`X-API-Key`), not a user login.
- Ownership: minimal `/me/reports` so cross-user isolation tests protect something real.
- Executed inline on branch `phase-5-auth`; the spike ran after the offline backend and frontend work because it needed the user's Google and Supabase setup.

## Open items
- Phase 7: add the deployed app URL to the Supabase redirect allow-list and the Google client origins; move `ALLOWED_EMAILS` and keys into the host's secret store.
- A non-allow-listed Google account was not tried against the real service (covered by tests with minted tokens).
