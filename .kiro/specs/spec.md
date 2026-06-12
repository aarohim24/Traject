# Axon — Phase 2 Kickoff Prompt
# Backend Service, Semantic Cache, Cost Attribution, Grafana
# ─────────────────────────────────────────────────────────────────

You are continuing work on the Axon project as the sole senior
engineer. Phase 1 (Python SDK) is complete and validated:
336 tests passing, 94% coverage, mypy --strict clean, all
benchmarks passing. Do not modify any Phase 1 SDK code unless
a Phase 2 requirement explicitly demands it.

Read this entire prompt before writing a single line of code.
State any assumptions explicitly before proceeding.

─────────────────────────────────────────────────────────────────
PHASE 2 SCOPE
─────────────────────────────────────────────────────────────────

Phase 2 introduces the backend service and makes Axon a complete
self-hosted platform. The deliverables are:

  1. FastAPI backend service (span ingestion, cost attribution,
     budget controls, cache coordination)
  2. PostgreSQL 16 + pgvector schema with Alembic migrations
  3. Redis 7 integration (hot semantic cache, budget counters)
  4. Semantic caching layer (SDK + backend integration)
  5. Feature-level cost attribution (aggregation pipeline)
  6. Budget controls with webhook alerting
  7. Docker Compose self-hosted deployment (one-command startup)
  8. Grafana dashboard templates (3 provisioned dashboards)
  9. SDK backend client (sends spans to backend)
  10. Live compression mode documentation and example

Out of scope for Phase 2:
  - TypeScript SDK (Phase 3)
  - Model router (Phase 3)
  - Multi-agent cascade tracer (Phase 3)
  - Custom React dashboard (Phase 4)
  - Cloud/Kubernetes deployment (Phase 4)
  - Enterprise SSO/RBAC (Phase 4)

─────────────────────────────────────────────────────────────────
REPOSITORY ADDITIONS
─────────────────────────────────────────────────────────────────

Add the following structure to the existing repo.
Do not touch anything under sdk/python/ except where
explicitly instructed.

axon/
├── backend/
│   ├── axon_backend/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── router.py
│   │   │       ├── spans.py
│   │   │       ├── attribution.py
│   │   │       ├── budgets.py
│   │   │       └── cache.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── span.py
│   │   │   ├── attribution.py
│   │   │   ├── budget.py
│   │   │   └── cache_entry.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── span_ingestion.py
│   │   │   ├── cost_attribution.py
│   │   │   ├── budget_enforcer.py
│   │   │   └── semantic_cache.py
│   │   ├── workers/
│   │   │   ├── __init__.py
│   │   │   └── scheduler.py
│   │   └── core/
│   │       ├── __init__.py
│   │       ├── config.py
│   │       ├── database.py
│   │       └── redis_client.py
│   ├── migrations/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 0001_initial_schema.py
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── unit/
│   │   │   ├── __init__.py
│   │   │   ├── test_span_ingestion.py
│   │   │   ├── test_cost_attribution.py
│   │   │   ├── test_budget_enforcer.py
│   │   │   └── test_semantic_cache.py
│   │   └── integration/
│   │       ├── __init__.py
│   │       ├── test_spans_api.py
│   │       ├── test_attribution_api.py
│   │       └── test_budgets_api.py
│   ├── alembic.ini
│   └── pyproject.toml
├── dashboards/
│   └── grafana/
│       ├── provisioning/
│       │   ├── dashboards/
│       │   │   └── dashboards.yml
│       │   └── datasources/
│       │       └── datasource.yml
│       └── dashboards/
│           ├── cost-overview.json
│           ├── compression-roi.json
│           └── budget-burn-rate.json
├── deploy/
│   ├── docker-compose.yml
│   └── .env.example
└── sdk/
    └── python/
        └── axon/
            ├── backend_client.py    ← NEW
            └── cache/
                ├── __init__.py      ← NEW
                └── semantic_cache.py ← NEW

─────────────────────────────────────────────────────────────────
BACKEND SERVICE SPECIFICATION
─────────────────────────────────────────────────────────────────

── axon_backend/core/config.py ─────────────────────────────────

Use pydantic-settings. All values read from environment variables
with sensible defaults for local development.

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://axon:axon@localhost:5432/axon"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl_seconds: int = 86400  # 24 hours

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 2
    cors_origins: list[str] = ["http://localhost:3000"]

    # Security
    api_key_header: str = "X-Axon-API-Key"
    api_key: str = "dev-key-change-in-production"

    # Semantic cache
    cache_similarity_threshold: float = 0.92
    cache_max_entries: int = 100_000

    # Budget alerts
    budget_alert_webhook_timeout_seconds: int = 10

    model_config = SettingsConfig(env_file=".env", extra="ignore")

