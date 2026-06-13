# Axon — Phase 4 Kickoff Prompt
# Custom React Dashboard · Kubernetes · Enterprise Features
# ─────────────────────────────────────────────────────────────────

You are continuing work on the Axon project as the sole senior
engineer. Phases 1, 2, and 3 are complete and validated:

Phase 1: Python SDK — 466 tests passing (cumulative), 85.38%
coverage, mypy --strict clean across 38 source files.

Phase 2: Backend — FastAPI + PostgreSQL + Redis + Grafana,
Docker Compose validated, all endpoints passing.

Phase 3: Router, TypeScript SDK, cascade tracer, prompt cache
advisor — 466 Python tests, 23 TypeScript tests, all clean.

Do not modify any Phase 1, 2, or 3 code unless a Phase 4
requirement explicitly demands it. All existing tests must
continue passing throughout Phase 4.

Read this entire prompt before writing a single line of code.
State assumptions explicitly before proceeding.

─────────────────────────────────────────────────────────────────
PHASE 4 SCOPE
─────────────────────────────────────────────────────────────────

Phase 4 makes Axon production-ready and enterprise-adoptable.

  1. Custom React dashboard (replaces Grafana for cloud users)
  2. Kubernetes deployment (Helm chart)
  3. Enterprise auth (API key management, RBAC, audit log)
  4. Quality regression detector (offline batch, sampled)
  5. Batch eligibility tagger (metadata only)
  6. Coverage improvements for Phase 3 gaps

Out of scope for Phase 4:
  - ML-based routing (Phase 5)
  - Conformal prediction guarantees (Phase 5)
  - Managed SaaS (Phase 5)
  - Plugin system (Phase 5)

─────────────────────────────────────────────────────────────────
REPOSITORY ADDITIONS
─────────────────────────────────────────────────────────────────

axon/
├── dashboard/                   ← NEW
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/
│   │   │   ├── client.ts
│   │   │   └── types.ts
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   ├── Header.tsx
│   │   │   │   └── Layout.tsx
│   │   │   └── ui/
│   │   │       ├── StatCard.tsx
│   │   │       ├── CostChart.tsx
│   │   │       ├── CompressionChart.tsx
│   │   │       ├── BudgetGauge.tsx
│   │   │       ├── RouterDecisionTable.tsx
│   │   │       └── SpanTable.tsx
│   │   ├── pages/
│   │   │   ├── CostOverview.tsx
│   │   │   ├── CompressionROI.tsx
│   │   │   ├── BudgetManager.tsx
│   │   │   ├── RouterAnalytics.tsx
│   │   │   └── SpanExplorer.tsx
│   │   ├── hooks/
│   │   │   ├── useAttribution.ts
│   │   │   ├── useBudgets.ts
│   │   │   └── useSpans.ts
│   │   └── lib/
│   │       ├── formatters.ts
│   │       └── constants.ts
│   ├── public/
│   │   └── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── index.html
├── deploy/
│   ├── docker-compose.yml       ← UPDATE: add dashboard service
│   ├── .env.example             ← UPDATE: add dashboard vars
│   └── kubernetes/              ← NEW
│       ├── helm/
│       │   └── axon/
│       │       ├── Chart.yaml
│       │       ├── values.yaml
│       │       └── templates/
│       │           ├── deployment-backend.yaml
│       │           ├── deployment-dashboard.yaml
│       │           ├── service-backend.yaml
│       │           ├── service-dashboard.yaml
│       │           ├── configmap.yaml
│       │           ├── secret.yaml
│       │           ├── ingress.yaml
│       │           ├── pvc-postgres.yaml
│       │           └── pvc-redis.yaml
│       └── README.md
└── backend/
    └── axon_backend/
        ├── api/v1/
        │   ├── auth.py          ← NEW: API key management
        │   └── audit.py         ← NEW: audit log endpoints
        ├── models/
        │   ├── api_key.py       ← NEW
        │   └── audit_log.py     ← NEW
        └── services/
            ├── auth_service.py  ← NEW
            ├── audit_service.py ← NEW
            └── quality_detector.py ← NEW

─────────────────────────────────────────────────────────────────
FEATURE 1: CUSTOM REACT DASHBOARD
─────────────────────────────────────────────────────────────────

A purpose-built React SPA that replaces Grafana for users who
want a polished UI without running a separate Grafana instance.
Grafana remains available for self-hosted power users.

Tech stack:
  - React 18 + TypeScript + Vite
  - Recharts for all charts
  - Tailwind CSS (utility classes only, no custom CSS files)
  - React Query (TanStack Query v5) for server state
  - React Router v6 for navigation
  - Zustand for minimal global state (API key, time range)

