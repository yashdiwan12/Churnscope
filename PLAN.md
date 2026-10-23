# Churnscope --- Project Implementation Plan

> **Purpose:** Build a portfolio-ready product analytics platform that
> turns user-activity events into engagement, funnel, retention, and
> churn-risk insights.
>
> **Principle:** Deliver a small, correct end-to-end MVP before adding
> optional sophistication. Never claim scale, accuracy, or performance
> that has not been measured.

## 1. Product Goal

Churnscope helps a SaaS team answer: 1. Are users actively using the
product? 2. Where do users drop out of important workflows? 3. Which
cohorts return over time? 4. Which customers show behaviours associated
with future churn?

The application combines event ingestion, SQL-backed analytics,
behavioural features, machine learning, authenticated access, and
interactive visualization.

### MVP definition of done

-   A developer can set up the project using documented instructions.
-   Users can sign in through Google using Supabase Auth.
-   A documented dataset can be loaded and validated events can be
    ingested.
-   Engagement, funnel, and retention metrics return correct results on
    test examples.
-   A churn model can be trained and evaluated reproducibly.
-   Streamlit displays analytics and model outputs.
-   Private saved data is accessible only to its owner.
-   Tests cover ingestion, analytics, authorization, and ML behaviour.

No model-performance target is assumed in advance; report actual
evaluation results.

## 2. Scope

### P0 --- MVP

-   Python application with clear module boundaries.
-   Dataset selection, source/licence notes, and data validation.
-   Supabase-hosted PostgreSQL and SQLAlchemy.
-   Supabase Google OAuth.
-   Token verification and server-side authorization.
-   Event ingestion and duplicate protection.
-   Engagement overview, funnel, and cohort-retention analytics.
-   Baseline churn classifier with leakage-aware evaluation.
-   Streamlit + Plotly dashboard.
-   Tests, README, setup instructions, and architecture diagram.

### P1 --- after the MVP

-   Saved reports and user watchlists.
-   Customer segmentation.
-   Model explanations and threshold comparison.
-   More detailed cohort and feature-adoption views.
-   Scheduled metric refresh or retraining.
-   Docker and deployment automation.
-   More complete logging and monitoring.

### Out of scope for version 1

-   Kafka or distributed streaming.
-   Microservices.
-   Large-scale analytics infrastructure.
-   LLM chatbot functionality.
-   Billing/subscription management.
-   Claims of real-time analytics at production scale.
-   Complex orchestration before it is needed.

## 3. Technology Stack

  -----------------------------------------------------------------------
  Component               Technology              Responsibility
  ----------------------- ----------------------- -----------------------
  Language                Python                  Application, analytics,
                                                  ML

  Data processing         Pandas, NumPy           Validation,
                                                  aggregation, features

  ML                      scikit-learn            Baselines,
                                                  classification,
                                                  evaluation

  Backend                 FastAPI                 API routes and request
                                                  coordination

  API contract            REST, Pydantic          Input validation and
                                                  responses

  Authentication          Supabase Auth, Google   Sign-in and identity
                          OAuth                   

  Database                Supabase-hosted         Customers, events,
                          PostgreSQL              metrics, predictions

  DB toolkit              SQLAlchemy              ORM, queries, sessions,
                                                  transactions

  Dashboard               Streamlit               User interface

  Visualization           Plotly                  Interactive charts

  Testing                 pytest, FastAPI         Unit and integration
                          TestClient              tests

  Version control         Git, GitHub             Source history and
                                                  documentation
  -----------------------------------------------------------------------

Optional libraries: a PostgreSQL driver such as `psycopg`, Alembic for
migrations, `httpx` for HTTP calls, and `joblib` for model
serialization. Add them only when needed. Do not use `yfinance` or
`pandas-ta`; they are finance-specific.

## 4. Architecture

