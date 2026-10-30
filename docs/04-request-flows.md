# 4. Request flows

## 4.1 Sign-in

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant S as Streamlit
    participant A as Supabase Auth
    participant G as Google
    participant API as FastAPI
    U->>S: click Sign in with Google
    S->>S: make flow id and PKCE verifier, keep verifier by flow id
    S->>A: redirect to /authorize (redirect_to app URL with ?flow=id, code_challenge)
    A->>G: authenticate
    G-->>A: identity
    A-->>S: redirect back with code
    S->>A: POST /token?grant_type=pkce (code, verifier)
    A-->>S: session (access_token JWT, refresh_token)
    Note over S: token kept in server-side session state, never in URL or logs
    S->>API: first authenticated call (Bearer token)
    API->>API: upsert user_profiles row keyed by token sub
```

On first authenticated API call the backend upserts a `user_profiles` row keyed by the token's `sub`.

## 4.2 Protected analytics request `[Built]`

Every analytics and churn route requires a verified, allow-listed Google user (`core/authorization.py`): no or bad token is 401, a valid token that is not on the allow-list is 403, and an unreachable key set is 503 (never "allow").

```mermaid
sequenceDiagram
    autonumber
    participant S as Streamlit page
    participant R as FastAPI route
    participant V as Auth dependency
    participant SV as Service
    participant DB as PostgreSQL
    S->>R: GET /analytics/funnel?start=..&end=.. (Bearer jwt)
    R->>V: verify signature, expiry, audience, issuer, role, then allow-list
    V-->>R: user_id = sub (or 401 / 403 / 503)
    R->>R: validate params (tz-aware, start before end, max 366 days) or 422
    R->>SV: funnel_report(window, window_days)
    SV->>DB: fetch needed event rows (SQLAlchemy)
    DB-->>SV: rows
    SV->>SV: apply funnel rules in Pandas, censor at data_through
    SV-->>R: steps, eligible_users, window, data_through
    R-->>S: 200 JSON
    S->>S: render Plotly chart with labelled window and denominators
```

Errors: 401 bad/missing token · 403 not on the allow-list · 422 invalid params · 503 DB unavailable · timeout → UI error state.

## 4.2a Dashboard page load `[Built]` (Phase 6)

Every Streamlit rerun goes through the gate before any page runs. Cached results are shown only after the gate allows the user, so losing access (allow-list change, expired token) shows nothing even though results are cached.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant G as gate.py
    participant API as FastAPI
    participant V as View
    participant D as data.py cache
    U->>G: open or interact with a page
    G->>API: GET /me (Bearer token)
    alt 401
        API-->>G: not authenticated
        G-->>U: clear session, show sign-in
    else 403 or 503
        API-->>G: not allowed or unavailable
        G-->>U: fixed message and Sign out, stop
    else 200
        API-->>G: id and email
        G->>V: render the selected page
        V->>D: fetch with filters
        alt cache hit within 5 minutes
            D-->>V: cached payload
        else miss
            D->>API: GET analytics or churn endpoint (30 s timeout)
            API-->>D: payload
            D-->>V: payload, stored only on success
        end
        V-->>U: charts with window, n= and data-through labels
    end
```

Errors from a view's own fetch map to fixed messages (422 and other 4xx: invalid settings, 503 or timeout: service unavailable with Retry). The shared cache is safe only while analytics data is shared among users; Phase 6b must key it by dataset and user.

## 4.3 Event ingestion (idempotent) `[Built]`

`POST /events` is protected by a service key (`X-API-Key`, compared in constant time; the route is closed with 503 unless `INGEST_API_KEY` is set) and capped at 5 MB and 5,000 events. `scripts/load_events.py` still calls the service directly. The response is `received / inserted / duplicates / conflicts / rejected`.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client or loader
    participant R as POST /events
    participant SV as ingest_events
    participant DB as PostgreSQL
    C->>R: batch of events
    R->>R: check X-API-Key and body size
    R->>SV: raw events
    SV->>SV: validate each row, split valid and rejected
    SV->>DB: upsert customers (earliest created_at kept)
    SV->>DB: INSERT events ON CONFLICT (event_id) DO NOTHING
    alt database error
        DB-->>SV: error
        SV->>DB: ROLLBACK
        SV-->>R: raise, mapped to 5xx
    else success
        SV->>DB: COMMIT
        SV-->>R: received, inserted, duplicates, conflicts, rejected
        R-->>C: 200 result
    end
```

Re-sending the same batch yields `inserted = 0`, `duplicates = n`. A DB failure rolls back and returns 5xx — never a success response.

## 4.4 Churn prediction `[Built]`

Implemented in `services/prediction.py` and `api/routes/churn.py`. Predictions are not persisted yet; unknown ids return `unknown_customer` and customers with no activity in the prior 28 days return `not_eligible` instead of a score.

```mermaid
sequenceDiagram
    autonumber
    participant S as Streamlit
    participant R as FastAPI
    participant P as Prediction service
    participant M as Model (loaded at startup)
    participant DB as PostgreSQL
    S->>R: POST /churn/predict (Bearer)
    R->>R: authenticate and validate input
    R->>P: customer ids
    P->>DB: read recent activity
    P->>P: build features at cutoff (same code and schema as training)
    P->>M: predict_proba
    M-->>P: risk_score
    P-->>R: risk_score, predicted_class, model_version
    R-->>S: JSON plus caveat that the score is an estimate
    Note over R,M: missing or schema-mismatched artifact returns 503, other endpoints stay up
```

If the artifact is missing or its feature schema mismatches: 503 with a generic message; other endpoints stay up.

## 4.4a Ranked at-risk list `[Built]` (Phase 6)

`GET /churn/at-risk?limit&offset` scores every customer with qualifying activity in the 28 days before the serving cutoff with the same feature code as `/churn/predict`, ranks them (score descending, then customer id), and returns a page plus counts, a 10-bin histogram built from the rounded scores, and the model's own test metrics from the artifact metadata. The scored list is cached in-process keyed by `(model_version, cutoff, max(events.id))`: the event id always grows, so a late event with an old timestamp still triggers a rescore.

## 4.5 Offline model training (not a request) `[Built]`

```mermaid
flowchart TD
    cmd(["python -m app.ml.train"]) --> ld["Load data"]
    ld --> ft["Build features at cutoffs"]
    ft --> sp["Time-based split"]
    sp --> fit["Fit Pipeline (preprocess + model) on train"]
    fit --> ev["Evaluate on holdout"]
    ev --> wr["Write artifact + feature schema +<br/>metadata (version, data range, metrics, seed)"]
    wr --> mc["Update docs/model_card.md with real results"]
```

## 4.6 Saved reports (P1)

`POST /me/reports` → `user_id` taken from the token (any body `user_id` is ignored) → insert. `GET`/`DELETE` filter by `user_id`; accessing another user's `report_id` returns 404 (not 403, to avoid leaking existence).