── dashboard/src/api/client.ts ─────────────────────────────────

All API calls go through a single typed client.
Base URL and API key read from environment variables:
  VITE_AXON_BACKEND_URL (default: http://localhost:8000)
  VITE_AXON_API_KEY

class AxonAPIClient:
  async getAttribution(params): Promise<AttributionResponse>
  async getBudgets(): Promise<BudgetStatus[]>
  async getBudget(featureTag: string): Promise<BudgetStatus>
  async upsertBudget(featureTag, payload): Promise<BudgetStatus>
  async deleteBudget(featureTag): Promise<void>
  async getSpans(params): Promise<InferenceSpan[]>
  async getCacheStats(featureTag?): Promise<CacheStats>
  async getHealth(): Promise<HealthStatus>

All methods throw AxonAPIError with status and message on
non-2xx responses. Never return undefined — throw on error.

── dashboard/src/pages/ ────────────────────────────────────────

CostOverview.tsx:
  - Time range selector: 24h, 7d, 30d (top right)
  - Stat cards: total cost, total tokens, cache hit rate,
    tokens saved by compression (4 cards, top row)
  - Cost over time: line chart, grouped by feature_tag
  - Cost by model: bar chart
  - Cost by provider: donut chart
  - Top 10 feature tags by cost: sortable table
  Auto-refreshes every 60 seconds.

CompressionROI.tsx:
  - Stat cards: total tokens saved, total cost saved,
    average compression ratio, shadow vs live mode split
  - Tokens saved over time: area chart
  - Compression ratio by feature_tag: horizontal bar chart
  - Cache hit rate over time: line chart
  - Cost saved by semantic cache (cumulative): stat card

BudgetManager.tsx:
  - Budget list: table with feature_tag, budget_usd, period,
    spent_usd, remaining_usd, pct_used, status badge
  - Status badge: green (ok), yellow (warning), red (exhausted)
  - Add/edit budget: inline form (no modal)
  - Delete budget: confirmation inline
  - Budget gauges: one gauge per feature_tag showing pct_used

RouterAnalytics.tsx:
  - Routing decisions table: timestamp, original model,
    selected model, task type, complexity tier, cost delta %
  - Model distribution: donut chart (what % went to each tier)
  - Cost savings from routing: stat card (cumulative)
  - Task type breakdown: bar chart

SpanExplorer.tsx:
  - Filterable table of recent spans
  - Filters: feature_tag, model, provider, environment,
    date range, compression_applied (bool)
  - Columns: timestamp, model, input_tokens, output_tokens,
    cost_usd, feature_tag, compression_applied, cache_hit
  - Pagination: 50 rows per page
  - Click row to expand: shows prompt_hash, artifact_type,
    routing_decision, tokens_saved

── dashboard design constraints ────────────────────────────────

Color palette (Tailwind):
  Primary background:  bg-gray-950
  Secondary background: bg-gray-900
  Card background:     bg-gray-800
  Border:              border-gray-700
  Primary text:        text-gray-100
  Secondary text:      text-gray-400
  Accent (teal):       text-teal-400, bg-teal-500
  Success:             text-green-400
  Warning:             text-yellow-400
  Error:               text-red-400

Charts use teal-400 as primary series color.
All numbers formatted: tokens with comma separators,
costs with 6 decimal places for small values.
No rounded corners larger than rounded-lg.
No gradients except on stat card accent borders.

── dashboard/package.json ──────────────────────────────────────

{
  "name": "@axon-sdk/dashboard",
  "version": "0.4.0",
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.23.0",
    "@tanstack/react-query": "^5.40.0",
    "recharts": "^2.12.0",
    "zustand": "^4.5.0",
    "clsx": "^2.1.0"
  },
  "devDependencies": {
    "typescript": "^5.4.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "vite": "^5.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "tailwindcss": "^3.4.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "@vitejs/plugin-react": "^4.3.0",
    "vitest": "^1.6.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.0",
    "jsdom": "^24.0.0"
  }
}

── Docker Compose update ───────────────────────────────────────

Add to deploy/docker-compose.yml:

  axon-dashboard:
    build:
      context: ../dashboard
      dockerfile: Dockerfile
    environment:
      VITE_AXON_BACKEND_URL: http://axon-backend:8000
      VITE_AXON_API_KEY: ${AXON_API_KEY:-dev-key-change-in-production}
    depends_on:
      axon-backend:
        condition: service_healthy
    ports:
      - "5173:80"

