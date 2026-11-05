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

Errors from a view's own fetch map to fixed messages (422 and other 4xx: invalid settings, 503 or timeout: service unavailable with Retry). Since Phase 6b the cache is keyed by dataset id and signed-in user id, and `dataset.py` re-checks `GET /datasets` on every rerun, so a deleted or foreign dataset is never read from it.

## 4.3 Event ingestion (idempotent) `[Built]`

`POST /events` always writes to dataset 1 (the demo) and is protected by a service key (`X-API-Key`, compared in constant time; the route is closed with 503 unless `INGEST_API_KEY` is set) and capped at 5 MB and 5,000 events. `scripts/load_events.py` still calls the service directly. The response is `received / inserted / duplicates / conflicts / rejected`.

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
    SV->>DB: INSERT events ON CONFLICT (dataset_id, event_id) DO NOTHING
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

`GET /churn/at-risk?limit&offset` scores every customer with qualifying activity in the 28 days before the serving cutoff with the same feature code as `/churn/predict`, ranks them (score descending, then customer id), and returns a page plus counts, a 10-bin histogram built from the rounded scores, and the model's own test metrics from the artifact metadata. The scored list is cached in-process keyed by `(dataset_id, model_version, cutoff, max(events.id))`: the event id always grows, so a late event with an old timestamp still triggers a rescore. With `?dataset_id=` for an upload the list is ranked by that upload's own stored scoring (4.5a), keyed by `(dataset_id, scoring fitted-at, cutoff)`; the cache holds at most 4 entries and a delete, import or re-score evicts that dataset's entries.

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

## 4.5a Upload flow `[Built]` (Phase 6b)

Four steps: check (stores nothing), map, import (one transaction), then scoring in a separate transaction after the commit. Both upload calls send the file as multipart, with the size limits enforced while the body is read (411 without Content-Length, 413 over 5.5 MB for the body or 5 MB for the file), before any parsing.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant UI as Streamlit Upload page
    participant API as FastAPI
    participant DB as PostgreSQL
    U->>UI: choose CSV, accept the privacy notice
    UI->>API: POST /datasets/check (file, columns when the headers differ)
    API->>API: read within limits, parse, count rows, names and first-week share
    API-->>UI: event names with counts, suggested mapping, skipped rows, approximate-signup warning
    U->>UI: match columns if asked, adjust mapping, choose derive signup, tick the acknowledgement if warned
    UI->>API: POST /datasets (file, columns, mapping, flags)
    API->>API: validate mapping, derive signup and event ids, apply the 5 percent invalid rule
    API->>DB: BEGIN, take the global advisory lock
    API->>DB: global cap check over other users' uploaded events
    alt cap exceeded
        API->>DB: ROLLBACK
        API-->>UI: 409 storage_full
    else room left
        API->>DB: delete caller's old upload (cascade), insert dataset, customers, events in batches
        API->>DB: COMMIT
        API->>API: evict old and new dataset cache entries
        Note over API,DB: import has committed, so the 201 stands whatever happens next
        API->>DB: load the upload's events
        API->>API: fit weekly backtest, pick logistic or inactivity rule
        API->>DB: store scoring JSON on the dataset row (own transaction)
        API-->>UI: 201 dataset, counts, derived signups, skipped rows
    end
    UI-->>U: switch to My data
```

Failure behaviour: any error before the commit rolls back and the old upload stays. A scoring failure stores `scoring.method = "failed"` and the Churn Risk page offers Retry (`POST /datasets/{id}/score`). Scoring (`services/upload_scoring.py`): weekly cutoffs (latest 26), 2 test cutoffs with a purge gap so no training label overlaps the test period, logistic regression against the days-since-last-activity rule (at risk at 7 days or more); the model is used only if its PR-AUC beats the rule's by at least 0.02. Floors: at least 200 test rows and 20 churners and 20 non-churners in the test and 20 churners in training, else `rule_unchecked` (at least 28 days of history, shown as not checked on the user's data), else `unavailable`. Roughly 9 weeks of history are needed for a checked result. The fitted model is stored as JSON numbers and applied as a dot product.

## 4.6 Saved reports (P1)

`POST /me/reports` → `user_id` taken from the token (any body `user_id` is ignored) → insert. `GET`/`DELETE` filter by `user_id`; accessing another user's `report_id` returns 404 (not 403, to avoid leaking existence).
