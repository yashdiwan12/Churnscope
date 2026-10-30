# 6. Security

## 6.1 Authentication vs authorization

- **Authentication** (who are you?): Supabase Auth with Google OAuth. The frontend obtains a JWT access token.
- **Authorization** (what may you do?): enforced **in the backend**. FastAPI verifies the token and filters every private query by the verified user id.

## 6.2 Decision: backend-enforced ownership

The backend connects to Postgres with a privileged credential, so RLS does not automatically know the end user. Therefore:

1. Backend verifies the JWT (signature, `exp`, `aud`, `iss`) and derives `user_id = sub`.
2. Every query on private tables includes `WHERE user_id = :verified_user_id` (centralised in repositories).
3. RLS is **enabled on all tables exposed through Supabase** as defence-in-depth `[Built]`: migration `0002_enable_rls` turns RLS on for every `public` table and revokes all `anon`/`authenticated` grants (and their default privileges). With no policies, the Supabase REST/Data API roles read and write nothing; the backend connects as `postgres`, which bypasses RLS. The frontend does not use the REST/Data API. Any table later exposed directly gets explicit, tested RLS policies. Before this migration (applied to the Supabase project on 2026-10-29) the tables had RLS off and `anon` held full privileges, so anyone with the project's public anon key could have read, changed or truncated them; nothing had been shared, so no exposure is known.
4. Cross-user access returns 404.

## 6.3 Secrets

| Secret | Lives in | Never in |
|---|---|---|
| DB password / `DATABASE_URL` | backend env | frontend, Git, logs |
| Supabase service-role key | backend env only (if used at all) | frontend, Git |
| `SUPABASE_JWT_SECRET` / JWKS config | backend env | frontend |
| Google OAuth client secret | Supabase dashboard | repo |
| `SUPABASE_ANON_KEY` | frontend env (public by design) | — |

Commit `.env.example`, never `.env`. Rotate any leaked credential immediately.

## 6.4 Threats and mitigations

| Threat | Mitigation |
|---|---|
| Forged/expired token | Server-side signature + expiry + audience checks; reject → 401 |
| Identity spoofing via request body | `user_id` only from token; body field ignored |
| Cross-user data access (IDOR) | Ownership filter in repositories; tests with two users |
| Duplicate/replayed events | Unique `event_id` + `ON CONFLICT DO NOTHING` |
| Malformed / oversized payload | Pydantic validation, size caps, event-name allow-list, timestamp bounds (no far-future or pre-2000 events, which would skew every default view) |
| SQL injection | SQLAlchemy parameterised queries only; no string-built SQL |
| Data leakage in logs/errors | Never log tokens or PII; generic error bodies; no stack traces |
| Cross-origin abuse | CORS restricted to dashboard origin (CORS ≠ authentication) |
| Model abuse / over-trust | Validated inputs; scores labelled as estimates |
| Label/feature leakage | Features limited to data at cutoff; tested |

## 6.4a Authentication and authorization as built `[Built]` (Phase 5)

**Boundary.** The backend is the only enforcement point. Supabase proves who the user is (Google sign-in, PKCE); FastAPI verifies the token itself and decides what that user may do. The database role the backend uses bypasses RLS; the Supabase REST roles (`anon`, `authenticated`) have no grants and RLS is on with no policies, so they read nothing. The Streamlit app never calls the Supabase REST API.

| Check | Where | Result |
|---|---|---|
| Signature, `exp`, `aud=authenticated`, `iss`, `role`, not anonymous, `sub` is a UUID | `core/security.py` | else 401; keys unreachable or auth unconfigured → 503 |
| Algorithms | same | ES256/RS256 from the project's JWKS; HS256 only with a configured secret; `none` and anything else rejected; a JWKS key is never an HMAC secret |
| Allow-list | `core/authorization.py` | exact lower-cased email or exact domain from `ALLOWED_EMAILS` / `ALLOWED_EMAIL_DOMAINS`; empty list allows nobody; no/non-string email → 403 |
| Sign-in method | same | `oauth` method and provider `google` (or absent), else 403 |
| Ownership | `db/reports.py` (only module touching `saved_reports`) | every function takes `user_id`; another user's id is a 404, never a 403 |
| Ingestion key | `core/authorization.py: ingest_key` | constant-time compare of SHA-256 digests; unset key → 503; missing/empty/wrong → 401 |
| Limits | routes | 5 MB body (413), 5,000 events (422), 100 reports per user (409), `filters` ≤ 4 KB |

Supabase project hardening (done by hand): Google provider on with a Testing-mode consent screen, redirect allow-list limited to the app origin, Email provider and anonymous sign-ins off.

Known limitations: the Streamlit session is lost on browser reload; the PKCE verifier store is per process; the allow-list is an environment variable (a change needs a restart).

## 6.5 Security checklist (Phase 7 gate)

- [ ] No secrets in Git history (`git log -p` scan)
- [x] Missing / invalid / expired / wrong-user token tests pass (`test_security.py`, `test_authorization.py`, `test_me_api.py`)
- [x] Client-supplied identity cannot override verified identity (`user_id` in a body is a 422; owner comes from the token)
- [ ] Logs contain no tokens or unnecessary personal data
- [ ] CORS lists only required origins
- [x] RLS enabled on exposed tables and tested (`tests/test_rls.py`; checked on the Supabase project)
- [ ] Error responses expose no internals
- [ ] Dependencies reviewed (`pip-audit`)