Create dashboard/Dockerfile:
  FROM node:20-alpine AS builder
  WORKDIR /app
  COPY package.json .
  RUN npm install
  COPY . .
  RUN npm run build

  FROM nginx:alpine
  COPY --from=builder /app/dist /usr/share/nginx/html
  COPY nginx.conf /etc/nginx/conf.d/default.conf
  EXPOSE 80

Create dashboard/nginx.conf:
  server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    location / {
      try_files $uri $uri/ /index.html;
    }
    location /api {
      return 404;
    }
  }

─────────────────────────────────────────────────────────────────
FEATURE 2: ENTERPRISE AUTH
─────────────────────────────────────────────────────────────────

Adds proper API key management and RBAC to the backend.
Currently the backend uses a single shared API key from env vars.
Phase 4 adds a database-backed key management system.

── backend/axon_backend/models/api_key.py ──────────────────────

class APIKeyRecord(Base):
    id: UUID (PK)
    name: str               # human label: "production", "staging"
    key_hash: str           # bcrypt hash of the key
    key_prefix: str         # first 8 chars for identification
    role: str               # "admin" | "engineer" | "viewer"
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked: bool (default False)
    created_by: str         # key prefix of creator

Roles:
  admin   — full access including key management
  engineer — read/write spans, budgets, cache
  viewer  — read-only access to all endpoints

── backend/axon_backend/models/audit_log.py ────────────────────

class AuditLogRecord(Base):
    id: UUID (PK)
    timestamp: datetime (indexed)
    actor_key_prefix: str
    action: str           # "span.ingest" | "budget.upsert" | ...
    resource: str         # feature_tag or "*"
    result: str           # "success" | "denied" | "error"
    ip_address: str
    details: str | None   # JSON string of relevant params

Append-only. No UPDATE or DELETE on this table ever.

── backend/axon_backend/services/auth_service.py ───────────────

def generate_api_key() -> tuple[str, str]:
    """Generate a new API key. Returns (raw_key, key_hash).
    Raw key format: axon_live_{32 random hex chars}
    Never store raw_key — hash it immediately."""

def verify_api_key(raw_key: str, db_session) -> APIKeyRecord | None:
    """Verify a raw API key against stored hashes.
    Returns the APIKeyRecord if valid and not revoked,
    None otherwise. Updates last_used_at on success."""

def require_role(minimum_role: str):
    """FastAPI dependency that enforces minimum role.
    Roles in ascending order: viewer < engineer < admin"""

── backend/axon_backend/api/v1/auth.py ─────────────────────────

POST /v1/auth/keys
  Requires: admin role
  Body: { name: str, role: str, expires_in_days: int | None }
  Response: { key: str (raw, shown ONCE), prefix: str, role: str }

GET /v1/auth/keys
  Requires: admin role
  Response: list[{ prefix, name, role, created_at,
                   last_used_at, expires_at, revoked }]
  Never returns key hashes or raw keys.

DELETE /v1/auth/keys/{prefix}
  Requires: admin role
  Sets revoked=True. Does not delete the record.
  Response: 204

── backend/axon_backend/api/v1/audit.py ────────────────────────

GET /v1/audit
  Requires: admin role
  Query params: from_ts, to_ts, actor_prefix, action, limit
  Response: list[AuditLogRecord]
  Default limit: 100, max: 1000

─────────────────────────────────────────────────────────────────
FEATURE 3: QUALITY REGRESSION DETECTOR
─────────────────────────────────────────────────────────────────

Detects if output quality degrades after routing to a cheaper
model or applying compression. Runs offline/batch, never
synchronous on the inference path.

── backend/axon_backend/services/quality_detector.py ───────────

class QualityDetector:
    """
    Samples spans from the last 24 hours where routing changed
    the model (original_model != selected_model) and scores
    output quality using a lightweight LLM judge.

    Runs as a daily background job via APScheduler.
    Never runs synchronously on the inference path.
    """

    async def run_daily_check(
        self,
        db: AsyncSession,
        sample_size: int = 50,
    ) -> QualityReport:
        """
        1. Sample up to sample_size spans from last 24h where
           routing was applied (routing_decision is not null)
        2. For each span, score output quality on a 1-5 scale
           using the smallest available model (gpt-4o-mini or
           claude-haiku) as judge
        3. Compare average quality score: routed vs non-routed
        4. If routed quality < non-routed quality - threshold,
           emit a warning log and record the regression
        5. Return QualityReport
        """

@dataclass
class QualityReport:
    date: datetime
    spans_sampled: int
    routed_avg_quality: float
    baseline_avg_quality: float
    regression_detected: bool
    regression_threshold: float  # default 0.3
    details: list[dict]

