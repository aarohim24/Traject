# Implementation Plan

## Overview

Phase 4 delivers six features across 25 atomic commits: enterprise auth (API key management,
RBAC, audit log), quality regression detector, batch eligibility tagger, a custom React
dashboard, Kubernetes Helm chart, and Phase 3 coverage improvements. Tasks are organized to
maximize parallelism — the first wave starts backend models, SDK tagging, and dashboard
scaffolding simultaneously since all three are independent. Each commit leaves all tests green.

---

## Tasks

- [x] 1. feat(backend): add api_key and audit_log models
  - [x] Create `backend/axon_backend/models/api_key.py` — `APIKeyRecord(Base)` with columns: `id` (UUID PK), `name` (str), `key_hash` (str), `key_prefix` (str, len 16, indexed, unique), `role` (str: admin|engineer|viewer), `created_at` (datetime, server_default now()), `last_used_at` (datetime|None), `expires_at` (datetime|None), `revoked` (bool, default false), `created_by` (str)
  - [x] Create `backend/axon_backend/models/audit_log.py` — `AuditLogRecord(Base)` with columns: `id` (UUID PK), `timestamp` (datetime, indexed), `actor_key_prefix` (str), `action` (str), `resource` (str), `result` (str: success|denied|error), `ip_address` (str, max 45), `details` (Text|None)
  - [x] Verify both ORM models import cleanly from `axon_backend.models` package; add them to `__init__.py` or ensure Alembic can discover them
  - [x] Ensure `mypy --strict` on `backend/axon_backend/models/` passes with zero errors

- [x] 2. feat(backend): implement auth service (keygen, verify, rbac)
  - [x] Create `backend/axon_backend/services/auth_service.py` with module-level docstring
  - [x] Implement `generate_api_key() -> tuple[str, str]` — raw key format `axon_live_{secrets.token_hex(16)}` (32 hex chars), bcrypt hash; never store raw key
  - [x] Implement `async def verify_api_key(raw_key: str, db: AsyncSession) -> APIKeyRecord | None` — lookup by prefix (first 8 chars), bcrypt.verify, check `revoked` and `expires_at`; update `last_used_at` on success (fire-and-forget); return None on any failure without exposing reason
  - [x] Implement `ROLE_ORDER: dict[str, int] = {"viewer": 0, "engineer": 1, "admin": 2}`
  - [x] Implement `require_role(minimum_role: str)` — FastAPI dependency factory returning async Depends-compatible function; reads `X-Axon-API-Key` header; raises HTTP 401 on missing/invalid key, HTTP 403 on insufficient role
  - [x] Add virtual admin path: if `raw_key == settings.api_key`, return a synthetic `APIKeyRecord` with role `admin` without a DB lookup (backward compat per Req 2.4.1)
  - [x] Full type annotations; `mypy --strict` clean

- [x] 3. feat(backend): implement audit service (append-only log)
  - [x] Create `backend/axon_backend/services/audit_service.py` with module-level docstring
  - [x] Implement `async def append_log(db: AsyncSession, actor_key_prefix: str, action: str, resource: str, result: str, ip_address: str, details: dict[str, Any] | None = None) -> None`
  - [x] `append_log` must never raise — catch all exceptions and log via structlog
  - [x] `details` serialized to JSON string before insert
  - [x] No update or delete methods on this service — append only
  - [x] Full type annotations; `mypy --strict` clean

- [x] 4. feat(backend): add auth and audit API endpoints
  - [x] Create `backend/axon_backend/api/v1/auth.py` — router with `POST /v1/auth/keys`, `GET /v1/auth/keys`, `DELETE /v1/auth/keys/{prefix}`; all endpoints require admin via `require_role("admin")`
  - [x] `POST /v1/auth/keys`: accepts `{name: str, role: str, expires_in_days: int | None}`; calls `generate_api_key()`; inserts `APIKeyRecord`; calls `append_log`; returns HTTP 201 with raw key (shown once)
  - [x] `GET /v1/auth/keys`: returns list of key records; response MUST NOT include `key_hash` or raw key values
  - [x] `DELETE /v1/auth/keys/{prefix}`: sets `revoked=True`; calls `append_log`; returns HTTP 204; returns HTTP 404 if prefix not found
  - [x] Create `backend/axon_backend/api/v1/audit.py` — router with `GET /v1/audit`; requires admin; query params `from_ts`, `to_ts`, `actor_prefix`, `action`, `limit` (default 100, max 1000)
  - [x] Register both new routers in the FastAPI app's main router
  - [x] Full type annotations; `mypy --strict` clean

