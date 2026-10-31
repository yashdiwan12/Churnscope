# Phase 6b — Bring your own data (uploads): design

Status: **draft for review** · Date: 2026-11-01 · Phase: 6b · Path: architectural (new `datasets` table, migration, dataset-scoped queries and caches, upload endpoints, new UI step)

## 1. Goal and understanding

A signed-in, allow-listed person uploads a CSV of their own product-activity events and sees the same dashboard (Overview, Funnel, Retention, Engagement) plus a churn-risk report for **their file only**. Nobody else can see it. The demo data stays available.

Said by the user: audience is anyone allowed to sign in; uploads come after the dashboard; the churn report scores the uploaded customers with the **existing model** (labelled as an estimate); CSVs use **fixed columns plus an event-name mapping step**; **one dataset per user**, replaceable and deletable; files with no signup event may use **"first event counts as signup"**.

Not in scope: training a model per upload, arbitrary column mapping, several datasets per user, sharing a dataset with another user, saved views, scheduled refresh, non-CSV formats.

## 2. Assumptions

- **A1.** Uploaded data may contain real customer identifiers. It is private to its owner, deletable, never logged.
- **A2.** The churn model was trained on synthetic data and cannot be validated on an upload (there are no labels). Scores are estimates, and the UI says so.
- **A3.** The free Supabase tier is small (500 MB shared), so limits are tight (section 5).
- **A4.** The allow-list keeps the user count small; limits still hold per user and globally.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | `dataset_id` column on `customers` and `events`; new `datasets` table with an owner. The demo data is dataset 1 (no owner, visible to all allowed users) | Mirrors the saved-reports ownership pattern; no runtime DDL |
| D2 | Uniqueness becomes **per dataset** (`event_id`, `external_customer_id`) | Two users can upload the same ids |
| D3 | Ownership check lives in one module (`db/datasets.py`); a foreign or missing dataset id is a **404** | Same rule as reports |
| D4 | Two calls: **check** (stores nothing) then **import** (with mapping). Both carry the file | Server stays stateless and never trusts browser parsing |
| D5 | Replace = **one transaction** that deletes the user's old dataset and inserts the new one, serialised per user by an advisory lock | A failed import keeps the old data; no partial state |
| D6 | "First event counts as signup" **derives a `signup` event** per customer lacking one, at their first mapped event's time (`properties.derived = true`), only when no event is mapped to `signup` | Retention, funnel and churn features all need `signup` (features drop customers without one); no metric code changes |
| D7 | Existing analytics and churn routes gain an optional `dataset_id` query parameter, default demo (1) | Backward compatible |
| D8 | Whole file rejected if more than 5% of rows are invalid; otherwise valid rows import and up to 20 skip reasons are shown | One bad row must not block a large file; a mostly broken file must not import silently |

## 4. Data model (migration `0003_datasets`)

- `datasets`: `id` bigint PK · `owner_id` uuid NULL FK to `user_profiles` (NULL = demo) · `kind` text CHECK in (`demo`, `upload`) · `name` text · `source_filename` text NULL · `signup_rule` text CHECK in (`event`, `derived_from_first_event`) · `mapping` jsonb · `mapped_counts` jsonb (rows per our event name) · `customer_count` int · `event_count` int · `data_through` timestamptz NULL · `created_at`. A **partial unique index on `owner_id` where `kind = 'upload'`** allows at most one upload per user. Row 1 is the demo dataset, created by the migration.
- `customers.dataset_id` and `events.dataset_id`: NOT NULL FK to `datasets` ON DELETE CASCADE; existing rows backfilled to 1.
- Constraints: replace the global uniques with `unique(dataset_id, external_customer_id)` and `unique(dataset_id, event_id)`; a composite FK `events(dataset_id, customer_id)` to `customers(dataset_id, id)` so an event can never point at another dataset's customer. Indexes lead with `dataset_id`: `(dataset_id, customer_id, event_timestamp)` and `(dataset_id, event_name, event_timestamp)`.
- RLS on and `anon`/`authenticated` grants revoked for `datasets`, as in `0002`. The RLS test is extended.
- Downgrade is allowed only when no upload exists (otherwise it raises).
- `POST /events` and the loader script write to dataset 1 explicitly.

## 5. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/datasets` | Demo plus the caller's own: id, kind, name, counts, data_through, `capabilities`, `signup_rule` |
| POST | `/datasets/check` | JSON `{csv_text, filename}`; stores nothing; returns rows, customers, time range, event names with counts, suggested mapping, skipped rows (count, first 20 reasons), the timestamp assumption |
| POST | `/datasets` | JSON `{csv_text, filename, mapping, derive_signup}`; imports and replaces; returns the dataset |
| DELETE | `/datasets/{id}` | Own upload only; demo or someone else's is a 404 |
| existing | analytics, churn | `?dataset_id=`; a dependency checks visibility (demo or owned), else 404 |

Limits (constants in one module): body at most 6 MB (411 without Content-Length, 413 over); `csv_text` at most 5 MB; at most 50,000 event rows; at most 10,000 customers; at most 50 distinct event names; a global cap on uploaded events (default 300,000), over which import returns 409 "storage full". Auth is `current_user`, as on other routes.