``` text
                         +----------------------+
                         |        User          |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | Streamlit + Plotly   |
                         +-----+-----------+----+
                               |           |
                     Sign-in   |           | Bearer access token
                               v           v
                     +----------------+  +-----------------------+
                     | Supabase Auth  |  | FastAPI REST API      |
                     | Google OAuth   |  | Validate + authorize  |
                     +----------------+  +-----------+-----------+
                                                    |
                                                    v
                                         +-----------------------+
                                         | Application Services  |
                                         +----+--------------+---+
                                              |              |
                                              v              v
                                    +----------------+  +----------------+
                                    | Analytics      |  | ML Inference   |
                                    | Pandas + SQL   |  | scikit-learn   |
                                    +-------+--------+  +-------+--------+
                                            |                   |
                                            +---------+---------+
                                                      |
                                                      v
                                           +---------------------+
                                           | SQLAlchemy          |
                                           +----------+----------+
                                                      |
                                                      v
                                           +---------------------+
                                           | Supabase PostgreSQL |
                                           +---------------------+

Dataset / event source ---> validated ingestion API ---> PostgreSQL
Offline training workflow ---> versioned model artifact ---> ML inference
```

For the MVP, API routes, analytics, and inference can run in one FastAPI
application, separated into code modules rather than deployed as
microservices.

### Request flow

1.  User signs in through Google using Supabase Auth.
2.  Streamlit sends the access token with protected API requests.
3.  FastAPI verifies the token and derives the authenticated identity.
4.  The API calls an analytics, ingestion, or prediction service.
5.  SQLAlchemy reads/writes PostgreSQL.
6.  Analytics calculates metrics, or inference loads a previously
    trained model.
7.  FastAPI returns a documented response.
8.  Streamlit renders the result using Plotly.

**Model rule:** training is separate from prediction requests. The API
loads a validated model artifact and uses the same feature schema and
preprocessing as training.

## 5. Data Plan

### 5.1 Select datasets before modelling

Choose a documented customer-churn dataset and, if needed, a separate
timestamped event dataset or clearly labelled synthetic events.

Before building: - Record source, licence, schema, and known
limitations. - Inspect types, missing values, duplicates, timestamps,
and identifiers. - Determine how churn is labelled. - Document
assumptions in `docs/data_dictionary.md`.

A static churn dataset may support classification but not real event
funnels or time-based validation. Do not pretend it has timestamps it
does not contain. Keep synthetic event analytics and a public churn
dataset distinct and clearly labelled if that is the practical choice.

### 5.2 Ingestion stages

1.  Read source data.
2.  Validate required columns and types.
3.  Normalize timestamps and identifiers.
4.  Check missing values and invalid records.
5.  Validate event names and event properties.
6.  Detect duplicates using a stable event ID or documented key.
7.  Insert using database constraints and safe conflict handling.
8.  Record rejected-row reasons without logging sensitive data.

### 5.3 Example event contract

``` json
{
  "event_id": "source-generated-unique-id",
  "customer_id": "customer-123",
  "event_name": "feature_used",
  "event_timestamp": "2026-10-20T12:30:00Z",
  "properties": {
    "feature": "report_builder"
  }
}
```

This is illustrative. Validate identifiers, timestamps, payload size,
event names, and property types.

### 5.4 Idempotency

Retries must not create duplicate events. Use a stable unique event
identifier and a PostgreSQL uniqueness constraint. Application-only
"check then insert" logic can race under concurrent requests.

## 6. Database Plan

Create only the tables needed for the selected dataset and MVP.

### `customers`

-   `id`: primary key.
-   `external_customer_id`: stable source identifier.
-   `created_at`: signup/account creation time.
-   `plan`: optional category.
-   `status`: optional status.
-   `churned_at`: optional observed churn timestamp.

### `events`

-   `id`: internal primary key.
-   `event_id`: unique source event identifier.
-   `customer_id`: foreign key.
-   `event_name`: validated name.
-   `event_timestamp`: event occurrence time.
-   `properties`: optional JSONB attributes.
-   `ingested_at`: ingestion timestamp.

Potential indexes: unique `event_id`; `(customer_id, event_timestamp)`
for customer timelines; `(event_name, event_timestamp)` for event
analytics. Add indexes based on actual query patterns and query plans.

### `user_profiles`