Add to APScheduler in axon_backend/workers/scheduler.py:
  quality_check — runs daily at 03:00
  Calls QualityDetector.run_daily_check()
  Logs results with structlog
  Does not raise — logs errors and continues

─────────────────────────────────────────────────────────────────
FEATURE 4: BATCH ELIGIBILITY TAGGER
─────────────────────────────────────────────────────────────────

Tags inference calls that are latency-insensitive and could
be routed to batch APIs for 50% cost reduction.
Phase 4 tags only — actual batch routing is Phase 5.

Add to axon/core/instrumentor.py:

The instrument() and patch() functions gain a new parameter:
  batch_eligible: bool | None = None

If batch_eligible=True, the InferenceSpan gets a new field:
  batch_eligible: bool = True

Heuristic auto-detection (when batch_eligible=None):
  Check environment variable AXON_BATCH_ELIGIBLE_FEATURES.
  If feature_tag is in this comma-separated list → True.
  Otherwise → False.

This is metadata only. No actual batch routing.
Add batch_eligible to InferenceSpan model and backend schema.

─────────────────────────────────────────────────────────────────
FEATURE 5: PHASE 3 COVERAGE IMPROVEMENTS
─────────────────────────────────────────────────────────────────

The following modules need additional test coverage:

backend_client.py (currently 0%):
  These require a mock backend server. Use respx to mock
  HTTP calls. Test: send_span fires-and-forgets, check_budget
  returns OK on backend error (fail open).

cache/semantic_cache.py (currently 0%):
  Mock the BackendClient. Test: lookup returns None on miss,
  store fires-and-forgets, both fail open on any error.

axon/tracer/cascade_tracer.py (currently 65%):
  Add tests for get_cascade_cost with mock backend client.
  Test: returns CascadeCostSummary with correct totals,
  returns empty summary on backend error.

Target: bring overall coverage back above 85%.

─────────────────────────────────────────────────────────────────
KUBERNETES / HELM SPECIFICATION
─────────────────────────────────────────────────────────────────

deploy/kubernetes/helm/axon/Chart.yaml:
  apiVersion: v2
  name: axon
  description: Axon AI inference optimization platform
  version: 0.4.0
  appVersion: "0.4.0"

deploy/kubernetes/helm/axon/values.yaml:
  backend:
    replicaCount: 2
    image: ghcr.io/aarohim24/axon-backend:latest
    resources:
      requests: { cpu: 250m, memory: 512Mi }
      limits:   { cpu: 500m, memory: 1Gi }
  dashboard:
    replicaCount: 1
    image: ghcr.io/aarohim24/axon-dashboard:latest
    resources:
      requests: { cpu: 100m, memory: 128Mi }
      limits:   { cpu: 200m, memory: 256Mi }
  postgres:
    enabled: true
    storageSize: 20Gi
  redis:
    enabled: true
    storageSize: 2Gi
  ingress:
    enabled: false
    host: ""

Templates must be valid Kubernetes YAML. Use named templates
for labels and selectors. Include readiness and liveness
probes on backend deployment (GET /health, threshold 3 fails).

deploy/kubernetes/README.md:
  Installation instructions, prerequisites (kubectl, helm 3),
  quick install command, values customization guide,
  upgrade procedure.

─────────────────────────────────────────────────────────────────
BACKEND MIGRATION
─────────────────────────────────────────────────────────────────

Add Alembic migration for Phase 4 schema changes:
  migrations/versions/0002_phase4_schema.py

New tables: api_keys, audit_log
New column: inference_spans.batch_eligible (boolean, default false)

─────────────────────────────────────────────────────────────────
TESTING REQUIREMENTS
─────────────────────────────────────────────────────────────────

Dashboard (Vitest + React Testing Library):
  tests/CostOverview.test.tsx
    - Renders stat cards with mocked API data
    - Time range selector updates query params
    - Loading state shown while fetching

  tests/BudgetManager.test.tsx
    - Budget list renders correctly
    - Add budget form submits correctly
    - Status badge shows correct color per status

  tests/formatters.test.ts
    - Token formatter adds comma separators
    - Cost formatter shows correct decimal places
    - Percentage formatter rounds correctly

Backend (additions):
  tests/unit/test_auth_service.py
    - generate_api_key produces correct format
    - verify_api_key returns None for revoked key
    - verify_api_key returns None for expired key
    - Role ordering: viewer < engineer < admin

  tests/unit/test_audit_service.py
    - Audit log entry created on each mutation
    - append-only: no update or delete methods exist

  tests/integration/test_auth_api.py
    - POST /v1/auth/keys requires admin role
    - GET /v1/auth/keys returns no raw keys
    - DELETE /v1/auth/keys/{prefix} revokes correctly
    - 401 on missing key, 403 on insufficient role