── axon_backend/core/database.py ───────────────────────────────

Async SQLAlchemy 2.0 setup.
- create_async_engine with pool configuration from Settings
- AsyncSessionLocal factory
- get_db() async dependency for FastAPI
- init_db() coroutine that creates all tables (used in lifespan)

── axon_backend/core/redis_client.py ───────────────────────────

- get_redis() returns a connected redis.asyncio.Redis client
- Singleton pattern: one connection pool per process
- Health check: ping() on startup
- All Redis keys namespaced: "axon:{key_type}:{identifier}"

── axon_backend/models/ ────────────────────────────────────────

All SQLAlchemy 2.0 mapped_column syntax. No legacy Column.

span.py — InferenceSpanRecord
  id: UUID (PK, server default gen_random_uuid())
  trace_id: str (indexed)
  parent_span_id: str | None
  span_name: str
  timestamp: datetime (indexed)
  duration_ms: int
  provider: str (indexed)
  model: str (indexed)
  input_tokens: int
  output_tokens: int
  cached_tokens: int
  token_count_method: str
  cost_usd: Numeric(12, 8) | None
  feature_tag: str (indexed)
  prompt_hash: str
  artifact_type: str
  compression_applied: bool
  shadow_mode: bool
  pre_compression_tokens: int | None
  tokens_saved: int | None
  cache_hit: bool
  environment: str (indexed)
  created_at: datetime (server default now())

  Index: (feature_tag, timestamp) composite
  Index: (environment, timestamp) composite

attribution.py — CostAttributionRecord
  Materialized hourly from inference_spans.
  id: UUID (PK)
  feature_tag: str
  hour_bucket: datetime (indexed)
  provider: str
  model: str
  total_input_tokens: int
  total_output_tokens: int
  total_cached_tokens: int
  total_cost_usd: Numeric(12, 8)
  total_tokens_saved: int
  cost_saved_compression_usd: Numeric(12, 8)
  cost_saved_cache_usd: Numeric(12, 8)
  call_count: int
  cache_hit_count: int
  p50_latency_ms: int
  p95_latency_ms: int
  created_at: datetime

  UniqueConstraint: (feature_tag, hour_bucket, provider, model)

budget.py — BudgetControlRecord
  id: UUID (PK)
  feature_tag: str (unique)
  period: str  # "daily" | "weekly" | "monthly"
  budget_usd: Numeric(10, 4)
  alert_threshold_pct: float  # 0.8 = alert at 80%
  hard_stop: bool  # block calls when exhausted
  alert_webhook_url: str | None
  created_at: datetime
  updated_at: datetime

cache_entry.py — CacheEntryRecord
  id: UUID (PK)
  prompt_hash: str (unique, indexed)
  embedding: Vector(384)  # pgvector column
  response_preview: str   # first 200 chars only
  model: str
  feature_tag: str (indexed)
  similarity_threshold: float
  created_at: datetime
  expires_at: datetime | None (indexed)
  last_hit_at: datetime
  hit_count: int
  cost_saved_usd: Numeric(10, 6)

── axon_backend/api/v1/ ────────────────────────────────────────

All routes require X-Axon-API-Key header authentication.
Return 401 if missing or invalid.
All request/response bodies are Pydantic v2 models.
All endpoints return appropriate HTTP status codes.

spans.py
  POST /v1/spans
    Body: SpanIngestRequest (list of InferenceSpanPayload)
    Max batch size: 1000 spans
    Response: SpanIngestResponse { accepted: int, rejected: int }
    Validation: reject spans with future timestamps (> 60s ahead)
    On success: persist to DB, check budgets, return 202

  GET /v1/spans
    Query params: feature_tag, from_ts, to_ts, limit (max 1000)
    Response: list[InferenceSpanPayload]

attribution.py
  GET /v1/attribution
    Query params: feature_tag (optional), from_ts, to_ts,
                  group_by (model|provider|feature_tag)
    Response: AttributionResponse
      { total_cost_usd, total_tokens, total_savings_usd,
        breakdown: list[AttributionRow] }

  GET /v1/attribution/summary
    Query params: period (daily|weekly|monthly)
    Response: top 10 feature_tags by cost, with trend

