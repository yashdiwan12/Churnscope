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

## 6.5 Security checklist (Phase 7 gate)

- [ ] No secrets in Git history (`git log -p` scan)
- [ ] Missing / invalid / expired / wrong-user token tests pass
- [ ] Client-supplied identity cannot override verified identity
- [ ] Logs contain no tokens or unnecessary personal data
- [ ] CORS lists only required origins
- [x] RLS enabled on exposed tables and tested (`tests/test_rls.py`; checked on the Supabase project)
- [ ] Error responses expose no internals
- [ ] Dependencies reviewed (`pip-audit`)