Phase 1/2/3 regression:
  pytest sdk/python/tests --cov=axon --cov-fail-under=85
  Must pass before Phase 4 is considered complete.
  Note: threshold raised from 80% to 85% for Phase 4.

─────────────────────────────────────────────────────────────────
CI ADDITIONS
─────────────────────────────────────────────────────────────────

Add to .github/workflows/ci.yml:

dashboard-test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/setup-node@v4
      with: { node-version: '20' }
    - cd dashboard
    - npm install
    - npm run typecheck
    - npm test -- --coverage

helm-lint:
  runs-on: ubuntu-latest
  steps:
    - uses: azure/setup-helm@v3
    - helm lint deploy/kubernetes/helm/axon

─────────────────────────────────────────────────────────────────
DOCUMENTATION UPDATES
─────────────────────────────────────────────────────────────────

docs/dashboard-guide.md (NEW):
  - What the dashboard provides vs Grafana
  - Running the dashboard (Docker Compose and standalone)
  - Each page explained with expected data
  - Configuration (backend URL, API key)

docs/enterprise-auth.md (NEW):
  - API key management workflow
  - Role descriptions and permissions
  - Key rotation procedure
  - Audit log access and interpretation

docs/kubernetes-deployment.md (NEW):
  - Prerequisites
  - Helm install with default values
  - Production values customization
  - Upgrade procedure
  - Resource requirements

README.md update:
  - Add dashboard screenshot placeholder
  - Update Docker Compose quickstart to mention
    dashboard at localhost:5173
  - Update roadmap: Phase 4 in progress

─────────────────────────────────────────────────────────────────
COMMIT SEQUENCE
─────────────────────────────────────────────────────────────────

01  feat(backend): add api_key and audit_log models
02  feat(backend): implement auth service (keygen, verify, rbac)
03  feat(backend): implement audit service (append-only log)
04  feat(backend): add auth and audit API endpoints
05  feat(backend): add Alembic migration 0002 (api_keys,
    audit_log, batch_eligible column)
06  test(backend): add auth service and API tests
07  feat(sdk): add batch eligibility tagger to instrumentor
08  feat(backend): add quality regression detector service
09  feat(backend): add quality check APScheduler job
10  test(sdk): add coverage for backend_client,
    semantic_cache, cascade_tracer
11  feat(dashboard): initialize React + Vite + Tailwind project
12  feat(dashboard): implement API client with typed methods
13  feat(dashboard): implement layout (sidebar, header)
14  feat(dashboard): implement CostOverview page
15  feat(dashboard): implement CompressionROI page
16  feat(dashboard): implement BudgetManager page
17  feat(dashboard): implement RouterAnalytics page
18  feat(dashboard): implement SpanExplorer page
19  test(dashboard): add Vitest tests for pages and formatters
20  feat(deploy): add dashboard service to Docker Compose
21  feat(deploy): add Kubernetes Helm chart
22  ci: add dashboard-test and helm-lint jobs
23  docs: add dashboard guide, enterprise auth, k8s deployment
24  docs: update README — Phase 4 in progress
25  chore: Phase 4 complete — all checks passing

─────────────────────────────────────────────────────────────────
VALIDATION CHECKLIST
─────────────────────────────────────────────────────────────────

[ ] mypy sdk/python/axon --strict → 0 errors
[ ] mypy backend/axon_backend --strict → 0 errors
[ ] ruff check sdk/python/axon sdk/python/tests → clean
[ ] pytest sdk/python/tests --cov=axon --cov-fail-under=85
    → passes (raised from 80% in Phase 4)
[ ] pytest backend/tests --cov=axon_backend
    --cov-fail-under=75 → passes
[ ] cd dashboard && npm run typecheck → 0 errors
[ ] cd dashboard && npm test -- --coverage → passes
[ ] cd sdk/typescript && npm run typecheck → 0 errors
[ ] cd sdk/typescript && npm test → 23 passed (regression)
[ ] helm lint deploy/kubernetes/helm/axon → no errors
[ ] docker compose -f deploy/docker-compose.yml up -d
    → 5 services healthy (postgres, redis, backend,
      grafana, dashboard)
[ ] curl http://localhost:8000/health → {"status":"ok","version":"0.4.0"}
[ ] Dashboard accessible at http://localhost:5173
[ ] POST /v1/auth/keys with viewer key → 403
[ ] POST /v1/auth/keys with admin key → 201 with raw key
[ ] GET /v1/audit → returns log entries
[ ] git log --oneline → 25 new commits since Phase 3