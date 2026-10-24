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
    S->>A: start Google OAuth (redirect URL configured)
    A->>G: authenticate
    G-->>A: identity
    A-->>S: session (access_token JWT, refresh_token)
    Note over S: token kept in server-side session state, never in URL or logs
    S->>API: first authenticated call (Bearer token)
    API->>API: upsert user_profiles row keyed by token sub
```

On first authenticated API call the backend upserts a `user_profiles` row keyed by the token's `sub`.

## 4.2 Protected analytics request `[In progress]`

The analytics endpoints exist (Phase 3) but are **unauthenticated until Phase 5**; the flow below is the target.

```mermaid
sequenceDiagram
    autonumber
    participant S as Streamlit page
    participant R as FastAPI route
    participant V as Auth dependency (Phase 5)
    participant SV as Service
    participant DB as PostgreSQL
    S->>R: GET /analytics/funnel?start=..&end=.. (Bearer jwt)
    R->>V: verify signature, expiry, audience, issuer
    V-->>R: user_id = sub (or 401)
    R->>R: validate params (tz-aware, start before end, max 366 days) or 422
    R->>SV: funnel_report(window, window_days)
    SV->>DB: fetch needed event rows (SQLAlchemy)
    DB-->>SV: rows
    SV->>SV: apply funnel rules in Pandas, censor at data_through
    SV-->>R: steps, eligible_users, window, data_through
    R-->>S: 200 JSON
    S->>S: render Plotly chart with labelled window and denominators
```

Errors: 401 bad/missing token · 422 invalid params · 503 DB unavailable · timeout → UI error state.

## 4.3 Event ingestion (idempotent) `[In progress]`

The ingestion service and its tests are built; the `POST /events` route and its authentication arrive in Phase 5. `scripts/load_events.py` calls the service directly meanwhile. The response field names below are the target; the service currently returns `received / inserted / duplicates / rejected`.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client or loader
    participant R as POST /events (Phase 5)
    participant SV as ingest_events
    participant DB as PostgreSQL
    C->>R: batch of events
    R->>R: authenticate
    R->>SV: raw events
    SV->>SV: validate each row, split valid and rejected
    SV->>DB: upsert customers (ON CONFLICT DO NOTHING)
    SV->>DB: INSERT events ON CONFLICT (event_id) DO NOTHING
    alt database error
        DB-->>SV: error
        SV->>DB: ROLLBACK
        SV-->>R: raise, mapped to 5xx
    else success
        SV->>DB: COMMIT
        SV-->>R: received, inserted, duplicates, rejected
        R-->>C: 200 result
    end
```

Re-sending the same batch yields `inserted = 0`, `duplicates = n`. A DB failure rolls back and returns 5xx — never a success response.

## 4.4 Churn prediction `[Built]` (authentication pending, Phase 5)

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