- [x] 5. feat(backend): add Alembic migration 0002
  - [x] Create `backend/migrations/versions/0002_phase4_schema.py` with `revision = "0002"`, `down_revision = "0001"`
  - [x] `upgrade()`: create table `api_keys` with all columns and `ix_api_keys_prefix` index; create table `audit_log` with all columns and `ix_audit_log_timestamp`, `ix_audit_log_actor` indexes; `op.add_column("inference_spans", Column("batch_eligible", Boolean, server_default=text("false"), nullable=False))`
  - [x] `downgrade()`: drop column `inference_spans.batch_eligible`; drop table `audit_log`; drop table `api_keys`
  - [x] Migration must match the ORM models exactly (same column names, types, constraints)
  - [x] Full type annotations; `mypy --strict` clean on migration file

- [x] 6. test(backend): add auth service and API tests
  - [x] Create `backend/tests/unit/test_auth_service.py`: test `generate_api_key` format (pattern `axon_live_[0-9a-f]{32}`, len 42); test bcrypt verify returns True for correct key, False for wrong key; test `verify_api_key` returns None for revoked record; test `verify_api_key` returns None for expired record; test role ordering (`ROLE_ORDER["viewer"] < ROLE_ORDER["engineer"] < ROLE_ORDER["admin"]`)
  - [x] Create `backend/tests/unit/test_audit_service.py`: test `append_log` inserts exactly one `AuditLogRecord`; test `append_log` never raises on DB error; verify `AuditService` has no update/delete methods
  - [x] Create `backend/tests/integration/test_auth_api.py`: test `POST /v1/auth/keys` with admin key → 201 + raw key in response; test `POST /v1/auth/keys` with viewer key → 403; test `POST /v1/auth/keys` with no key → 401; test `GET /v1/auth/keys` response contains no `key_hash` field; test `DELETE /v1/auth/keys/{prefix}` revokes correctly and returns 204; test `GET /v1/audit` with admin key returns entries
  - [x] All tests use async fixtures; no mocking of the module under test

- [x] 7. feat(sdk): add batch eligibility tagger to instrumentor
  - [x] Add `batch_eligible: bool = False` field to `InferenceSpan` in `sdk/python/axon/models.py` (one line addition, after `environment`)
  - [x] Add `batch_eligible: bool | None = None` parameter to `instrument()` in `sdk/python/axon/core/instrumentor.py`
  - [x] Add `batch_eligible: bool | None = None` parameter to `patch()` — forward to `instrument()` call within patch
  - [x] Implement `_resolve_batch_eligible(feature_tag: str, explicit: bool | None) -> bool` — if explicit is not None return it; else parse `AXON_BATCH_ELIGIBLE_FEATURES` env var as comma-separated list and return `feature_tag in parsed_set`
  - [x] Call `_resolve_batch_eligible` inside `_run_pipeline` and pass result to `InferenceSpan(batch_eligible=...)`
  - [x] Verify all 466 existing tests still pass; `mypy --strict` on `sdk/python/axon` clean

- [x] 8. feat(backend): add quality regression detector service
  - [x] Create `backend/axon_backend/services/quality_detector.py` with module-level docstring
  - [x] Define `@dataclass class QualityReport` with fields: `date: datetime`, `spans_sampled: int`, `routed_avg_quality: float`, `baseline_avg_quality: float`, `regression_detected: bool`, `regression_threshold: float`, `details: list[dict[str, Any]]`
  - [x] Implement `class QualityDetector` with class constants `REGRESSION_THRESHOLD = 0.3`, `DEFAULT_SAMPLE_SIZE = 50`, `JUDGE_MODELS = ["gpt-4o-mini", "claude-haiku-20240307"]`
  - [x] Implement `async def run_daily_check(self, db: AsyncSession, sample_size: int = 50) -> QualityReport`: sample routed spans (routing_decision IS NOT NULL, last 24h, LIMIT sample_size); sample baseline spans (routing_decision IS NULL, last 24h, LIMIT sample_size); score each via `_score_quality`; compute averages; set `regression_detected = routed_avg < baseline_avg - REGRESSION_THRESHOLD`; emit structlog warning if regression detected; never raises
  - [x] Implement `async def _score_quality(self, span: InferenceSpanRecord, judge_model: str) -> float`: calls LLM judge; returns 3.0 and logs warning on any error
  - [x] Handle edge case: zero spans sampled → `regression_detected = False`, all averages = 0.0
  - [x] Full type annotations; `mypy --strict` clean

