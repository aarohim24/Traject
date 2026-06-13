# Requirements: Axon Phase 4 — Custom React Dashboard, Kubernetes, Enterprise Features

## Overview

These requirements govern Phase 4 of the Axon platform. They are written in EARS (Easy Approach
to Requirements Syntax) format. All requirements are additive — no existing Phase 1, 2, or 3
behavior is altered except where a requirement explicitly states an extension. Every existing test
suite must continue passing throughout Phase 4 development.

Correctness properties from `design.md` § 10 are referenced in the relevant acceptance criteria
below to indicate which properties must hold.

---

## Requirement 1: Custom React Dashboard

### 1.1 Dashboard Initialization

WHERE the repository root contains a `dashboard/` directory,
THE system SHALL provide a React 18 + TypeScript + Vite single-page application
that compiles without TypeScript errors (`tsc --noEmit` exits 0)
and passes all Vitest tests.

**Acceptance Criteria:**

- 1.1.1 WHEN the developer runs `npm install && npm run build` inside `dashboard/`,
  THEN the build SHALL complete successfully and produce a `dist/` directory containing
  `index.html` and all static assets.

- 1.1.2 WHEN `tsc --noEmit` is run inside `dashboard/`,
  THEN it SHALL exit with code 0 and report zero errors
  (`tsconfig.json` must have `"strict": true`).

- 1.1.3 WHEN `npm test -- --run` is run inside `dashboard/`,
  THEN all Vitest tests SHALL pass.

- 1.1.4 The `package.json` SHALL declare exact dependency ranges for:
  React ^18.3.0, TypeScript ^5.4.0, Vite ^5.3.0, Recharts ^2.12.0,
  Tailwind CSS ^3.4.0, TanStack Query ^5.40.0, React Router ^6.23.0,
  Zustand ^4.5.0, and Vitest ^1.6.0.

### 1.2 API Client

WHERE the dashboard makes a request to any Axon backend endpoint,
THE system SHALL route all HTTP calls through the `AxonAPIClient` class
in `dashboard/src/api/client.ts`.

**Acceptance Criteria:**

- 1.2.1 WHEN a backend response has HTTP status >= 300,
  THEN `AxonAPIClient` SHALL throw an `AxonAPIError` containing the HTTP status code
  and the response body message.

- 1.2.2 WHEN `AxonAPIClient` makes any request,
  THEN it SHALL include the `X-Axon-API-Key` header with the configured API key.

- 1.2.3 WHEN `VITE_AXON_BACKEND_URL` is set,
  THEN the API client SHALL use that value as the base URL;
  WHEN it is absent, the client SHALL default to `http://localhost:8000`.

- 1.2.4 The client SHALL expose typed methods:
  `getAttribution`, `getBudgets`, `getBudget`, `upsertBudget`, `deleteBudget`,
  `getSpans`, `getCacheStats`, `getHealth`.
  Each method SHALL return a typed Promise and SHALL NOT return `undefined`.

### 1.3 Page: CostOverview

**Acceptance Criteria:**

- 1.3.1 WHEN CostOverview mounts,
  THEN it SHALL display four stat cards: total cost (USD), total tokens, cache hit rate,
  and tokens saved by compression.

- 1.3.2 WHEN CostOverview mounts,
  THEN it SHALL render a cost-over-time line chart grouped by `feature_tag`,
  a cost-by-model bar chart, and a cost-by-provider donut chart.

- 1.3.3 WHEN the user selects a time range (24h, 7d, or 30d),
  THEN the page SHALL re-fetch attribution data with the corresponding
  `from_ts` / `to_ts` query parameters and update all charts and stat cards.

- 1.3.4 WHEN the page is mounted and not manually refreshed,
  THEN it SHALL automatically re-fetch data every 60 seconds via
  `refetchInterval: 60_000`.

- 1.3.5 WHEN data is loading,
  THEN the page SHALL display a loading skeleton or spinner in place of each chart.

### 1.4 Page: CompressionROI

**Acceptance Criteria:**