budgets.py
  PUT /v1/budgets/{feature_tag}
    Body: BudgetControlPayload
    Response: BudgetControlRecord
    Creates or updates (upsert)

  GET /v1/budgets/{feature_tag}
    Response: BudgetStatusResponse
      { budget, period, spent_usd, remaining_usd,
        pct_used, status: "ok"|"warning"|"exhausted" }

  GET /v1/budgets
    Response: list[BudgetStatusResponse] for all feature_tags

  DELETE /v1/budgets/{feature_tag}
    Response: 204 No Content

cache.py
  POST /v1/cache/lookup
    Body: { prompt_hash: str, prompt_embedding: list[float] }
    Response: CacheLookupResponse
      { hit: bool, response_preview: str | None,
        similarity: float | None }
    Uses pgvector cosine similarity search

  POST /v1/cache/store
    Body: CacheStoreRequest
      { prompt_hash, prompt_embedding, response_preview,
        model, feature_tag, cost_usd }
    Response: 201 Created

  POST /v1/cache/invalidate
    Body: { feature_tag: str } | { prompt_hash: str }
    Response: { invalidated: int }

  GET /v1/cache/stats
    Query: feature_tag (optional)
    Response: { hit_count, miss_count, hit_rate,
                total_cost_saved_usd, entry_count }

── axon_backend/services/ ──────────────────────────────────────

span_ingestion.py
  async def ingest_spans(
      spans: list[InferenceSpanPayload],
      db: AsyncSession,
      redis: Redis,
  ) -> SpanIngestResponse:
    - Bulk insert using SQLAlchemy insert()
    - After insert: check each feature_tag against budget
    - If budget exceeded: fire webhook (non-blocking, background task)
    - Return accepted/rejected counts

cost_attribution.py
  async def materialize_hourly(
      db: AsyncSession,
      hour: datetime,
  ) -> int:
    - Aggregate inference_spans for the given hour
    - Upsert into cost_attribution
    - Returns rows upserted

  async def get_attribution(
      db: AsyncSession,
      feature_tag: str | None,
      from_ts: datetime,
      to_ts: datetime,
      group_by: str,
  ) -> AttributionResponse:

budget_enforcer.py
  async def check_budget(
      feature_tag: str,
      db: AsyncSession,
      redis: Redis,
  ) -> BudgetStatus:
    - Read current spend from Redis counter (fast path)
    - If counter missing, compute from DB and cache in Redis
    - Compare against budget threshold
    - Returns BudgetStatus enum: OK | WARNING | EXHAUSTED

  async def fire_webhook(
      webhook_url: str,
      payload: BudgetAlertPayload,
  ) -> None:
    - POST to webhook_url with timeout=10s
    - Log success or failure; never raise
    - Payload: { feature_tag, budget_usd, spent_usd,
                 pct_used, status, timestamp }

semantic_cache.py
  async def lookup(
      prompt_hash: str,
      embedding: list[float],
      db: AsyncSession,
      threshold: float,
  ) -> CacheLookupResponse:
    - Exact hash lookup first (fast path)
    - If miss: pgvector cosine similarity search
      SELECT * FROM cache_entries
      ORDER BY embedding <=> :query_embedding
      LIMIT 1
    - Return hit if similarity >= threshold

  async def store(
      request: CacheStoreRequest,
      db: AsyncSession,
  ) -> None:
    - Insert CacheEntryRecord
    - On conflict (prompt_hash): update hit_count + last_hit_at

── axon_backend/workers/scheduler.py ───────────────────────────

APScheduler AsyncIOScheduler.

Jobs:
  materialize_attribution — runs every hour at :05
    Calls cost_attribution.materialize_hourly() for the
    previous complete hour.

  expire_cache_entries — runs daily at 02:00
    DELETE FROM cache_entries WHERE expires_at < now()

  recompute_budget_counters — runs every 15 minutes
    Recompute Redis budget counters from DB for all
    active feature_tags. Prevents counter drift.

── axon_backend/main.py ────────────────────────────────────────

FastAPI app with lifespan context manager:
  - On startup: init_db(), ping Redis, start scheduler
  - On shutdown: stop scheduler, close DB pool, close Redis

Middleware:
  - CORSMiddleware (origins from Settings)
  - RequestLoggingMiddleware (structlog, log method + path +
    status + duration_ms)

Routes: include v1 router with prefix="/v1"

Health endpoints (no auth required):
  GET /health → { status: "ok", version: "0.2.0" }
  GET /health/db → checks DB connection
  GET /health/redis → checks Redis ping

─────────────────────────────────────────────────────────────────
SDK ADDITIONS (sdk/python/axon/)
─────────────────────────────────────────────────────────────────

── axon/backend_client.py ──────────────────────────────────────

Async HTTP client that sends InferenceSpan data to the backend.