- [x] 9. feat(backend): add quality check APScheduler job
  - [x] Add `async def _run_quality_check() -> None` to `backend/axon_backend/workers/scheduler.py` — creates `QualityDetector`, runs `run_daily_check`, logs result via structlog; catches all exceptions (logs, never re-raises)
  - [x] Inside `register_jobs()`, add `scheduler.add_job(_run_quality_check, trigger="cron", hour=3, minute=0, id="quality_check", replace_existing=True)`
  - [x] Verify the three existing scheduler jobs are unchanged and their tests still pass
  - [x] `mypy --strict` on `workers/scheduler.py` clean

- [x] 10. test(sdk): add coverage for backend_client, semantic_cache, cascade_tracer
  - [x] Create `sdk/python/tests/unit/test_backend_client.py` using `respx` to mock HTTP: test `send_span` fires POST to `/v1/spans` with correct payload; test `send_span` does not raise on 500 response; test `check_budget` returns `allowed=True` on HTTP 500; test `check_budget` returns `allowed=True` on network timeout
  - [x] Create `sdk/python/tests/unit/test_semantic_cache.py` using mock `BackendClient`: test `lookup` returns None on cache miss; test `store` does not raise; test `lookup` returns None on backend error (fail open); test `store` does not raise on backend error
  - [x] Add tests to `sdk/python/tests/unit/test_cascade_tracer.py`: test `get_cascade_cost` returns `CascadeCostSummary` with correct cost totals (mock backend client); test `get_cascade_cost` returns empty summary when backend client raises
  - [ ] Verify `pytest sdk/python/tests --cov=axon --cov-fail-under=85` passes after all new tests

- [x] 11. feat(dashboard): initialize React + Vite + Tailwind project
  - [x] Create `dashboard/package.json` with exact dependency versions from spec: React ^18.3.0, react-router-dom ^6.23.0, @tanstack/react-query ^5.40.0, recharts ^2.12.0, zustand ^4.5.0, clsx ^2.1.0, TypeScript ^5.4.0, Vite ^5.3.0, tailwindcss ^3.4.0, autoprefixer ^10.4.0, postcss ^8.4.0, vitest ^1.6.0, @testing-library/react ^16.0.0, @testing-library/user-event ^14.5.0, jsdom ^24.0.0
  - [x] Create `dashboard/tsconfig.json` with `"strict": true`, `"noImplicitAny": true`, target `"ES2022"`, lib `["ES2022", "DOM"]`
  - [x] Create `dashboard/vite.config.ts` with `@vitejs/plugin-react` and Vitest test configuration (environment: jsdom)
  - [x] Create `dashboard/tailwind.config.ts` with `content: ["./src/**/*.{ts,tsx}"]`
  - [x] Create `dashboard/postcss.config.js` with tailwindcss and autoprefixer plugins
  - [x] Create `dashboard/index.html` as Vite entry HTML pointing to `src/main.tsx`
  - [x] Create `dashboard/src/main.tsx` — mounts `<App />` into `#root`
  - [x] Create `dashboard/src/App.tsx` — `<QueryClientProvider>`, `<BrowserRouter>`, `<Routes>` placeholder for all 5 pages
  - [x] Create `dashboard/src/lib/constants.ts` — `TIME_RANGES`, `COLORS`, `DEFAULT_PAGE_SIZE = 50`, `REFETCH_INTERVAL_MS = 60_000`
  - [x] Create `dashboard/src/lib/formatters.ts` — `formatTokens(n)`, `formatCost(usd)`, `formatPct(ratio)` with JSDoc
  - [x] Verify `npm run build` succeeds; `tsc --noEmit` passes

