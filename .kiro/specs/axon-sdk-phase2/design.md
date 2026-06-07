# Axon Phase 2 — Technical Design

## 1. Architecture Overview

Phase 2 transforms Axon from a local SDK-only tool into a self-hosted platform. The SDK (Phase 1) gains two additions — a backend HTTP client and a semantic cache client — while a new FastAPI backend service provides span ingestion, cost attribution, budget controls, semantic caching, and a Grafana observability layer.

```
┌─────────────────────────────────────────────────────────────────┐
│  Developer Application                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  axon.instrument() / axon.patch()                       │   │
│  │    ├── Phase 1: compress → classify → emit OTEL span    │   │
│  │    ├── NEW: BackendClient.send_span() (fire-and-forget) │   │
│  │    └── NEW: SemanticCacheClient.lookup() / .store()     │   │
│  └─────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬─────────────────────────────────┘
                                │ HTTP (httpx, async, 2s timeout)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  axon-backend  (FastAPI 0.111, Python 3.11)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  /v1/spans   │  │ /v1/attrib.  │  │  /v1/budgets         │  │
│  │  /v1/cache   │  │ /health/*    │  │  (CRUD + status)     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│  ┌──────▼─────────────────▼──────────────────────▼───────────┐  │
│  │  Services: SpanIngestion │ CostAttribution │ BudgetEnforcer│  │
│  │            SemanticCache │ APScheduler Workers             │  │
│  └──────┬─────────────────────────────────┬───────────────────┘  │
│         │ asyncpg                         │ redis.asyncio        │
│         ▼                                 ▼                      │
│  ┌─────────────────┐            ┌──────────────────┐            │
│  │  PostgreSQL 16   │            │  Redis 7          │            │
│  │  + pgvector      │            │  (hot cache,      │            │
│  │  (spans, attrib, │            │   budget counters)│            │
│  │   budgets,       │            └──────────────────┘            │
│  │   cache_entries) │                                            │
│  └─────────────────┘                                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Grafana 10.4  (3 provisioned dashboards via JSON API source)   │
└─────────────────────────────────────────────────────────────────┘
```

### 1.1 Design Principles

- **Fail open everywhere**: BackendClient never raises; budget checks default to OK on error; cache lookups return None on error. The inference path is never blocked by backend failures.
- **Fire-and-forget for telemetry**: `send_span()` uses a 2-second timeout and discards any error after logging. This adds < 1ms overhead to the instrumented call.
- **Async-first**: The backend uses `asyncpg` + SQLAlchemy 2.0 async throughout. No sync DB calls anywhere.
- **Redis as fast path**: Budget counters live in Redis (O(1) reads). DB is the source of truth but only hit on cache miss or periodic recompute.
- **Exact cost with Decimal**: All cost_usd values stored as `Numeric(12, 8)`. No float arithmetic in cost paths.

---

## 2. Directory Structure

```
axon/
├── backend/
│   ├── axon_backend/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI app, lifespan, middleware
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── router.py          # include_router aggregator
│   │   │       ├── spans.py           # POST /spans, GET /spans
│   │   │       ├── attribution.py     # GET /attribution, /attribution/summary
│   │   │       ├── budgets.py         # CRUD /budgets/{feature_tag}
│   │   │       └── cache.py           # /cache/lookup, /store, /invalidate, /stats
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                # DeclarativeBase
│   │   │   ├── span.py                # InferenceSpanRecord
│   │   │   ├── attribution.py         # CostAttributionRecord
│   │   │   ├── budget.py              # BudgetControlRecord
│   │   │   └── cache_entry.py         # CacheEntryRecord (pgvector)
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── span_ingestion.py
│   │   │   ├── cost_attribution.py
│   │   │   ├── budget_enforcer.py
│   │   │   └── semantic_cache.py
│   │   ├── workers/
│   │   │   ├── __init__.py
│   │   │   └── scheduler.py           # APScheduler AsyncIOScheduler
│   │   └── core/
│   │       ├── __init__.py
│   │       ├── config.py              # pydantic-settings Settings
│   │       ├── database.py            # async SQLAlchemy engine + session
│   │       └── redis_client.py        # redis.asyncio singleton
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
│   ├── Dockerfile
│   ├── alembic.ini
│   └── pyproject.toml
├── dashboards/
│   └── grafana/
│       ├── provisioning/
│       │   ├── dashboards/dashboards.yml
│       │   └── datasources/datasource.yml
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
            ├── backend_client.py      ← NEW
            └── cache/
                ├── __init__.py        ← NEW
                └── semantic_cache.py  ← NEW
```