class BackendClient:
    def __init__(self, base_url: str, api_key: str) -> None: ...

    async def send_span(self, span: InferenceSpan) -> None:
        """POST span to /v1/spans. Fire-and-forget.
        Never raises — log errors with structlog only.
        Timeout: 2 seconds. Do not block the inference path."""

    async def check_budget(self, feature_tag: str) -> BudgetStatus:
        """GET /v1/budgets/{feature_tag}.
        Returns BudgetStatus.OK on any error (fail open)."""

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient."""

Integration with instrumentor:
  Update axon/core/instrumentor.py configure() to accept:
    backend_url: str | None = None
    backend_api_key: str | None = None
  If backend_url is set, send spans to backend in addition
  to OTEL export. Both paths run independently.

── axon/cache/semantic_cache.py ────────────────────────────────

Client-side cache lookup that talks to the backend.

class SemanticCacheClient:
    def __init__(self, backend_client: BackendClient) -> None: ...

    async def lookup(
        self,
        messages: list[dict[str, Any]],
        model: str,
    ) -> CacheLookupResult | None:
        """Check cache before hitting the LLM provider.
        Computes embedding locally (all-MiniLM-L6-v2 singleton).
        Returns None on any error (fail open)."""

    async def store(
        self,
        messages: list[dict[str, Any]],
        response_text: str,
        model: str,
        feature_tag: str,
        cost_usd: Decimal,
    ) -> None:
        """Store response in cache after successful LLM call.
        Fire-and-forget. Never raises."""

─────────────────────────────────────────────────────────────────
DOCKER COMPOSE SPECIFICATION
─────────────────────────────────────────────────────────────────

deploy/docker-compose.yml must define these services:

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: axon
      POSTGRES_PASSWORD: axon
      POSTGRES_DB: axon
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U axon"]
      interval: 5s
      retries: 5
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
    ports:
      - "6379:6379"

  axon-backend:
    build:
      context: ../backend
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql+asyncpg://axon:axon@postgres:5432/axon
      REDIS_URL: redis://redis:6379/0
      API_KEY: ${AXON_API_KEY:-dev-key-change-in-production}
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      retries: 3

  grafana:
    image: grafana/grafana:10.4.0
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - ../dashboards/grafana/provisioning:/etc/grafana/provisioning
      - ../dashboards/grafana/dashboards:/var/lib/grafana/dashboards
      - grafana_data:/var/lib/grafana
    depends_on:
      - axon-backend
    ports:
      - "3000:3000"

volumes:
  postgres_data:
  redis_data:
  grafana_data:

Also create backend/Dockerfile:
  FROM python:3.11-slim
  WORKDIR /app
  COPY pyproject.toml .
  RUN pip install -e ".[prod]"
  COPY axon_backend/ axon_backend/
  COPY migrations/ migrations/
  COPY alembic.ini .
  CMD ["sh", "-c", "alembic upgrade head && uvicorn axon_backend.main:app --host 0.0.0.0 --port 8000 --workers 2"]

─────────────────────────────────────────────────────────────────
GRAFANA DASHBOARDS SPECIFICATION
─────────────────────────────────────────────────────────────────

Three provisioned dashboards. All use the Axon backend as a
JSON API datasource (not direct PostgreSQL connection —
query the /v1/attribution and /v1/budgets endpoints).

1. cost-overview.json
   - Total cost over time (time series, by feature_tag)
   - Cost by model (bar chart)
   - Cost by provider (pie chart)
   - Top 5 most expensive feature_tags (table)
   - Total tokens input vs output (stacked bar)

2. compression-roi.json
   - Tokens saved by compression over time (time series)
   - Cost saved by compression (stat panel, cumulative)
   - Compression ratio by feature_tag (table)
   - Cache hit rate over time (time series)
   - Cost saved by semantic cache (stat panel, cumulative)

3. budget-burn-rate.json
   - Budget utilization per feature_tag (gauge panels)
   - Burn rate: daily spend vs daily budget (time series)
   - Features approaching budget limit (table, sorted by pct_used)
   - Alert history (annotations)

─────────────────────────────────────────────────────────────────
backend/pyproject.toml SPECIFICATION
─────────────────────────────────────────────────────────────────

[project]
name = "axon-backend"
version = "0.2.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.29",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "pgvector>=0.2",
    "redis[hiredis]>=5.0",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "structlog>=24.1",
    "apscheduler>=3.10",
    "httpx>=0.27",
    "sentence-transformers>=3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "httpx>=0.27",
    "anyio>=4.0",
]
prod = []  # same as base for now

─────────────────────────────────────────────────────────────────
TESTING REQUIREMENTS
─────────────────────────────────────────────────────────────────

Backend tests use pytest-asyncio with anyio backend.
Integration tests use FastAPI's AsyncClient (httpx).
Database tests use a test database (separate from dev).
Redis tests use fakeredis for unit tests.

conftest.py must provide:
  - async_client fixture (FastAPI AsyncClient, test DB)
  - db_session fixture (isolated transaction per test, rolls back)
  - redis_mock fixture (fakeredis)
  - sample_span_payload() factory function
  - sample_spans_batch() factory (n=10 default)

Coverage target: 75% overall for backend.
  (Lower than SDK due to infrastructure code complexity.)

Key test invariants:
  - POST /v1/spans with 1000 spans returns 202
  - POST /v1/spans with future timestamp rejects that span
  - Budget at 100% with hard_stop=True returns exhausted status
  - Webhook fires when budget threshold crossed
  - Webhook failure (timeout/500) does not fail span ingestion
  - Cache exact hash lookup faster than vector search
  - Cache lookup returns None gracefully on DB error
  - /health returns 200 even if scheduler hasn't started
  - All endpoints return 401 without valid API key

─────────────────────────────────────────────────────────────────
CI ADDITIONS (.github/workflows/ci.yml)
─────────────────────────────────────────────────────────────────

Add a backend job to the existing CI workflow:

backend-test:
  runs-on: ubuntu-latest
  services:
    postgres:
      image: pgvector/pgvector:pg16
      env: { POSTGRES_USER: axon, POSTGRES_PASSWORD: axon,
             POSTGRES_DB: axon_test }
      ports: ["5432:5432"]
    redis:
      image: redis:7-alpine
      ports: ["6379:6379"]
  steps:
    - cd backend
    - pip install -e ".[dev]"
    - alembic upgrade head
    - pytest tests/ --cov=axon_backend --cov-fail-under=75

─────────────────────────────────────────────────────────────────
COMMIT SEQUENCE
─────────────────────────────────────────────────────────────────

01  chore(backend): initialize backend service structure
02  feat(backend): add Settings config with pydantic-settings
03  feat(backend): add async SQLAlchemy database setup
04  feat(backend): add Redis client with health check
05  feat(backend): define all SQLAlchemy models with migrations
06  feat(backend): implement span ingestion service
07  feat(backend): implement cost attribution aggregation
08  feat(backend): implement budget enforcer with webhook
09  feat(backend): implement semantic cache service
10  feat(backend): implement APScheduler background workers
11  feat(backend): implement spans API endpoints
12  feat(backend): implement attribution API endpoints
13  feat(backend): implement budgets API endpoints
14  feat(backend): implement cache API endpoints
15  feat(backend): add FastAPI app with lifespan and middleware
16  feat(backend): add backend Dockerfile
17  feat(deploy): add Docker Compose with all services
18  feat(dashboards): add Grafana provisioning and 3 dashboards
19  feat(sdk): add backend HTTP client (fire-and-forget spans)
20  feat(sdk): add semantic cache client
21  feat(sdk): update configure() to accept backend_url
22  test(backend): add unit tests for all services
23  test(backend): add integration tests for all API endpoints
24  ci: add backend test job to CI workflow
25  docs: update README with Docker Compose quickstart
26  chore: Phase 2 complete — backend validated, all checks passing

─────────────────────────────────────────────────────────────────
VALIDATION CHECKLIST
─────────────────────────────────────────────────────────────────

Run these after all 26 commits. All must pass.

[ ] cd backend && mypy axon_backend --strict → 0 errors
[ ] cd backend && ruff check axon_backend tests → clean
[ ] cd backend && pytest --cov=axon_backend
    --cov-fail-under=75 → passes
[ ] cd sdk/python && pytest --cov=axon --cov-fail-under=80
    → still passes (Phase 1 regression check)
[ ] docker compose -f deploy/docker-compose.yml up -d
    → all 4 services healthy within 60 seconds
[ ] curl http://localhost:8000/health → {"status":"ok"}
[ ] curl http://localhost:8000/health/db → {"status":"ok"}
[ ] curl http://localhost:8000/health/redis → {"status":"ok"}
[ ] Grafana accessible at http://localhost:3000
    → all 3 dashboards visible under Axon folder
[ ] POST /v1/spans with valid API key → 202
[ ] POST /v1/spans without API key → 401
[ ] GET /v1/attribution → returns valid response
[ ] PUT /v1/budgets/test → 200
[ ] GET /v1/budgets/test → includes spent_usd field
[ ] docker compose -f deploy/docker-compose.yml down -v
    → clean shutdown, no errors