- 1.4.1 WHEN CompressionROI mounts,
  THEN it SHALL display stat cards for total tokens saved, total cost saved,
  average compression ratio, and shadow-mode vs live-mode split.

- 1.4.2 WHEN CompressionROI renders charts,
  THEN it SHALL include a tokens-saved-over-time area chart,
  a compression-ratio-by-feature-tag horizontal bar chart,
  and a cache-hit-rate-over-time line chart.

### 1.5 Page: BudgetManager

**Acceptance Criteria:**

- 1.5.1 WHEN BudgetManager mounts,
  THEN it SHALL display a table of all budgets with columns:
  `feature_tag`, `budget_usd`, `period`, `spent_usd`, `remaining_usd`, `pct_used`, status badge.

- 1.5.2 WHEN `pct_used < 0.80`,
  THEN the status badge SHALL be rendered with green (`text-green-400`).
  WHEN `0.80 <= pct_used < 1.00`,
  THEN the status badge SHALL be rendered with yellow (`text-yellow-400`).
  WHEN `pct_used >= 1.00`,
  THEN the status badge SHALL be rendered with red (`text-red-400`).

- 1.5.3 WHEN the user submits the add-budget inline form,
  THEN the dashboard SHALL call `upsertBudget` and refresh the budget list on success.

- 1.5.4 WHEN the user confirms a budget deletion,
  THEN the dashboard SHALL call `deleteBudget` and remove the budget from the list.

- 1.5.5 WHEN BudgetManager renders,
  THEN it SHALL render one `BudgetGauge` component per budget below the table.

### 1.6 Page: RouterAnalytics

**Acceptance Criteria:**

- 1.6.1 WHEN RouterAnalytics mounts,
  THEN it SHALL display a routing decisions table with columns:
  `timestamp`, `original_model`, `selected_model`, `task_type`, `complexity_tier`, `cost_delta_pct`.

- 1.6.2 WHEN RouterAnalytics renders charts,
  THEN it SHALL include a model-distribution donut chart and a task-type-breakdown bar chart.

- 1.6.3 WHEN RouterAnalytics mounts,
  THEN it SHALL display a cumulative cost savings stat card derived from routing decisions.

### 1.7 Page: SpanExplorer

**Acceptance Criteria:**

- 1.7.1 WHEN SpanExplorer mounts,
  THEN it SHALL display a filterable, paginated table of inference spans
  with 50 rows per page.

- 1.7.2 WHEN the user applies a filter (`feature_tag`, `model`, `provider`,
  `environment`, date range, or `compression_applied`),
  THEN the table SHALL update to show only matching spans.

- 1.7.3 WHEN the user clicks a span row,
  THEN the row SHALL expand to show `prompt_hash`, `artifact_type`,
  `routing_decision`, `tokens_saved`, and `batch_eligible`.

### 1.8 Design System

**Acceptance Criteria:**

- 1.8.1 The dashboard SHALL use only Tailwind utility classes for all styling.
  No custom CSS files SHALL exist in `dashboard/src/`.

- 1.8.2 The primary background SHALL be `bg-gray-950`,
  secondary background `bg-gray-900`, card background `bg-gray-800`.

- 1.8.3 The accent color for all interactive elements and chart primary series SHALL be teal:
  `text-teal-400` / `bg-teal-500` / `#2dd4bf` for Recharts.

- 1.8.4 All token counts SHALL be formatted with comma separators.
  All cost values SHALL be formatted with 6 decimal places when < $0.01,
  and 2 decimal places when >= $1.00.
  (Design § 10.6 — formatters correctness property.)

### 1.9 Docker Deployment

**Acceptance Criteria:**

- 1.9.1 WHEN `docker build -t axon-dashboard .` is run from `dashboard/`,
  THEN the build SHALL succeed using the multi-stage Dockerfile
  (node:20-alpine builder → nginx:alpine runtime).

- 1.9.2 WHEN the dashboard container is started,
  THEN navigating to any client-side route SHALL return `index.html`
  (nginx `try_files` SPA fallback).

- 1.9.3 WHEN a request is made to `/api/*` on the dashboard container,
  THEN nginx SHALL return 404.

---