- [x] 12. feat(dashboard): implement API client with typed methods
  - [x] Create `dashboard/src/api/types.ts` — TypeScript interfaces: `AttributionParams`, `AttributionResponse`, `BudgetStatus`, `BudgetPayload`, `SpanQueryParams`, `InferenceSpanResponse`, `CacheStats`, `HealthStatus`, `AxonAPIErrorPayload`
  - [x] Create `dashboard/src/api/client.ts` — `AxonAPIError` class (extends Error, exposes `status: number`); `AxonAPIClient` class with private `request<T>` helper (adds `X-Axon-API-Key` header, throws `AxonAPIError` on non-2xx); all 8 typed public methods
  - [x] Environment variable resolution: `VITE_AXON_BACKEND_URL` defaulting to `http://localhost:8000`, `VITE_AXON_API_KEY`
  - [x] No `any` without inline comment
  - [x] `tsc --noEmit` passes

- [x] 13. feat(dashboard): implement layout (sidebar, header)
  - [x] Create `dashboard/src/components/layout/Sidebar.tsx` — navigation links to all 5 pages using React Router `<NavLink>`; uses `bg-gray-900`, `border-gray-700`; active link styled with `text-teal-400`
  - [x] Create `dashboard/src/components/layout/Header.tsx` — displays current page title; includes global time-range selector (24h / 7d / 30d) updating Zustand store
  - [x] Create `dashboard/src/components/layout/Layout.tsx` — wraps `<Sidebar>` + `<Header>` + `<Outlet />`; uses `bg-gray-950` root background
  - [x] Update `dashboard/src/App.tsx` — wrap all page routes inside `<Layout>`
  - [x] `tsc --noEmit` passes

- [x] 14. feat(dashboard): implement CostOverview page
  - [x] Create `dashboard/src/components/ui/StatCard.tsx` — accepts `label: string`, `value: string`, `delta?: string`; styled with `bg-gray-800`, `border-gray-700`, teal accent border
  - [x] Create `dashboard/src/components/ui/CostChart.tsx` — Recharts `<LineChart>` grouped by `feature_tag`; uses `#2dd4bf` as primary color
  - [x] Create `dashboard/src/hooks/useAttribution.ts` — `useQuery` wrapper calling `client.getAttribution(params)`; `refetchInterval: REFETCH_INTERVAL_MS`
  - [x] Create `dashboard/src/pages/CostOverview.tsx` — renders 4 stat cards (total cost, total tokens, cache hit rate, tokens saved); renders CostChart + bar chart (model) + donut chart (provider); top-10 feature tags sortable table; shows loading skeleton while fetching
  - [x] `tsc --noEmit` passes

- [x] 15. feat(dashboard): implement CompressionROI page
  - [x] Create `dashboard/src/components/ui/CompressionChart.tsx` — area chart for tokens saved over time; horizontal bar chart for compression ratio by feature_tag
  - [x] Create `dashboard/src/pages/CompressionROI.tsx` — 4 stat cards (tokens saved, cost saved, avg compression ratio, shadow/live split); renders CompressionChart components; cache hit rate line chart; cumulative cost saved stat card
  - [x] `tsc --noEmit` passes

- [x] 16. feat(dashboard): implement BudgetManager page
  - [x] Create `dashboard/src/components/ui/BudgetGauge.tsx` — Recharts `<RadialBarChart>` showing `pct_used`; color determined by status (green/yellow/red)
  - [x] Create `dashboard/src/hooks/useBudgets.ts` — `useQuery` for budget list; `useMutation` wrappers for `upsertBudget` and `deleteBudget` with `onSuccess` invalidation
  - [x] Create `dashboard/src/pages/BudgetManager.tsx` — budget table with status badges; inline add/edit form (no modal); inline delete confirmation; one `BudgetGauge` per feature tag below table
  - [x] Status badge colors: `text-green-400` (< 80%), `text-yellow-400` (80–100%), `text-red-400` (≥ 100%)
  - [x] `tsc --noEmit` passes