---

## 3. Backend Service Design

### 3.1 Configuration (`axon_backend/core/config.py`)

Uses `pydantic-settings` with `BaseSettings`. All values read from environment variables with sensible local defaults.

```python
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
```

### 3.2 Database Setup (`axon_backend/core/database.py`)

- `create_async_engine` with pool configuration from Settings
- `AsyncSessionLocal` via `async_sessionmaker`
- `get_db()` async generator dependency for FastAPI route injection
- `init_db()` coroutine that runs `CREATE TABLE IF NOT EXISTS` for all models (used in lifespan)

### 3.3 Redis Client (`axon_backend/core/redis_client.py`)

- Module-level `_redis_pool: Redis | None = None` singleton
- `get_redis() -> Redis` — creates pool on first call, returns existing pool thereafter
- All keys namespaced: `"axon:{key_type}:{identifier}"`
  - Budget counters: `"axon:budget:{feature_tag}"`
  - Cache TTL keys: `"axon:cache:{prompt_hash}"`
- `ping_redis()` async function called on startup

### 3.4 Database Models

#### `InferenceSpanRecord` (`inference_spans` table)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK, `gen_random_uuid()` |
| trace_id | VARCHAR | indexed |
| parent_span_id | VARCHAR | nullable |
| span_name | VARCHAR | |
| timestamp | TIMESTAMPTZ | indexed |
| duration_ms | INTEGER | |
| provider | VARCHAR | indexed |
| model | VARCHAR | indexed |
| input_tokens | INTEGER | |
| output_tokens | INTEGER | |
| cached_tokens | INTEGER | |
| token_count_method | VARCHAR | |
| cost_usd | NUMERIC(12,8) | nullable |
| feature_tag | VARCHAR | indexed |
| prompt_hash | VARCHAR(64) | |
| artifact_type | VARCHAR | |
| compression_applied | BOOLEAN | |
| shadow_mode | BOOLEAN | |
| pre_compression_tokens | INTEGER | nullable |
| tokens_saved | INTEGER | nullable |
| cache_hit | BOOLEAN | |
| environment | VARCHAR | indexed |
| created_at | TIMESTAMPTZ | server default `now()` |

Composite indexes: `(feature_tag, timestamp)`, `(environment, timestamp)`

#### `CostAttributionRecord` (`cost_attribution` table)

Materialized hourly from spans. Unique constraint: `(feature_tag, hour_bucket, provider, model)`.

| Column | Type |
|--------|------|
| id | UUID PK |
| feature_tag | VARCHAR |
| hour_bucket | TIMESTAMPTZ indexed |
| provider | VARCHAR |
| model | VARCHAR |
| total_input_tokens | INTEGER |
| total_output_tokens | INTEGER |
| total_cached_tokens | INTEGER |
| total_cost_usd | NUMERIC(12,8) |
| total_tokens_saved | INTEGER |
| cost_saved_compression_usd | NUMERIC(12,8) |
| cost_saved_cache_usd | NUMERIC(12,8) |
| call_count | INTEGER |
| cache_hit_count | INTEGER |
| p50_latency_ms | INTEGER |
| p95_latency_ms | INTEGER |
| created_at | TIMESTAMPTZ |

#### `BudgetControlRecord` (`budget_controls` table)

| Column | Type |
|--------|------|
| id | UUID PK |
| feature_tag | VARCHAR unique |
| period | VARCHAR (`"daily"` \| `"weekly"` \| `"monthly"`) |
| budget_usd | NUMERIC(10,4) |
| alert_threshold_pct | FLOAT |
| hard_stop | BOOLEAN |
| alert_webhook_url | VARCHAR nullable |
| created_at | TIMESTAMPTZ |
| updated_at | TIMESTAMPTZ |

