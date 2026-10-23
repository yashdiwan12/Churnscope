# 4. Request flows

## 4.1 Sign-in

```
User -> Streamlit: click "Sign in with Google"
Streamlit -> Supabase Auth: start Google OAuth (redirect URL configured)
Supabase Auth -> Google: authenticate
Google -> Supabase Auth: identity
Supabase Auth -> Streamlit: session (access_token JWT, refresh_token)
Streamlit: store token in session state (server-side), never in URL/logs
```

On first authenticated API call the backend upserts a `user_profiles` row keyed by the token's `sub`.

## 4.2 Protected analytics request

```
Streamlit page -> FastAPI: GET /analytics/funnel?from=..&to=..   (Authorization: Bearer <jwt>)
FastAPI dependency: verify signature, expiry, audience, issuer -> user_id = sub
Route: validate query params (Pydantic; date range, limits)
Service: build funnel (SQL aggregation + Pandas) using documented rules
Repository (SQLAlchemy) -> PostgreSQL
FastAPI -> Streamlit: JSON { steps[], denominators, window, generated_at }
Streamlit: render Plotly chart with labelled window + denominators
```

Errors: 401 bad/missing token · 422 invalid params · 503 DB unavailable · timeout → UI error state.

## 4.3 Event ingestion (idempotent)

```
Client/loader -> FastAPI: POST /events  [ {event_id, customer_id, event_name, event_timestamp, properties}, ... ]
FastAPI: authenticate, validate each event (schema, name allow-list, UTC timestamp, payload size)
Service: split into valid / rejected(reason)
Repository: BEGIN; INSERT ... ON CONFLICT (event_id) DO NOTHING; COMMIT
FastAPI -> client: 200 { accepted, duplicates, rejected:[{index, reason}] }
```

Re-sending the same batch yields `accepted = 0`, `duplicates = n`. A DB failure rolls back and returns 5xx — never a success response.

## 4.4 Churn prediction

```
Streamlit -> FastAPI: POST /churn/predict { customer_ids | customer_id }   (Bearer)
FastAPI: authenticate, validate input
Prediction service: build features at the cutoff (same code/schema as training)
Model: loaded once at startup from the versioned artifact
Service: risk_score, predicted_class, model_version  -> optionally persist to predictions
FastAPI -> Streamlit: JSON + caveat that the score is an estimate
```

If the artifact is missing or its feature schema mismatches: 503 with a generic message; other endpoints stay up.

## 4.5 Offline model training (not a request)

```
python -m app.ml.train  ->  load data -> build features at cutoffs -> time-based split
 -> fit Pipeline(preprocess + model) on train -> evaluate on holdout
 -> write artifact + feature schema + metadata (version, data range, metrics, seed)
 -> update docs/model_card.md with real results
```

## 4.6 Saved reports (P1)

`POST /me/reports` → `user_id` taken from the token (any body `user_id` is ignored) → insert. `GET`/`DELETE` filter by `user_id`; accessing another user's `report_id` returns 404 (not 403, to avoid leaking existence).