- [x] 17. feat(dashboard): implement RouterAnalytics page
  - [x] Create `dashboard/src/components/ui/RouterDecisionTable.tsx` — sortable table with columns: `timestamp`, `original_model`, `selected_model`, `task_type`, `complexity_tier`, `cost_delta_pct`
  - [x] Create `dashboard/src/pages/RouterAnalytics.tsx` — routing decisions table; model distribution donut chart; cumulative cost savings stat card; task type breakdown bar chart
  - [x] `tsc --noEmit` passes

- [x] 18. feat(dashboard): implement SpanExplorer page
  - [x] Create `dashboard/src/components/ui/SpanTable.tsx` — paginated table (50 rows/page); expandable rows showing `prompt_hash`, `artifact_type`, `routing_decision`, `tokens_saved`, `batch_eligible`
  - [x] Create `dashboard/src/hooks/useSpans.ts` — `useQuery` wrapper calling `client.getSpans(params)` with filter params
  - [x] Create `dashboard/src/pages/SpanExplorer.tsx` — filter bar (feature_tag, model, provider, environment, date range, compression_applied); renders `SpanTable`; pagination controls
  - [x] `tsc --noEmit` passes

- [x] 19. test(dashboard): add Vitest tests for pages and formatters
  - [x] Update `dashboard/vite.config.ts` to include `@vitest/coverage-v8` and test setup file
  - [x] Create `dashboard/src/tests/formatters.test.ts` — test `formatTokens` adds comma separators for n >= 1000; test `formatCost` uses 6 decimals for values < 0.01 and 2 decimals for values >= 1.0; test `formatPct` rounds to 1 decimal and stays in [0%, 100%]
  - [x] Create `dashboard/src/tests/CostOverview.test.tsx` — mock API client; render CostOverview with `QueryClientProvider`; assert 4 stat cards rendered; assert time range selector renders 3 options; assert loading skeleton shown before data resolves
  - [x] Create `dashboard/src/tests/BudgetManager.test.tsx` — mock API client; render BudgetManager; assert budget table rows render; assert status badge color correct per pct_used threshold; assert add budget form submits and calls `upsertBudget`
  - [x] Verify `npm test -- --run` passes all tests

- [x] 20. feat(deploy): add dashboard service to Docker Compose
  - [x] Create `dashboard/Dockerfile` — multi-stage: `FROM node:20-alpine AS builder`, `WORKDIR /app`, `COPY package.json .`, `RUN npm install`, `COPY . .`, `RUN npm run build`; second stage `FROM nginx:alpine`, copy dist, copy nginx.conf, `EXPOSE 80`
  - [x] Create `dashboard/nginx.conf` — `listen 80`, `root /usr/share/nginx/html`, `location / { try_files $uri $uri/ /index.html; }`, `location /api { return 404; }`
  - [x] Update `deploy/docker-compose.yml` — add `axon-dashboard` service: build context `../dashboard`, environment `VITE_AXON_BACKEND_URL` and `VITE_AXON_API_KEY`, depends_on `axon-backend` with `condition: service_healthy`, ports `5173:80`
  - [x] Update `deploy/.env.example` — add `VITE_AXON_BACKEND_URL=http://localhost:8000` and `VITE_AXON_API_KEY=dev-key-change-in-production`
  - [x] Verify `docker compose config` validates without errors