-   `id`: Supabase Auth user UUID.
-   `display_name`: optional.
-   `created_at`: profile creation time.

This identity is the person using Churnscope, not necessarily a
customer in the product being analysed.

### `saved_reports` (P1)

-   `id`: primary key.
-   `user_id`: owner.
-   `report_type`: report category.
-   `filters`: optional JSONB configuration.
-   `created_at`: creation time.

### `predictions`

-   `id`: primary key.
-   `customer_id`: customer being scored.
-   `prediction_time`: when prediction was made.
-   `prediction_horizon`: future period covered.
-   `risk_score`: model output, if supported.
-   `predicted_class`: model output.
-   `model_version`: model identifier.

Store outcome/evaluation information separately or in clearly defined
outcome fields. Never evaluate a prediction using information already
known at prediction time.

### Database rules

-   Use foreign keys, uniqueness, and check constraints where
    appropriate.
-   Use consistent timestamp/time-zone handling.
-   Keep private Churnscope user data separate from analysed customer
    data.
-   Use JSONB for flexible event properties, not as a substitute for
    every relational column.
-   Add migrations when the schema starts evolving.
-   Use transactions for multi-step writes.

### Supabase security decision

**Recommended MVP:** Streamlit calls FastAPI; FastAPI verifies the
user's token, enforces ownership, and accesses PostgreSQL using
SQLAlchemy.

If the backend uses a privileged database credential, do not assume RLS
automatically knows the end user's identity. Enforce ownership in the
backend or explicitly establish a secure RLS-aware database context. If
clients access Supabase tables directly, configure and test RLS for
every exposed table.

Never expose a database password or Supabase service-role key in
client-side code or GitHub.

## 7. API Plan

  -------------------------------------------------------------------------------------
  Method                  Endpoint                              Purpose
  ----------------------- ------------------------------------- -----------------------
  `GET`                   `/health`                             Service health

  `POST`                  `/events`                             Validate and store
                                                                events

  `GET`                   `/analytics/overview`                 Engagement summary

  `GET`                   `/analytics/funnel`                   Funnel conversion

  `GET`                   `/analytics/retention`                Cohort retention

  `GET`                   `/analytics/engagement`               Activity trends

  `GET`                   `/customers/{customer_id}/insights`   Authorized customer
                                                                insights

  `POST`                  `/churn/predict`                      Generate a churn-risk
                                                                estimate

  `GET`                   `/me/reports`                         List own saved reports

  `POST`                  `/me/reports`                         Save a report

  `DELETE`                `/me/reports/{report_id}`             Delete own report
  -------------------------------------------------------------------------------------

Exact routes may change as the project evolves.

API standards: - Use Pydantic request/response schemas. - Return
appropriate HTTP status codes and consistent errors. - Validate date
ranges and pagination. - Do not expose stack traces or secrets. - Use
timeouts for external calls. - Protect private endpoints with verified
authentication. - Derive identity from the verified token, not a
client-supplied `user_id`. - Generate and inspect OpenAPI documentation.

## 8. Analytics Plan

Write metric definitions before building the dashboard.

### Active users

Count distinct users who performed at least one qualifying event in the
selected time window. Explicitly list which events qualify.

### Funnel conversion

Example: `signup -> onboarding_complete -> first_key_action`.

Define event ordering, time window, user-versus-event counting,
repeat-event handling, and eligibility. A basic step conversion rate is:

`users reaching step N / eligible users reaching step N-1`

Document the denominator and rules.

### Cohort retention

Group customers by a starting event such as signup week. For each later
period, count cohort members who performed qualifying activity divided
by the eligible original cohort size. Distinguish calendar periods from
elapsed periods and mark incomplete recent cohorts.

### Engagement

Potential metrics include active days per user, qualifying events per
active user, feature adoption, returning-user rate, and time between
meaningful activities. Raw event volume alone is not proof of product
value.

## 9. Churn Model Plan

### 9.1 Define the label

Choose one definition supported by the dataset: - Subscription
cancellation, if trustworthy cancellation labels exist. - No qualifying
activity for a specified period. - Failure to return within a defined
future window.