## Requirement 2: Enterprise API Key Management

### 2.1 Key Generation

**Acceptance Criteria:**

- 2.1.1 WHEN `generate_api_key()` is called,
  THEN it SHALL return a tuple `(raw_key, key_hash)` where:
  - `raw_key` matches the pattern `axon_live_[0-9a-f]{32}`
  - `key_hash` is a valid bcrypt hash of `raw_key`
  - `len(raw_key) == 42`
  (Design § 10.1 — key format correctness property.)

- 2.1.2 WHEN `generate_api_key()` is called twice,
  THEN the two raw keys SHALL be different with overwhelming probability
  (collision probability < 2⁻¹²⁸).

- 2.1.3 The raw key SHALL never be stored in any database table, log, or span.
  Only `key_hash` and `key_prefix` (first 8 characters) SHALL be persisted.

### 2.2 Key Verification

**Acceptance Criteria:**

- 2.2.1 WHEN `verify_api_key(raw_key, db)` is called with a valid, non-revoked,
  non-expired key,
  THEN it SHALL return the corresponding `APIKeyRecord`.

- 2.2.2 WHEN `verify_api_key` is called with a revoked key,
  THEN it SHALL return `None`.

- 2.2.3 WHEN `verify_api_key` is called with an expired key
  (`expires_at` is not null and is in the past),
  THEN it SHALL return `None`.

- 2.2.4 WHEN `verify_api_key` is called with any invalid key,
  THEN it SHALL return `None` without raising an exception
  and SHALL NOT reveal the reason for failure in its return value.

- 2.2.5 WHEN `verify_api_key` returns a valid `APIKeyRecord`,
  THEN it SHALL update `last_used_at` on that record
  (fire-and-forget; failure does not affect the return value).
  (Design § 10.2 — bcrypt determinism correctness property.)

### 2.3 API Endpoints — Key Management

**Acceptance Criteria:**

- 2.3.1 WHEN `POST /v1/auth/keys` is called with an admin key,
  THEN it SHALL return HTTP 201 with `{ key, prefix, role, name, created_at }`.
  The `key` field SHALL contain the raw key and be shown exactly once.

- 2.3.2 WHEN `POST /v1/auth/keys` is called with a non-admin key,
  THEN it SHALL return HTTP 403.

- 2.3.3 WHEN `POST /v1/auth/keys` is called without a key,
  THEN it SHALL return HTTP 401.

- 2.3.4 WHEN `GET /v1/auth/keys` is called with an admin key,
  THEN it SHALL return a list of key records.
  The response SHALL NOT include `key_hash` or any raw key value.

- 2.3.5 WHEN `DELETE /v1/auth/keys/{prefix}` is called with an admin key,
  THEN it SHALL set `revoked=True` on the matching record and return HTTP 204.
  The record SHALL NOT be deleted from the database.

- 2.3.6 WHEN `DELETE /v1/auth/keys/{prefix}` is called with a prefix that
  does not exist,
  THEN it SHALL return HTTP 404.

### 2.4 Backward Compatibility

**Acceptance Criteria:**

- 2.4.1 WHEN the `X-Axon-API-Key` header contains the value from `settings.api_key`
  (the environment-variable key from Phase 2/3),
  THEN ALL existing endpoints SHALL continue to accept it as a valid admin key.
  No SDK reconfiguration SHALL be required.

- 2.4.2 WHEN the Phase 4 auth system is deployed,
  THEN all existing Phase 1, 2, and 3 tests SHALL continue to pass without modification.

---

## Requirement 3: RBAC and Audit Logging

### 3.1 Role Hierarchy

**Acceptance Criteria:**

- 3.1.1 The system SHALL define exactly three roles: `viewer`, `engineer`, `admin`,
  with the ordering `viewer (0) < engineer (1) < admin (2)`.

- 3.1.2 WHEN a `require_role("engineer")` dependency is applied to an endpoint,
  THEN it SHALL accept requests from both `engineer` and `admin` key holders,
  AND SHALL reject requests from `viewer` key holders with HTTP 403.

