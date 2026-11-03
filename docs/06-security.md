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
| Cross-origin abuse | CORS empty by default; set `CORS_ORIGINS` only if a browser calls the API (CORS ≠ authentication) |
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

### Dashboard behaviour (Phase 6) `[Built]`

- The gate calls `GET /me` on every Streamlit rerun, so a revoked allow-list entry or an expired token stops the user even when results are cached. 401 clears the session and shows sign-in; 403/503 show a fixed message with Sign out and stop the page.
- Error messages shown to users are fixed strings; Streamlit's error details, toolbar and footer are hidden (`frontend/.streamlit/config.toml`, read only when launched from `frontend/`). Tokens are never rendered.
- The sign-in link is a same-tab anchor to the Supabase authorize URL (PKCE).
- Query parameters (`sort`, `limit`, `offset`, dates) are validated by the API; the UI cannot send a range over 366 days.
- The 5-minute result cache is keyed by dataset id and signed-in user id (Phase 6b), so it is safe once data is private; see 6.4b.

Known limitations: the Streamlit session is lost on browser reload; the PKCE verifier store is per process; the allow-list is an environment variable (a change needs a restart).

## 6.4b Uploaded data `[Built]` (Phase 6b)

Users can upload their own events. The file may hold real customer identifiers, so it is treated as private to its owner.

**Ownership.** `db/datasets.py` is the one place that decides visibility: a dataset is visible if it is the demo (id 1) or the caller owns it. Every `?dataset_id=` route, `DELETE /datasets/{id}` and `POST /datasets/{id}/score` use it. A missing id, someone else's id, or (for delete and score) the demo is **404 `Dataset not found`**, never 403, so ids do not leak existence. At most one upload per user (partial unique index), and `POST /events` and the loader write to dataset 1 only. A composite foreign key stops an event from pointing at another dataset's customer.

**Privacy.**
- No value from a file reaches a log or an error body. Skip reasons are a row number and a code. Database failures during an import or scoring are logged by exception type only (the exception text carries SQL parameters, which are file values) and the traceback chain is dropped.
- The `/datasets` routes have their own 422 handler (`main.py`) that returns only the field path and message, never the offending input, because FastAPI's default 422 echoes it. Other routes keep the default handler.
- Only `customer_id`, `event_name`, `event_timestamp` and `event_id` are stored; other columns are ignored. The original file is not kept, only a cleaned file name.
- Delete is real: customers and events cascade, the scoring JSON goes with the row, and the backend evicts that dataset's churn-cache entries (scored rows hold customer ids). The acting browser session also clears its result cache, and the selector re-checks `GET /datasets` on every rerun, so a deleted dataset is never served from the cache of another session. There is no automatic expiry yet: the notice tells the user the file is kept until deleted, and the operator can run `scripts/purge_uploads.py` ([runbook](08-operations-runbook.md)).

**Limits.** Request body 5.5 MB (411 without Content-Length, 413 over; checked before parsing) and file part 5 MB, read in chunks; the Streamlit uploader refuses over 5 MB in the browser (`maxUploadSize`); at most 50,000 event rows, 10,000 customers, 50 distinct event names, 100 characters per id or name, 5 form fields; the whole file is rejected if more than 5% of counted rows are invalid; a global cap of 300,000 uploaded events returns 409 `storage_full`. The cap check, the delete of the old upload and the insert share one transaction-scoped advisory lock, so two imports cannot both pass the cap and a failed import keeps the old data. The check endpoint has no rate limit beyond these caps and the allow-list (revisit in Phase 7).

**Stored models are JSON, not pickles.** An upload's fitted model is plain numbers (feature names, scaler means and scales, coefficients, intercept) applied as a dot product, so reading it can never run code. The shipped demo model remains a joblib pickle, guarded by its hash (see the [model card](model_card.md)).

**Caches.** The frontend result cache keys on dataset and user; the backend churn cache keys on dataset (demo: also model version, cutoff and newest event id; upload: scoring fitted-at) and holds at most 4 entries.

## 6.5 Security checklist (Phase 7 gate)

- [x] No secrets in Git history (`git log -p --all` scan of 98 commits, 2026-11-03; section 6.6)
- [x] Missing / invalid / expired / wrong-user token tests pass (`test_security.py`, `test_authorization.py`, `test_me_api.py`)
- [x] Client-supplied identity cannot override verified identity (`user_id` in a body is a 422; owner comes from the token)
- [x] Logs contain no tokens or unnecessary personal data (all 10 `logger.` calls in `backend/app` log exception type names or fixed text; section 6.6)
- [ ] CORS lists only required origins (the code default is now empty and tested in `test_health.py`; the deployed value is set with the dashboard URL in Phase 7b, so the box closes there)
- [x] RLS enabled on exposed tables and tested (`tests/test_rls.py`; checked on the Supabase project)
- [x] Error responses expose no internals (all 28 `HTTPException` sites and both `JSONResponse` handlers return fixed text or field paths; section 6.6)
- [x] Dependencies reviewed (`pip-audit` on both locked environments, 2026-11-03: no known vulnerabilities; section 6.6)