Do not mix incompatible definitions.

### 9.2 Define cutoff and horizon

Illustrative example: - Features use activity from the previous 28
days. - The target describes a churn event or inactivity condition in
the following 14 days.

Choose windows that fit the dataset and document them.

### 9.3 Candidate features

-   Days since last meaningful activity.
-   Active days in the feature window.
-   Event counts by category.
-   Change in activity relative to a previous window.
-   Number of key features used.
-   Onboarding completion.
-   Account age at cutoff.
-   Plan/category, if available and valid.

Every feature must be computable from information available at the
prediction cutoff.

### 9.4 Training and evaluation

1.  Build a simple baseline.
2.  Split data using a method appropriate to the dataset.
3.  Fit preprocessing only on training data.
4.  Train Logistic Regression as an interpretable baseline.
5.  Compare with Random Forest if useful.
6.  Evaluate with a confusion matrix, precision, recall, F1, and ROC-AUC
    where appropriate.
7.  Inspect class imbalance and compare with a naive baseline.
8.  Review false positives and false negatives.
9.  Save the fitted pipeline, feature schema, training metadata, and
    model version.
10. Load the validated artifact in FastAPI for inference.

If the dataset is a static snapshot without reliable temporal data, do
not claim true temporal validation. Document the limitation and choose a
defensible method or a more suitable dataset.

### 9.5 Model lifecycle

-   Training is a separate script/task.
-   Model artifacts are versioned and reproducible.
-   Inference uses the same feature schema and preprocessing as
    training.
-   Report actual evaluation results.
-   Do not retrain on every prediction request.
-   Return risk estimates as uncertain predictions, not guarantees.

## 10. Dashboard Plan

### Overview

Active users, new/returning users, qualifying event volume, conversion
summary, engagement trend.

### Funnels

Defined event sequence, users at each step, conversion rates, drop-offs,
date filters.

### Retention

Cohort definition, cohort size, retention by period, heatmap/line chart,
incomplete-cohort warning.

### Engagement

Activity over time, feature adoption, active days, event-category
breakdown.

### Churn Risk

Risk estimates for eligible customers, model version, evaluation
summary, supported feature explanation, uncertainty caveat.

### My Workspace (P1)

Saved reports and personal views, limited to the authenticated user's
own records.

UI requirements: - Label date ranges and denominators. - Display data
freshness and empty states. - Handle API timeouts and errors. - Avoid
charts that imply unsupported precision. - Never display fabricated
analytics or model scores.

## 11. Repository Structure

``` text
churnscope/
├── README.md
├── PLAN.md
├── requirements.txt
├── .env.example
├── .gitignore
├── app/
│   ├── main.py
│   ├── api/routes/
│   │   ├── health.py
│   │   ├── events.py
│   │   ├── analytics.py
│   │   ├── churn.py
│   │   └── reports.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── logging.py
│   ├── db/
│   │   ├── session.py
│   │   ├── models.py
│   │   └── repositories.py
│   ├── schemas/
│   ├── services/
│   │   ├── ingestion.py
│   │   ├── analytics.py
│   │   ├── features.py
│   │   └── prediction.py
│   └── ml/
│       ├── train.py
│       ├── evaluate.py
│       └── artifacts/
├── dashboard/
│   ├── app.py
│   └── pages/
├── notebooks/
│   └── exploratory_analysis.ipynb
├── data/README.md
├── migrations/
├── tests/
│   ├── test_events.py
│   ├── test_analytics.py
│   ├── test_auth.py
│   └── test_predictions.py
└── docs/
    ├── architecture.md
    ├── data_dictionary.md
    ├── database.md
    └── model_card.md
```

Start with fewer modules if needed. Refactor when separation improves
clarity and testability.

## 12. Implementation Milestones

### Milestone 0 --- Setup

-   [ ] Create Git repository.
-   [ ] Create virtual environment and dependency file.
-   [ ] Create `.gitignore` and `.env.example`.
-   [ ] Write initial README and scope.
-   [ ] Select and document datasets.