**CSV rules.** UTF-8 (BOM allowed), comma-separated, header row, columns matched case-insensitively and trimmed: required `customer_id`, `event_name`, `event_timestamp`; optional `event_id`; other columns are ignored and never stored. IDs and names are trimmed and at most 100 chars. Timestamps are ISO-8601; one with no zone is treated as UTC and the check says so; a timestamp is rejected if in the future (5 min skew) or before 2000-01-01, the same bounds as `POST /events`. Without `event_id`, one is derived: a hash of customer, mapped name, timestamp and occurrence number, so repeated identical rows do not double count. Duplicate `event_id`s keep the first and are counted as duplicates, not as invalid rows.

**Mapping.** `{their_name: our_name or null}` with `our_name` in `EVENT_NAMES`; many-to-one is allowed; at least one target must be in `QUALIFYING_EVENTS`, else the import is refused. The suggestion matches by normalised name (lower case, spaces and hyphens to underscores). `derive_signup` is accepted only when nothing maps to `signup`.

**Capabilities** (computed from `mapped_counts` and `signup_rule`): Overview and Engagement always; Retention needs `signup` (mapped or derived); Funnel needs `signup`, `onboarding_complete` and `report_created`, else it names the missing steps; Churn needs a signup too and shows the existing empty state if no customer is eligible.

## 6. Flow

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant UI as Streamlit
    participant API as FastAPI
    participant DB as Postgres
    U->>UI: choose file, accept privacy notice
    UI->>API: POST /datasets/check (csv_text)
    API-->>UI: names with counts, suggested mapping, skipped rows
    U->>UI: adjust mapping, pick derive signup, see which pages will work
    UI->>API: POST /datasets (csv_text, mapping)
    API->>DB: one transaction, lock user, delete old dataset, insert new
    DB-->>API: committed, or rolled back with the old data intact
    API-->>UI: new dataset
    UI-->>U: switch to My data
```

UI: a sidebar **Data** selector (Demo data, My data), default Demo. An **Upload data** page (template download, notice, check, mapping, replace confirmation, import, delete). A banner that follows the selection: demo keeps the current text; My data says "Your uploaded data: <filename>, private to you". Pages whose capability is missing show a fixed message naming what is missing. A 404 for the selected dataset falls back to Demo with a notice. On the Churn Risk page for My data, the evaluation block is labelled "measured on the synthetic test set", and a notice states the model was trained on synthetic data and not measured on this file. Retention and Funnel carry a note when the signup is derived.

## 7. Caches

- Frontend `data.py`: every cached call keys on `dataset_id` and the signed-in user id (new parameters on each function); the `_api` argument stays excluded.
- Backend churn-list cache: the key becomes `(dataset_id, model_version, cutoff, max(events.id) for that dataset)`, bounded to 4 entries (oldest evicted) so memory does not grow per dataset.
- `latest_event_id`, `data_through`, `resolve_customers`, `customer_external_ids` and every analytics repository function take `dataset_id`.

## 8. Security and privacy

| Risk | Control | Test |
|---|---|---|
| Reading or deleting another user's dataset | `db/datasets.py` owns the check; every route uses it; 404 | two-user tests on every route |
| Event or customer crossing datasets | composite FK and dataset-scoped uniques | a direct insert is refused |
| `POST /events` writing into a user dataset | writes target dataset 1 only | test |
| Resource exhaustion | size and row caps, global cap, per-user lock, 5% rule | boundary tests |
| Partial import or lost data | single transaction | a forced failure keeps the old dataset |
| Leaking rows in logs or errors | skip reasons carry row numbers and codes, never values; fixed error messages | log-capture test |
| Stale cache across datasets or users | keys include dataset and user | frontend and backend tests |
| Personal data | notice on the upload step; delete really deletes (cascade); no extra columns stored | delete test counts rows |

## 9. Failure behaviour

Invalid CSV, missing columns and over-limit files return fixed 4xx messages with a reason code. Database unavailable: the existing 503. The import can be slow on a cold database: the frontend timeout is 60 s with a Retry that re-sends the file from session memory.

## 10. Testing

- Migration up and down on seeded data.
- Every route with two users and a foreign id; the demo dataset cannot be deleted.
- Atomic replace under a forced failure; concurrent imports by one user (one wins, none partial).
- Caps: rows, bytes, customers, names, global.
- The 5% rule at and just above the limit.
- Timestamp bounds and zoneless handling.
- Mapping validation, including a missing qualifying event.
- Derived signup (retention, funnel and features all see it).
- `event_id` derivation and duplicates.
- Cache keys on both sides.
- Capabilities for several mapping shapes.
- Hand-checked metrics on a small uploaded file equal the same events loaded as demo.
- Frontend: selector, banner, notices, 404 fallback.

## 11. Plan outline (for the plan document)

1. Migration `0003`, models, `db/datasets.py`, dataset-scoped repositories, `POST /events` pinned to dataset 1.
2. `dataset_id` on analytics and churn routes, visibility dependency, churn cache key and bound.
3. CSV parsing and the check endpoint.
4. Import (mapping, derived signup, transaction, caps), list and delete endpoints.
5. Frontend: data selector, dataset-keyed caches, banner and notices.
6. Frontend: Upload data page.
7. Docs, progress, whole-branch review, real run-through with a test file.

## 12. Open points

- The global cap default (300,000 events) is a guess for the free tier. Revisit it against the real database size before deploy (Phase 7).
- Idle expiry of uploads is not included; users delete manually.