- 3.1.3 WHEN a `require_role("admin")` dependency is applied,
  THEN it SHALL reject all non-admin roles with HTTP 403.
  (Design § 10.3 — role hierarchy correctness property.)

### 3.2 Audit Log

**Acceptance Criteria:**

- 3.2.1 WHEN any key-management mutation occurs (key creation, key revocation),
  THEN `append_log` SHALL be called and a new `AuditLogRecord` SHALL be inserted.

- 3.2.2 The `audit_log` table SHALL be append-only.
  No `UPDATE` or `DELETE` SQL SHALL ever be executed against it.
  The `AuditService` class SHALL expose only `append_log` — no update or delete methods.

- 3.2.3 WHEN `GET /v1/audit` is called with an admin key,
  THEN it SHALL return audit log entries filtered by the supplied query parameters
  (`from_ts`, `to_ts`, `actor_prefix`, `action`).
  The default limit SHALL be 100; the maximum SHALL be 1000.

- 3.2.4 WHEN `GET /v1/audit` is called with a non-admin key,
  THEN it SHALL return HTTP 403.

- 3.2.5 Each `AuditLogRecord` SHALL include:
  `id`, `timestamp`, `actor_key_prefix`, `action`, `resource`, `result`, `ip_address`, `details`.

---

## Requirement 4: Quality Regression Detector

### 4.1 Offline Execution

**Acceptance Criteria:**

- 4.1.1 The quality regression detector SHALL run as a background job via APScheduler
  at 03:00 UTC daily and SHALL NOT execute synchronously on any inference path.

- 4.1.2 WHEN the quality check job completes,
  THEN the result SHALL be logged via structlog and SHALL NOT affect any API response.

- 4.1.3 WHEN the quality check job raises any exception,
  THEN the exception SHALL be caught, logged via structlog, and the scheduler
  SHALL NOT crash.

### 4.2 Sampling

**Acceptance Criteria:**

- 4.2.1 WHEN `run_daily_check` executes,
  THEN it SHALL sample up to 50 spans from the last 24 hours where
  `routing_decision IS NOT NULL` (routed spans).

- 4.2.2 WHEN `run_daily_check` executes,
  THEN it SHALL also sample up to 50 baseline spans from the last 24 hours
  where `routing_decision IS NULL`.

- 4.2.3 WHEN fewer than the requested number of spans are available,
  THEN the detector SHALL proceed with the available spans
  and record the actual count in `QualityReport.spans_sampled`.

### 4.3 Regression Detection

**Acceptance Criteria:**

- 4.3.1 WHEN `routed_avg_quality >= baseline_avg_quality - 0.3`,
  THEN `regression_detected` SHALL be `False`.

- 4.3.2 WHEN `routed_avg_quality < baseline_avg_quality - 0.3`,
  THEN `regression_detected` SHALL be `True`
  AND a structlog warning SHALL be emitted.

- 4.3.3 WHEN `spans_sampled == 0`,
  THEN `regression_detected` SHALL be `False`.
  (Design § 10.4 — regression threshold correctness property.)

### 4.4 LLM Judge

**Acceptance Criteria:**

- 4.4.1 The quality scoring SHALL use the smallest available model:
  `gpt-4o-mini` or `claude-haiku-20240307`.

- 4.4.2 WHEN the LLM judge call fails for any reason,
  THEN `_score_quality` SHALL return 3.0 (neutral score)
  and log a warning via structlog.
  It SHALL NOT raise an exception.

- 4.4.3 Quality scores returned by the judge SHALL be on a scale of 1.0 to 5.0.

### 4.5 QualityReport

**Acceptance Criteria:**

- 4.5.1 `run_daily_check` SHALL return a `QualityReport` dataclass instance
  containing: `date`, `spans_sampled`, `routed_avg_quality`, `baseline_avg_quality`,
  `regression_detected`, `regression_threshold` (default 0.3), `details`.

---

## Requirement 5: Batch Eligibility Tagger

### 5.1 SDK Changes

**Acceptance Criteria:**

- 5.1.1 WHEN `instrument()` or `patch()` is called with `batch_eligible=True`,
  THEN every `InferenceSpan` emitted SHALL have `batch_eligible=True`.