## 6.6 Phase 7a security pass

Run on 2026-11-03 on branch `phase-7a-quality`, local only (no Supabase connection, no `.env` read).

| Check | What was run | Result |
|---|---|---|
| Secrets in Git history | `git log -p --all` (98 commits, about 47,000 lines) searched for key, secret, password, `service_role`, JWT-shaped strings, database URLs with a password, Google/Supabase/GitHub/AWS key shapes and private-key headers; files ever added matching `.env`, `.pem`, `.key`, `client_secret` | 300 keyword hits, all classified: test fixtures (`ingest-key-0123...`, `user:secret@127.0.0.1:1`, `user:password@host`), the local Docker database login (`churnscope`, defined in `docker-compose.yml`, localhost only), `https://p.supabase.co`-style placeholders, header names and doc text. No JWT-shaped string, no key or private-key header, no real project URL. Only `.env.example` was ever committed as an env file. **No real secret found; nothing rewritten.** |
| Logs | grep of `logger.` in `backend/app`: 10 calls (5 in `routes/datasets.py`, 4 in `main.py`, 1 in `services/uploads.py`) | Every call logs a fixed text, a counter, the model version or `type(exc).__name__`. The one `logger.warning` that formats an exception (`churn model unavailable: %s`) uses `ModelUnavailable`, whose messages are fixed strings in `ml/artifact.py`. `logger.exception` in the lifespan hook records a traceback for a model-load failure only (no request data). No tokens, emails or file values. |
| Error responses | grep of `HTTPException` and `JSONResponse` in `backend/app`: 28 `HTTPException` sites, 2 `JSONResponse` | All fixed messages, upload `code` and `message` pairs, or field path plus message. Two sites pass `str(exc)` from `analytics.InvalidRange`, whose texts are fixed (`start must be before end`, `window must not exceed N days`). Unhandled errors give FastAPI's plain 500. Accepted: on routes outside `/datasets`, `/events` and `/me`, FastAPI's default 422 echoes the caller's own query or body input back to that caller; nothing from other users or the server. |
| CORS | `Settings.cors_origins` | **Finding, fixed:** the code default was `http://localhost:8501`, not empty. It is now empty, so no cross-origin access exists unless `CORS_ORIGINS` is set; two tests in `test_health.py` (unset gives an empty list, a list is split and trimmed). The Streamlit app calls the API from its server, so it needs no CORS entry. Methods stay `GET, POST, DELETE` and headers `Authorization, Content-Type` (`X-API-Key` is not allowed cross-origin, tested). |
| Frontend exposure | grep of `os.getenv`, `os.environ`, `st.secrets` in `frontend/` (not tests, not `.venv`) | Only `gate.py` reads configuration: `API_BASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `APP_BASE_URL`. No other variable and no `st.secrets` use. The only `unsafe_allow_html` that includes a variable is the sign-in link, whose URL goes through `html.escape(quote=True)`. |
| Dependencies | `uv export --format requirements-txt` per project, then `uvx pip-audit --no-deps --disable-pip` on the export (backend 55 pinned packages, frontend 44) | No known vulnerabilities in either. No upgrade needed. |
| Code review | Two passes. (1) `security-review` skill run on 2026-11-03 over the branch diff (`git diff main...HEAD` at ab56b44): **no findings** at or above confidence 8/10, so nothing went to false-positive filtering. Risks it checked and found not exploitable: upload routes moved to `current_user` + `ensure_profile` (same token, allow-list and Google checks; owner comes only from the token); `score_dataset`/`set_scoring` ownership unchanged (new paths only turn a race into a 404); `clean_filename` is a display label, never a path; the raw CSV header check gives a fixed message with no echo; the narrowed 422 path match still covers every real `/datasets` route; the empty CORS default tightens access; purge prints the exception type only; no-signup and transient-error handling log type names only; frontend `dataset_choice` is server-side session state and the API still checks ownership; the churn message order and preview timestamp changes are display-only, with no `unsafe_allow_html`. (2) Hand review over `git diff main...HEAD` plus a pass over `backend/app` and `frontend`: every route's dependency (analytics and churn: `current_user`; events: `ingest_key`; me and datasets: user or profile; health open by design), raw SQL (one `pg_advisory_xact_lock` with a bound parameter, no string-built SQL), `eval`/`pickle`/`subprocess` use (the model artifact is the only unpickle and is hash-checked), and the Task 2-3 changes (no-signup path, transient 503, body-before-profile) | No further findings. |

Outcome: one finding (CORS default), fixed with tests. Remaining open box: CORS in 6.5 until Phase 7b sets the deployed origin. Tests after the pass: backend 418 passed (2 opt-in timing tests skipped), frontend 203 passed with `-W error`; ruff clean in both.