- [x] 21. feat(deploy): add Kubernetes Helm chart
  - [x] Create `deploy/kubernetes/helm/axon/Chart.yaml` — `apiVersion: v2`, `name: axon`, `description: Axon AI inference optimization platform`, `version: 0.4.0`, `appVersion: "0.4.0"`
  - [x] Create `deploy/kubernetes/helm/axon/values.yaml` — backend (replicaCount 2, image, resources), dashboard (replicaCount 1, image, resources), postgres (enabled true, storageSize 20Gi), redis (enabled true, storageSize 2Gi), ingress (enabled false, host "")
  - [x] Create `deploy/kubernetes/helm/axon/templates/_helpers.tpl` — `axon.labels` and `axon.selectorLabels` named templates
  - [x] Create `templates/deployment-backend.yaml` — uses values.backend; readiness probe `GET /health:8000` periodSeconds 10 failureThreshold 3; liveness probe `GET /health:8000` periodSeconds 20 failureThreshold 3
  - [x] Create `templates/deployment-dashboard.yaml` — uses values.dashboard
  - [x] Create `templates/service-backend.yaml` — ClusterIP, port 8000
  - [x] Create `templates/service-dashboard.yaml` — ClusterIP, port 80
  - [x] Create `templates/configmap.yaml` — non-secret env vars
  - [x] Create `templates/secret.yaml` — DATABASE_URL, REDIS_URL, API_KEY (base64 via `{{ b64enc }}`)
  - [x] Create `templates/ingress.yaml` — `{{- if .Values.ingress.enabled }}` guard
  - [x] Create `templates/pvc-postgres.yaml` — 20Gi ReadWriteOnce; `{{- if .Values.postgres.enabled }}` guard
  - [x] Create `templates/pvc-redis.yaml` — 2Gi ReadWriteOnce; `{{- if .Values.redis.enabled }}` guard
  - [x] Create `deploy/kubernetes/README.md` — prerequisites (kubectl, helm 3), quick install command, values customization guide, upgrade procedure
  - [x] Verify `helm lint deploy/kubernetes/helm/axon` exits 0

- [x] 22. ci: add dashboard-test and helm-lint jobs
  - [x] Update `.github/workflows/ci.yml` — add `dashboard-test` job: `runs-on: ubuntu-latest`; steps: checkout, `actions/setup-node@v4` with node-version 20, `cd dashboard && npm install`, `npm run typecheck`, `npm test -- --coverage`
  - [x] Add `helm-lint` job to `.github/workflows/ci.yml`: `runs-on: ubuntu-latest`; steps: checkout, `azure/setup-helm@v3`, `helm lint deploy/kubernetes/helm/axon`
  - [x] Ensure new jobs do not break any existing CI jobs
  - [x] Verify YAML is valid (`yamllint` or equivalent)

- [x] 23. docs: add dashboard guide, enterprise auth, k8s deployment docs
  - [x] Create `docs/dashboard-guide.md` — sections: what the dashboard provides vs Grafana; running via Docker Compose (port 5173) and standalone; each of the 5 pages explained with expected data; configuration (VITE_AXON_BACKEND_URL, VITE_AXON_API_KEY)
  - [x] Create `docs/enterprise-auth.md` — sections: API key management workflow; role descriptions and permissions (viewer/engineer/admin); key rotation procedure; audit log access and interpretation; backward compatibility note for env-var key
  - [x] Create `docs/kubernetes-deployment.md` — sections: prerequisites (kubectl ≥ 1.24, helm ≥ 3.0); quick install command; production values customization; upgrade procedure; resource requirements per service

- [x] 24. docs: update README — Phase 4 in progress
  - [x] Update `README.md` — add dashboard screenshot placeholder section; update Docker Compose quickstart to mention dashboard at `http://localhost:5173`; update roadmap table: mark Phase 4 as "in progress" with key features listed; retain Phase 5 as "not started"

- [x] 25. chore: Phase 4 complete — all checks passing
  - [x] Run full validation checklist: `mypy sdk/python/axon --strict` → 0 errors; `mypy backend/axon_backend --strict` → 0 errors; `ruff check sdk/python/axon sdk/python/tests` → clean; `pytest sdk/python/tests --cov=axon --cov-fail-under=85` → passes; `pytest backend/tests --cov=axon_backend --cov-fail-under=75` → passes; `cd dashboard && npm run typecheck` → 0 errors; `cd dashboard && npm test -- --run` → all pass; `cd sdk/typescript && npm test` → 23 passed; `helm lint deploy/kubernetes/helm/axon` → no errors
  - [x] Verify `git log --oneline` shows exactly 25 new commits since Phase 3 tag
  - [x] Confirm `docker compose -f deploy/docker-compose.yml up -d` brings up 5 healthy services
  - [x] Confirm `POST /v1/auth/keys` with viewer key → 403; with admin key → 201
  - [x] Update `backend/axon_backend/core/config.py` version string to `"0.4.0"` if not already set
  - [x] Tag commit as `v0.4.0`