#### `CacheEntryRecord` (`cache_entries` table)

Uses `pgvector` extension. Requires `CREATE EXTENSION IF NOT EXISTS vector` in migration.

| Column | Type |
|--------|------|
| id | UUID PK |
| prompt_hash | VARCHAR(64) unique indexed |
| embedding | `VECTOR(384)` |
| response_preview | VARCHAR(200) |
| model | VARCHAR |
| feature_tag | VARCHAR indexed |
| similarity_threshold | FLOAT |
| created_at | TIMESTAMPTZ |
| expires_at | TIMESTAMPTZ nullable indexed |
| last_hit_at | TIMESTAMPTZ |
| hit_count | INTEGER |
| cost_saved_usd | NUMERIC(10,6) |

### 3.5 API Layer

All routes require `X-Axon-API-Key` header. Missing or invalid key returns 401. Authentication is a FastAPI dependency injected via `Depends(verify_api_key)`.

#### Spans API (`/v1/spans`)

```
POST /v1/spans
  Body: SpanIngestRequest { spans: list[InferenceSpanPayload] }
  Validation: max 1000 spans; reject any span with timestamp > now() + 60s
  Action: bulk insert → budget check → (optional) webhook
  Response: 202 SpanIngestResponse { accepted: int, rejected: int }

GET /v1/spans
  Query: feature_tag?, from_ts, to_ts, limit (≤ 1000)
  Response: list[InferenceSpanPayload]
```

#### Attribution API (`/v1/attribution`)

```
GET /v1/attribution
  Query: feature_tag?, from_ts, to_ts, group_by (model|provider|feature_tag)
  Response: AttributionResponse {
    total_cost_usd, total_tokens, total_savings_usd,
    breakdown: list[AttributionRow]
  }

GET /v1/attribution/summary
  Query: period (daily|weekly|monthly)
  Response: top 10 feature_tags by cost with trend
```

#### Budgets API (`/v1/budgets`)

```
PUT /v1/budgets/{feature_tag}    — upsert, returns BudgetControlRecord
GET /v1/budgets/{feature_tag}    — BudgetStatusResponse
GET /v1/budgets                  — list[BudgetStatusResponse]
DELETE /v1/budgets/{feature_tag} — 204 No Content
```

#### Cache API (`/v1/cache`)

```
POST /v1/cache/lookup    — exact hash then pgvector similarity
POST /v1/cache/store     — insert/upsert CacheEntryRecord
POST /v1/cache/invalidate — by feature_tag or prompt_hash
GET  /v1/cache/stats      — aggregated cache statistics
```

#### Health Endpoints (no auth)

```
GET /health        → { status: "ok", version: "0.2.0" }
GET /health/db     → checks DB connection
GET /health/redis  → checks Redis ping
```

### 3.6 Services

#### `span_ingestion.py`

```python
async def ingest_spans(
    spans: list[InferenceSpanPayload],
    db: AsyncSession,
    redis: Redis,
) -> SpanIngestResponse:
```

1. Filter future-timestamped spans (> 60s ahead) → count as rejected
2. Bulk insert accepted spans using `insert().on_conflict_do_nothing()`
3. For each unique `feature_tag` in accepted spans: call `check_budget()`
4. If `EXHAUSTED` or `WARNING` with webhook configured: schedule `fire_webhook()` as `BackgroundTask`
5. Return `SpanIngestResponse(accepted=N, rejected=M)`

#### `cost_attribution.py`

```python
async def materialize_hourly(db: AsyncSession, hour: datetime) -> int:
```

Groups `inference_spans` by `(feature_tag, provider, model)` for the given hour bucket. Upserts into `cost_attribution` using `INSERT ... ON CONFLICT DO UPDATE`. Returns rows affected. Idempotent.

```python
async def get_attribution(
    db: AsyncSession,
    feature_tag: str | None,
    from_ts: datetime,
    to_ts: datetime,
    group_by: str,
) -> AttributionResponse:
```

Queries `cost_attribution` table with optional filters. Groups and sums by the requested dimension.