- 5.1.2 WHEN `instrument()` or `patch()` is called with `batch_eligible=False`,
  THEN every `InferenceSpan` emitted SHALL have `batch_eligible=False`,
  regardless of the `AXON_BATCH_ELIGIBLE_FEATURES` environment variable.

- 5.1.3 WHEN `instrument()` or `patch()` is called with `batch_eligible=None` (default)
  AND the `AXON_BATCH_ELIGIBLE_FEATURES` environment variable contains the
  current `feature_tag`,
  THEN every `InferenceSpan` emitted SHALL have `batch_eligible=True`.

- 5.1.4 WHEN `instrument()` or `patch()` is called with `batch_eligible=None`
  AND the `feature_tag` is NOT in `AXON_BATCH_ELIGIBLE_FEATURES`,
  THEN `batch_eligible` SHALL default to `False`.
  (Design § 10.5 — batch tagger env var parsing correctness property.)

- 5.1.5 `InferenceSpan.batch_eligible` SHALL default to `False` for all existing
  call sites that do not pass the new parameter.

### 5.2 Backward Compatibility

**Acceptance Criteria:**

- 5.2.1 WHEN Phase 4 SDK changes are applied,
  THEN all 466 existing Python SDK tests SHALL continue to pass without modification.

- 5.2.2 `mypy --strict` on `sdk/python/axon` SHALL report zero errors after the addition.

### 5.3 Backend and Database

**Acceptance Criteria:**

- 5.3.1 The `inference_spans` table SHALL gain a `batch_eligible` boolean column
  via the 0002 Alembic migration, with `server_default = false`.

- 5.3.2 Existing rows in `inference_spans` SHALL have `batch_eligible = false`
  after the migration runs.

---

## Requirement 6: Kubernetes Deployment

### 6.1 Helm Chart

**Acceptance Criteria:**

- 6.1.1 WHEN `helm lint deploy/kubernetes/helm/axon` is run,
  THEN it SHALL exit with zero errors.

- 6.1.2 The Helm chart SHALL be at version `0.4.0` and appVersion `"0.4.0"`.

- 6.1.3 The chart SHALL include the following templates:
  `deployment-backend.yaml`, `deployment-dashboard.yaml`,
  `service-backend.yaml`, `service-dashboard.yaml`,
  `configmap.yaml`, `secret.yaml`, `ingress.yaml`,
  `pvc-postgres.yaml`, `pvc-redis.yaml`, `_helpers.tpl`.

- 6.1.4 All Deployment and Service templates SHALL use the `axon.labels`
  and `axon.selectorLabels` named templates defined in `_helpers.tpl`.

### 6.2 Backend Deployment

**Acceptance Criteria:**

- 6.2.1 The backend Deployment SHALL default to 2 replicas.

- 6.2.2 The backend Deployment SHALL configure a readiness probe and a liveness probe,
  both targeting `GET /health` on port 8000,
  with `failureThreshold: 3`.

- 6.2.3 The backend Deployment SHALL set resource requests of 250m CPU / 512Mi memory
  and limits of 500m CPU / 1Gi memory by default.

### 6.3 Dashboard Deployment

**Acceptance Criteria:**

- 6.3.1 The dashboard Deployment SHALL default to 1 replica.

- 6.3.2 The dashboard Deployment SHALL set resource requests of 100m CPU / 128Mi memory
  and limits of 200m CPU / 256Mi memory by default.

### 6.4 Storage

**Acceptance Criteria:**

- 6.4.1 The chart SHALL include a PersistentVolumeClaim for PostgreSQL
  with default size 20Gi and access mode `ReadWriteOnce`.

- 6.4.2 The chart SHALL include a PersistentVolumeClaim for Redis
  with default size 2Gi and access mode `ReadWriteOnce`.

### 6.5 Ingress

**Acceptance Criteria:**

- 6.5.1 WHEN `ingress.enabled = false` (default),
  THEN the Ingress resource SHALL NOT be created.