---

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "parallel": true,
      "tasks": [1, 7, 11],
      "rationale": "Backend models, SDK batch tagger, and dashboard initialization are fully independent — no shared files"
    },
    {
      "wave": 2,
      "parallel": true,
      "tasks": [2, 3, 12],
      "rationale": "Auth service depends on models (task 1), audit service depends on models (task 1), dashboard API client depends on dashboard init (task 11)"
    },
    {
      "wave": 3,
      "parallel": true,
      "tasks": [4, 8, 13],
      "rationale": "Auth endpoints depend on auth+audit services (tasks 2,3), quality detector depends on models (task 1), dashboard layout depends on API client (task 12)"
    },
    {
      "wave": 4,
      "parallel": true,
      "tasks": [5, 9, 14],
      "rationale": "Migration depends on models+endpoint finalization (tasks 1,4), scheduler job depends on quality detector (task 8), CostOverview depends on layout (task 13)"
    },
    {
      "wave": 5,
      "parallel": true,
      "tasks": [6, 10, 15, 16, 17, 18],
      "rationale": "Backend tests depend on endpoints+migration (tasks 4,5,6 deps), SDK coverage tests depend on SDK changes (task 7), remaining pages depend on layout (task 13)"
    },
    {
      "wave": 6,
      "parallel": true,
      "tasks": [19, 20],
      "rationale": "Dashboard tests depend on all pages (tasks 14-18), Docker Compose update depends on dashboard Dockerfile being ready (task 11+)"
    },
    {
      "wave": 7,
      "parallel": true,
      "tasks": [21, 22],
      "rationale": "Helm chart is independent of dashboard tests, CI jobs depend on both dashboard and helm being created"
    },
    {
      "wave": 8,
      "parallel": false,
      "tasks": [23, 24, 25],
      "rationale": "Documentation written after all features complete; README after docs; final validation after everything"
    }
  ],
  "dependencies": {
    "1": [],
    "2": [1],
    "3": [1],
    "4": [2, 3],
    "5": [1, 4],
    "6": [4, 5],
    "7": [],
    "8": [1],
    "9": [8],
    "10": [7],
    "11": [],
    "12": [11],
    "13": [12],
    "14": [13],
    "15": [13],
    "16": [13],
    "17": [13],
    "18": [13],
    "19": [14, 15, 16, 17, 18],
    "20": [11, 19],
    "21": [20],
    "22": [19, 21],
    "23": [6, 10, 19, 21],
    "24": [23],
    "25": [22, 23, 24]
  }
}
```

---

## Notes

**Strict constraints on existing files:**
- `sdk/python/axon/models.py` — add `batch_eligible: bool = False` field ONLY
- `sdk/python/axon/core/instrumentor.py` — add `batch_eligible: bool | None = None` parameter ONLY
- `backend/axon_backend/workers/scheduler.py` — add `_run_quality_check` function and one `add_job` call ONLY
- `deploy/docker-compose.yml` — add `axon-dashboard` service ONLY
- `deploy/.env.example` — add two dashboard env vars ONLY
- `.github/workflows/ci.yml` — add two new jobs ONLY
- `README.md` — update roadmap section and quickstart ONLY

**Files that must NOT be modified:**
- `sdk/python/axon/router/`, `sdk/python/axon/tracer/`, `sdk/python/axon/advisor/` (Phase 3 SDK)
- Any existing backend model, service, or API file from Phases 1–3
- `sdk/typescript/` (Phase 3 TypeScript SDK)
- `dashboards/grafana/` (Phase 2 Grafana dashboards)

**Test isolation:** Dashboard tests use `jsdom` environment via Vitest. Backend integration tests
use an in-memory or test PostgreSQL database. The `respx` library is used for all HTTP mocking
in SDK tests — never mock the module under test directly.

**Monetary values:** All USD cost values in the dashboard are passed as strings from the backend
and displayed with `formatCost()`. No floating-point arithmetic is performed on cost values in
the React frontend.

**mypy strictness:** Tasks 1–10 must all pass `mypy --strict` on their respective packages
before proceeding to task 25. The `batch_eligible` field addition must not introduce `Any`
in the instrumentor pipeline.