#### `budget_enforcer.py`

```python
async def check_budget(
    feature_tag: str,
    db: AsyncSession,
    redis: Redis,
) -> BudgetStatus:
```

1. Try Redis `GET axon:budget:{feature_tag}` (fast path)
2. On miss: compute `SUM(cost_usd)` from `inference_spans` for current period, cache in Redis with TTL
3. Compare against `budget_usd * alert_threshold_pct`
4. Return `BudgetStatus.OK | WARNING | EXHAUSTED`

```python
async def fire_webhook(webhook_url: str, payload: BudgetAlertPayload) -> None:
```

POST with `timeout=10s`. Catches all exceptions, logs — never raises.
Payload: `{ feature_tag, budget_usd, spent_usd, pct_used, status, timestamp }`.

#### `semantic_cache.py` (backend)

```python
async def lookup(
    prompt_hash: str,
    embedding: list[float],
    db: AsyncSession,
    threshold: float,
) -> CacheLookupResponse:
```

1. Exact hash lookup (fast path)
2. On miss: pgvector cosine similarity — `ORDER BY embedding <=> :query LIMIT 1`
3. Return hit if similarity >= threshold

```python
async def store(request: CacheStoreRequest, db: AsyncSession) -> None:
```

`INSERT ... ON CONFLICT (prompt_hash) DO UPDATE SET hit_count = hit_count + 1, last_hit_at = now()`

### 3.7 Background Workers (`workers/scheduler.py`)

APScheduler `AsyncIOScheduler`:

| Job | Schedule | Action |
|-----|----------|--------|
| `materialize_attribution` | Every hour at :05 | `materialize_hourly()` for previous complete hour |
| `expire_cache_entries` | Daily at 02:00 | `DELETE FROM cache_entries WHERE expires_at < now()` |
| `recompute_budget_counters` | Every 15 minutes | Recompute Redis budget counters for all active feature_tags |

### 3.8 FastAPI App (`main.py`)

Lifespan context manager:
- **Startup**: `init_db()` → `ping_redis()` → `scheduler.start()`
- **Shutdown**: `scheduler.shutdown()` → close DB pool → close Redis

Middleware stack (outer to inner):
1. `CORSMiddleware` — origins from `Settings.cors_origins`
2. `RequestLoggingMiddleware` — structlog, logs method + path + status + duration_ms

Route prefix: `/v1` via `include_router(v1_router, prefix="/v1")`

---

## 4. SDK Additions

### 4.1 `axon/backend_client.py`

```python
class BackendClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Axon-API-Key": api_key},
            timeout=2.0,
        )

    async def send_span(self, span: InferenceSpan) -> None:
        """POST to /v1/spans. Fire-and-forget. Never raises."""

    async def check_budget(self, feature_tag: str) -> BudgetStatus:
        """GET /v1/budgets/{feature_tag}. Fail open — returns OK on any error."""

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient."""
```

`configure()` in `axon/core/instrumentor.py` gains two new optional parameters:

```python
def configure(
    otlp_endpoint: str | None = None,
    export_to_stdout: bool = True,
    local_span_log: str | None = None,
    backend_url: str | None = None,      # NEW
    backend_api_key: str | None = None,  # NEW
) -> None:
```

When `backend_url` is set, a module-level `_backend_client` is created. `_run_pipeline()` calls `asyncio.create_task(client.send_span(span))` independently of the OTEL path.

### 4.2 `axon/cache/semantic_cache.py`

```python
class SemanticCacheClient:
    def __init__(self, backend_client: BackendClient) -> None: ...

    async def lookup(
        self,
        messages: list[dict[str, Any]],
        model: str,
    ) -> CacheLookupResult | None:
        """Compute embedding locally, check cache via backend. Fail open."""

    async def store(
        self,
        messages: list[dict[str, Any]],
        response_text: str,
        model: str,
        feature_tag: str,
        cost_usd: Decimal,
    ) -> None:
        """Store response in cache. Fire-and-forget."""
```

`CacheLookupResult` dataclass: `{ hit: bool, response_preview: str | None, similarity: float | None }`.

Reuses `axon.compression.relevance_scorer._model` singleton for embedding — no extra model load.