**Exit:** clean local setup, documented data source, no secrets in Git.

### Milestone 1 --- Data and metric definitions

-   [ ] Inspect schema, types, missing values, duplicates, and
    timestamps.
-   [ ] Write data dictionary.
-   [ ] Define qualifying activity events.
-   [ ] Define funnel steps and conversion rules.
-   [ ] Define cohort and retention periods.
-   [ ] Validate metrics on small hand-checkable examples.

**Exit:** assumptions and analytics definitions are documented and
reproducible.

### Milestone 2 --- Database and ingestion

-   [ ] Create Supabase project and PostgreSQL schema.
-   [ ] Configure SQLAlchemy and database driver.
-   [ ] Create tables, constraints, and initial indexes.
-   [ ] Build import/ingestion service.
-   [ ] Add event validation and deduplication.
-   [ ] Add safe conflict handling.
-   [ ] Test reads and writes.

**Exit:** repeated ingestion does not create duplicate event records.

### Milestone 3 --- Analytics

-   [ ] Implement active-user aggregation.
-   [ ] Implement funnel calculation.
-   [ ] Implement cohort retention.
-   [ ] Implement engagement trends.
-   [ ] Validate outputs against hand-checked examples.
-   [ ] Expose analytics through FastAPI.

**Exit:** analytics endpoints return correct, documented results.

### Milestone 4 --- Churn model

-   [ ] Document label and prediction horizon.
-   [ ] Build leakage-aware features.
-   [ ] Create a baseline model.
-   [ ] Fit preprocessing inside a pipeline.
-   [ ] Evaluate with appropriate metrics and baseline comparison.
-   [ ] Inspect errors and class imbalance.
-   [ ] Save model/schema/version metadata.
-   [ ] Implement inference service and tests.

**Exit:** reproducible training/evaluation and validated API inference.

### Milestone 5 --- Authentication and authorization

-   [ ] Configure Google OAuth in Supabase and Google Cloud.
-   [ ] Configure local/deployed redirect URLs.
-   [ ] Implement Streamlit sign-in/sign-out.
-   [ ] Verify tokens in FastAPI.
-   [ ] Implement owner-only access for private data.
-   [ ] Decide and document RLS/backend authorization boundaries.
-   [ ] Test missing, expired, invalid, and wrong-user access.

**Exit:** protected routes work and cross-user access tests fail safely.

### Milestone 6 --- Dashboard

-   [ ] Create overview page.
-   [ ] Create funnel page.
-   [ ] Create retention page.
-   [ ] Create engagement page.
-   [ ] Create churn-risk page.
-   [ ] Connect pages to FastAPI.
-   [ ] Add loading, empty, and error states.
-   [ ] Add saved views only if time allows.

**Exit:** user can complete the core analytics flow in the UI.

### Milestone 7 --- Quality and documentation

-   [ ] Add unit/integration tests.
-   [ ] Test duplicate ingestion and malformed payloads.
-   [ ] Test analytics against known examples.
-   [ ] Test authentication and ownership boundaries.
-   [ ] Test inference validation and model loading.
-   [ ] Document architecture and schema.
-   [ ] Document actual model evaluation.
-   [ ] Add screenshots and setup instructions.
-   [ ] Review secrets, logging, and data exposure.
-   [ ] Deploy only after local workflow is reliable.

**Exit:** a new developer can follow the README and run the documented
workflow.

## 13. Testing Plan

### Ingestion

-   Valid event accepted.
-   Invalid event rejected.
-   Duplicate event handled safely.
-   Invalid timestamp or oversized payload rejected.

### Analytics

-   Active-user counts match hand-calculated examples.
-   Funnel ordering and denominator are correct.
-   Retention handles incomplete cohorts.
-   Empty ranges return meaningful results.
-   Time-zone boundaries are consistent.

### Authentication and authorization

-   Missing/invalid token is rejected for protected endpoints.
-   User A cannot access User B's private records.
-   Client-supplied identity cannot override verified identity.
-   Secrets never appear in responses or logs.

### ML