- 6.5.2 WHEN `ingress.enabled = true`,
  THEN the Ingress SHALL route traffic to the backend and dashboard services.

### 6.6 Docker Compose Update

**Acceptance Criteria:**

- 6.6.1 WHEN `docker compose -f deploy/docker-compose.yml up -d` is run,
  THEN 5 services SHALL start and reach healthy state:
  `postgres`, `redis`, `axon-backend`, `grafana`, `axon-dashboard`.

- 6.6.2 The `axon-dashboard` service SHALL depend on `axon-backend`
  with `condition: service_healthy`.

- 6.6.3 WHEN the dashboard container is running,
  THEN the dashboard SHALL be accessible at `http://localhost:5173`.

---

## Requirement 7: Phase 3 Coverage and Regression

### 7.1 Coverage Targets

**Acceptance Criteria:**

- 7.1.1 WHEN `pytest sdk/python/tests --cov=axon --cov-fail-under=85` is run,
  THEN it SHALL pass. The coverage threshold is raised from 80% to 85% for Phase 4.

- 7.1.2 WHEN `pytest backend/tests --cov=axon_backend --cov-fail-under=75` is run,
  THEN it SHALL pass.

### 7.2 backend_client.py Coverage

**Acceptance Criteria:**

- 7.2.1 WHEN `send_span` is called,
  THEN it SHALL fire a POST request to `/v1/spans` and SHALL NOT raise
  on a non-2xx response (fire-and-forget).

- 7.2.2 WHEN `check_budget` is called and the backend returns any error
  (HTTP >= 400 or network timeout),
  THEN it SHALL return a `BudgetStatus` with `allowed=True` (fail open).

### 7.3 semantic_cache.py Coverage

**Acceptance Criteria:**

- 7.3.1 WHEN `lookup` is called for a prompt not in the cache,
  THEN it SHALL return `None`.

- 7.3.2 WHEN `store` or `lookup` encounters any backend error,
  THEN it SHALL return gracefully (None for lookup, no-op for store)
  without raising.

### 7.4 cascade_tracer.py Coverage

**Acceptance Criteria:**

- 7.4.1 WHEN `get_cascade_cost` is called with a valid trace ID,
  THEN it SHALL return a `CascadeCostSummary` with correct cost totals.

- 7.4.2 WHEN `get_cascade_cost` is called and the backend client raises,
  THEN it SHALL return an empty `CascadeCostSummary`.

### 7.5 CI Additions

**Acceptance Criteria:**

- 7.5.1 The `.github/workflows/ci.yml` SHALL include a `dashboard-test` job that:
  - Runs on `ubuntu-latest`
  - Checks out code, sets up Node 20
  - Runs `npm install` and `npm run typecheck` inside `dashboard/`
  - Runs `npm test -- --coverage` inside `dashboard/`

- 7.5.2 The `.github/workflows/ci.yml` SHALL include a `helm-lint` job that:
  - Runs on `ubuntu-latest`
  - Installs Helm 3 via `azure/setup-helm@v3`
  - Runs `helm lint deploy/kubernetes/helm/axon`

### 7.6 Phase 1/2/3 Regression Guard

**Acceptance Criteria:**

- 7.6.1 WHEN all 25 Phase 4 commits are applied,
  THEN `pytest sdk/python/tests` SHALL pass with all 466 existing tests green.

- 7.6.2 WHEN all Phase 4 changes are applied,
  THEN `cd sdk/typescript && npm test` SHALL pass with all 23 existing TypeScript tests green.

- 7.6.3 WHEN all Phase 4 changes are applied,
  THEN `mypy sdk/python/axon --strict` SHALL exit with 0 errors.

- 7.6.4 WHEN all Phase 4 changes are applied,
  THEN `mypy backend/axon_backend --strict` SHALL exit with 0 errors.

- 7.6.5 WHEN all Phase 4 changes are applied,
  THEN `ruff check sdk/python/axon sdk/python/tests` SHALL report no violations.

- 7.6.6 WHEN all Phase 4 changes are applied,
  THEN `curl http://localhost:8000/health` SHALL return
  `{"status":"ok","version":"0.4.0"}`.