---

## 5. Infrastructure

### 5.1 Docker Compose (`deploy/docker-compose.yml`)

| Service | Image | Port | Depends On |
|---------|-------|------|------------|
| postgres | `pgvector/pgvector:pg16` | 5432 | — |
| redis | `redis:7-alpine` | 6379 | — |
| axon-backend | built from `../backend` | 8000 | postgres healthy, redis healthy |
| grafana | `grafana/grafana:10.4.0` | 3000 | axon-backend |

Volumes: `postgres_data`, `redis_data`, `grafana_data`

### 5.2 Alembic Migration (`versions/0001_initial_schema.py`)

`upgrade()` steps:
1. `CREATE EXTENSION IF NOT EXISTS vector`
2. Create `inference_spans` table with all columns + composite indexes
3. Create `cost_attribution` table with unique constraint
4. Create `budget_controls` table
5. Create `cache_entries` table with `VECTOR(384)` column + IVFFlat index

`downgrade()` drops tables in reverse order, then drops extension.

---

## 6. Grafana Dashboards

Three provisioned dashboards using Axon backend as JSON API datasource.

### `cost-overview.json`
Total cost time series, cost by model (bar), cost by provider (pie), top 5 feature_tags (table), input vs output tokens (stacked bar).

### `compression-roi.json`
Tokens saved time series, cost saved by compression (stat, cumulative), compression ratio by feature_tag (table), cache hit rate (time series), cost saved by cache (stat, cumulative).

### `budget-burn-rate.json`
Budget utilization per feature_tag (gauge), daily spend vs budget (time series), features approaching limit (table sorted by pct_used), alert annotations.

---

## 7. Testing Strategy

### 7.1 `backend/tests/conftest.py` Fixtures

- `async_client` — `FastAPI AsyncClient` with test DB and in-memory Redis
- `db_session` — isolated transaction per test, rolled back on teardown
- `redis_mock` — `fakeredis.aioredis`
- `sample_span_payload()` — factory for a valid `InferenceSpanPayload`
- `sample_spans_batch(n=10)` — factory for n valid payloads

### 7.2 Key Test Invariants

**Unit tests:**
- Budget at 100% with `hard_stop=True` → `EXHAUSTED`
- Webhook failure does not fail span ingestion
- Cache exact hash lookup never hits pgvector path
- `materialize_hourly` is idempotent (upsert semantics)

**Integration tests:**
- `POST /v1/spans` with 1000 spans → 202
- Future timestamp span is rejected, others accepted
- All endpoints return 401 without API key
- `/health` returns 200 even without scheduler
- Cache returns hit after store

### 7.3 Coverage Target

75% overall for `axon_backend`. Phase 1 regression: ≥ 80%.

---

## 8. CI Integration

New `backend-test` job in `.github/workflows/ci.yml`:

```yaml
backend-test:
  runs-on: ubuntu-latest
  services:
    postgres:
      image: pgvector/pgvector:pg16
      env: { POSTGRES_USER: axon, POSTGRES_PASSWORD: axon, POSTGRES_DB: axon_test }
      ports: ["5432:5432"]
    redis:
      image: redis:7-alpine
      ports: ["6379:6379"]
  steps:
    - uses: actions/checkout@v4
    - run: cd backend && pip install -e ".[dev]"
    - run: cd backend && alembic upgrade head
    - run: cd backend && pytest tests/ --cov=axon_backend --cov-fail-under=75
```

---

## 9. Commit Dependency Graph

```
01 structure → 02 config → 03 DB → 04 Redis → 05 models+migrations
→ 06 ingestion → 07 attribution → 08 budgets → 09 cache → 10 workers
→ 11 spans API → 12 attribution API → 13 budgets API → 14 cache API
→ 15 main.py → 16 Dockerfile → 17 Docker Compose → 18 Grafana
→ 19 BackendClient → 20 SemanticCacheClient → 21 configure() update
→ 22 unit tests → 23 integration tests → 24 CI → 25 README → 26 complete
```

Each commit is atomic: the codebase compiles and mypy passes after every commit even before the test commits (22–23).