-   Training and inference use the same feature schema.
-   Preprocessing is fitted on training data only.
-   Future information does not enter features.
-   Model artifact/version is recorded.
-   Malformed inputs are handled.
-   Evaluation can be reproduced.

### Integration

-   Dashboard handles API errors.
-   Database failures do not appear as successful writes.
-   Event-to-analytics flow works on a small test dataset.

## 14. Security and Reliability Requirements

-   Store secrets in environment variables or a secrets manager.
-   Commit `.env.example`, never `.env`.
-   Never commit OAuth secrets, database passwords, or Supabase
    service-role keys.
-   Verify tokens server-side.
-   Enforce row ownership for private records.
-   Configure and test RLS for directly exposed Supabase tables.
-   Validate event schema, names, identifiers, and timestamps.
-   Use database constraints for idempotency.
-   Avoid logging tokens or unnecessary personal data.
-   Use timeouts and sensible error responses.
-   Restrict CORS to required origins; CORS is not authentication.
-   Avoid exposing stack traces.
-   Document data provenance, licensing, and limitations.

## 15. Deployment Plan

-   Supabase: managed PostgreSQL and Auth.
-   FastAPI: one Python web service.
-   Streamlit: dashboard service.
-   GitHub: source code and documentation.
-   Environment configuration: service URLs and secrets per environment.

Before deployment: - Configure OAuth redirect URLs. - Ensure Streamlit
uses the deployed API URL. - Configure CORS for the dashboard origin. -
Use secure database connection settings. - Verify health checks and
error handling. - Confirm secrets are not bundled into client-visible
code. - Test the full deployed sign-in-to-dashboard flow.

Docker is an optional later improvement, not an MVP prerequisite.

## 16. Interview Readiness

Be ready to explain: - Why Pandas vectorization is useful and how joins
can duplicate rows. - How active users, funnel conversion, and retention
are defined. - What the churn label and prediction horizon mean. - How
leakage was prevented and metrics were chosen. - Why PostgreSQL,
constraints, and indexes were selected. - How duplicate ingestion is
prevented. - How Supabase tokens are verified. - Authentication versus
authorization. - How private record ownership is enforced. - Why
Streamlit and FastAPI are separate. - Why training is separate from
inference. - What happens if the API, database, or model is
unavailable. - Which limitations remain and how the project could scale.

## 17. Portfolio Deliverables

The finished repository should include: - Problem statement and
features. - Architecture diagram. - Technology stack and component
responsibilities. - Dataset source, licence, schema, and limitations. -
Database schema/ER diagram. - Local setup and environment
configuration. - Supabase/Google OAuth setup notes. - API examples. -
Dashboard screenshots. - Actual model results and methodology. - Tests
and test instructions. - Security notes and known limitations. - Future
work.

### Resume wording --- only after implementation

**Churnscope --- Product Analytics & Churn Intelligence Platform** -
Built a Python analytics platform to process product activity events and
visualize engagement, funnel conversion, and cohort retention. -
Developed FastAPI endpoints and a PostgreSQL data layer using
SQLAlchemy, with Supabase Google authentication. - Engineered
behavioural features and evaluated a scikit-learn churn classifier using
a documented validation methodology. - Created a Streamlit and Plotly
dashboard for product metrics and churn-risk analysis.

Add event counts, latency, accuracy, or performance improvements only
after collecting and verifying them.

## 18. Final Build Order

1.  Select and document datasets.
2.  Define event schema and analytics metrics.
3.  Build/test Pandas analytics on local data.
4.  Design PostgreSQL tables and load data.
5.  Expose analytics through FastAPI.
6.  Build/evaluate the churn model.
7.  Add inference to FastAPI.
8.  Add Supabase Google OAuth and authorization.
9.  Build Streamlit/Plotly pages.
10. Add integration and security tests.
11. Complete documentation and screenshots.
12. Deploy when the local workflow is reliable.

**Definition of done:** Churnscope is complete when the data
definitions are clear, analytics are correct, model evaluation is
reproducible, user data is protected, and the end-to-end flow is
documented and testable.
