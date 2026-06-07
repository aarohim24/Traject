# Implementation Plan: Axon Phase 2

## Overview

26 atomic commits that build the Axon backend service from an empty directory to a fully validated self-hosted platform. Each task maps to exactly one commit. The sequence is bottom-up: infrastructure → data → services → API → deploy → SDK additions → tests → CI and docs.

**Hard constraints:**
- Do NOT modify anything under `sdk/python/` except `axon/backend_client.py`, `axon/cache/__init__.py`, `axon/cache/semantic_cache.py`, and the `configure()` function signature in `axon/core/instrumentor.py`.
- After every commit, `cd sdk/python && mypy axon --strict` must still pass.
- After commits 19–21, `cd sdk/python && pytest --cov=axon --cov-fail-under=80` must pass.

---

## Tasks

- [x] 1. Initialize backend service structure
  - Create the full directory tree: `backend/axon_backend/` with subdirectories `api/v1/`, `models/`, `services/`, `workers/`, `core/`; `backend/migrations/versions/`; `backend/tests/unit/`; `backend/tests/integration/`
  - Create all `__init__.py` files in every package directory
  - Create `backend/pyproject.toml` with `name="axon-backend"`, `version="0.2.0"`, `requires-python=">=3.11"`, and all runtime dependencies from the spec (fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, alembic, pgvector, redis[hiredis], pydantic, pydantic-settings, structlog, apscheduler, httpx, sentence-transformers)
  - Create `backend/pyproject.toml` `[project.optional-dependencies]` with `dev` (pytest, pytest-asyncio, pytest-cov, httpx, anyio, fakeredis) and `prod` extras
  - Create `backend/alembic.ini` pointing to `migrations/` directory
  - Create `backend/migrations/env.py` and `backend/migrations/script.py.mako` (standard Alembic templates)
  - Create `backend/migrations/versions/` directory with `.gitkeep`
  - Create stub `backend/axon_backend/main.py` (bare `app = FastAPI()` placeholder)
  - Verify `pip install -e ".[dev]"` succeeds from `backend/`
  - _Commit: `chore(backend): initialize backend service structure`_
  - _Satisfies: R1.1, R1.2, R1.3, R1.4, R1.5, R1.6_

- [x] 2. Add Settings config with pydantic-settings
  - Implement `backend/axon_backend/core/config.py` with `Settings(BaseSettings)` class
  - Include all fields from the design (§3.1): `database_url`, `database_pool_size`, `database_max_overflow`, `redis_url`, `redis_cache_ttl_seconds`, `api_host`, `api_port`, `api_workers`, `cors_origins`, `api_key_header`, `api_key`, `cache_similarity_threshold`, `cache_max_entries`, `budget_alert_webhook_timeout_seconds`
  - Set `model_config = SettingsConfig(env_file=".env", extra="ignore")`
  - Export a module-level `settings = Settings()` singleton for import by other modules
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - Create `deploy/.env.example` with all configurable variables and inline comments
  - _Commit: `feat(backend): add Settings config with pydantic-settings`_
  - _Satisfies: R2.1_

- [x] 3. Add async SQLAlchemy database setup
  - Implement `backend/axon_backend/core/database.py`
  - Create `engine = create_async_engine(settings.database_url, pool_size=settings.database_pool_size, max_overflow=settings.database_max_overflow, echo=False)`
  - Create `AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)`
  - Implement `async def get_db() -> AsyncGenerator[AsyncSession, None]` — yields session, closes on exit; use as FastAPI `Depends`
  - Implement `async def init_db() -> None` — calls `async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)`
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): add async SQLAlchemy database setup`_
  - _Satisfies: R3.1, R3.2, R3.3, R3.5_

- [x] 4. Add Redis client with health check
  - Implement `backend/axon_backend/core/redis_client.py`
  - Declare module-level `_redis: Redis | None = None`
  - Implement `def get_redis() -> Redis` — creates `redis.asyncio.from_url(settings.redis_url)` on first call, returns singleton thereafter
  - Implement `async def ping_redis() -> None` — calls `(await get_redis()).ping()`, logs success or failure via structlog; never raises
  - Enforce key namespace convention: document `"axon:{key_type}:{identifier}"` pattern in module docstring
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): add Redis client with health check`_
  - _Satisfies: R4.1, R4.2, R4.3, R4.4, R4.5_

- [x] 5. Define all SQLAlchemy models with Alembic migration
  - Implement `backend/axon_backend/models/base.py` — `Base = DeclarativeBase()`
  - Implement `backend/axon_backend/models/span.py` — `InferenceSpanRecord(Base)` with all columns from design §3.4 using `mapped_column` syntax; composite indexes on `(feature_tag, timestamp)` and `(environment, timestamp)`
  - Implement `backend/axon_backend/models/attribution.py` — `CostAttributionRecord(Base)` with `UniqueConstraint("feature_tag", "hour_bucket", "provider", "model")`
  - Implement `backend/axon_backend/models/budget.py` — `BudgetControlRecord(Base)` with `UniqueConstraint("feature_tag")`
  - Implement `backend/axon_backend/models/cache_entry.py` — `CacheEntryRecord(Base)` with `pgvector.sqlalchemy.Vector(384)` for the `embedding` column
  - Implement `backend/axon_backend/models/__init__.py` — re-export all four record classes
  - Write `backend/migrations/versions/0001_initial_schema.py`:
    - `upgrade()`: `CREATE EXTENSION IF NOT EXISTS vector`, then create all four tables with all columns, constraints, and indexes
    - `downgrade()`: drop all four tables in reverse order, then `DROP EXTENSION IF EXISTS vector`
  - Update `backend/migrations/env.py` to use `Base.metadata` and async context
  - All models use SQLAlchemy 2.0 `mapped_column` — no legacy `Column`
  - Full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): define all SQLAlchemy models with migrations`_
  - _Satisfies: R5.1, R5.2, R5.3, R5.4, R5.5, R5.6, R5.7, R5.8, R5.9_

- [x] 6. Implement span ingestion service
  - Implement `backend/axon_backend/services/span_ingestion.py`
  - Define Pydantic v2 models `InferenceSpanPayload`, `SpanIngestRequest`, `SpanIngestResponse`
  - Implement `async def ingest_spans(spans, db, redis) -> SpanIngestResponse`:
    - Filter spans with `timestamp > datetime.utcnow() + timedelta(seconds=60)` → rejected
    - Bulk insert accepted spans using `await db.execute(insert(InferenceSpanRecord).values(...).on_conflict_do_nothing())`
    - Collect unique feature_tags from accepted spans
    - Call `check_budget(feature_tag, db, redis)` for each (import from budget_enforcer — stub the import; actual impl in task 8)
    - Return `SpanIngestResponse(accepted=len(valid), rejected=len(invalid))`
  - Define `BudgetStatus` enum: `OK`, `WARNING`, `EXHAUSTED`
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): implement span ingestion service`_
  - _Satisfies: R6.1, R6.2, R6.3, R6.4, R6.5, R6.6_

- [x] 7. Implement cost attribution aggregation service
  - Implement `backend/axon_backend/services/cost_attribution.py`
  - Define Pydantic v2 models: `AttributionRow`, `AttributionResponse`
  - Implement `async def materialize_hourly(db: AsyncSession, hour: datetime) -> int`:
    - Build SQL query: `SELECT feature_tag, provider, model, SUM(input_tokens), SUM(output_tokens), SUM(cached_tokens), SUM(cost_usd), SUM(tokens_saved), COUNT(*), COUNT(*) FILTER (WHERE cache_hit), PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms), PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) FROM inference_spans WHERE timestamp >= :hour AND timestamp < :hour_end GROUP BY feature_tag, provider, model`
    - Upsert results into `cost_attribution` via `INSERT ... ON CONFLICT DO UPDATE`
    - Return row count
  - Implement `async def get_attribution(db, feature_tag, from_ts, to_ts, group_by) -> AttributionResponse`:
    - Query `cost_attribution` with filters; group by requested dimension; sum all numeric columns
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): implement cost attribution aggregation`_
  - _Satisfies: R7.1, R7.2, R7.3, R7.4, R7.5_

- [x] 8. Implement budget enforcer with webhook alerting
  - Implement `backend/axon_backend/services/budget_enforcer.py`
  - Define Pydantic v2 model `BudgetAlertPayload { feature_tag, budget_usd, spent_usd, pct_used, status, timestamp }`
  - Implement `async def check_budget(feature_tag, db, redis) -> BudgetStatus`:
    - Try `await redis.get(f"axon:budget:{feature_tag}")` (fast path)
    - On miss: `SELECT SUM(cost_usd) FROM inference_spans WHERE feature_tag = :tag AND timestamp >= :period_start`; cache result in Redis with `EXPIRE settings.redis_cache_ttl_seconds`
    - Load `BudgetControlRecord` for feature_tag; if none exists, return `BudgetStatus.OK`
    - Compare spend against `budget_usd * alert_threshold_pct` and `budget_usd`
    - Catch ALL exceptions with structlog warning; return `BudgetStatus.OK`
  - Implement `async def fire_webhook(webhook_url, payload) -> None`:
    - `async with httpx.AsyncClient(timeout=settings.budget_alert_webhook_timeout_seconds) as client: await client.post(webhook_url, json=payload.model_dump())`
    - Wrap in `try/except Exception`; log success or failure; never raise
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): implement budget enforcer with webhook`_
  - _Satisfies: R8.1, R8.2_

- [x] 9. Implement semantic cache service
  - Implement `backend/axon_backend/services/semantic_cache.py`
  - Define Pydantic v2 models: `CacheLookupResponse { hit, response_preview, similarity }`, `CacheStoreRequest { prompt_hash, prompt_embedding, response_preview, model, feature_tag, cost_usd }`
  - Implement `async def lookup(prompt_hash, embedding, db, threshold) -> CacheLookupResponse`:
    - Exact hash: `SELECT * FROM cache_entries WHERE prompt_hash = :hash`
    - If miss: `SELECT *, 1 - (embedding <=> :query) AS similarity FROM cache_entries ORDER BY embedding <=> :query LIMIT 1` (pgvector cosine)
    - Return hit if `similarity >= threshold`
    - Wrap in `try/except Exception`; return `CacheLookupResponse(hit=False, ...)` on error
  - Implement `async def store(request, db) -> None`:
    - `INSERT INTO cache_entries (...) VALUES (...) ON CONFLICT (prompt_hash) DO UPDATE SET hit_count = cache_entries.hit_count + 1, last_hit_at = now()`
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): implement semantic cache service`_
  - _Satisfies: R9.1, R9.2_

- [x] 10. Implement APScheduler background workers
  - Implement `backend/axon_backend/workers/scheduler.py`
  - Create `scheduler = AsyncIOScheduler()` module-level instance
  - Add `materialize_attribution` job: `scheduler.add_job(run_materialize, "cron", minute=5)` where `run_materialize` calls `materialize_hourly(db, previous_hour)`; use async DB session via `AsyncSessionLocal()`
  - Add `expire_cache_entries` job: `scheduler.add_job(run_expire_cache, "cron", hour=2, minute=0)` — `DELETE FROM cache_entries WHERE expires_at IS NOT NULL AND expires_at < now()`
  - Add `recompute_budget_counters` job: `scheduler.add_job(run_recompute_budgets, "interval", minutes=15)` — recompute Redis budget counters for all `BudgetControlRecord`s
  - Wrap all job functions in `try/except Exception` with structlog error logging — scheduler must not crash
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): implement APScheduler background workers`_
  - _Satisfies: R10.1, R10.2, R10.3, R10.4, R10.5, R10.6_

- [x] 11. Implement spans API endpoints
  - Implement `backend/axon_backend/api/v1/spans.py`
  - Define `verify_api_key` FastAPI dependency: reads `X-Axon-API-Key` header; raises `HTTPException(401)` if missing or != `settings.api_key`
  - `POST /v1/spans`:
    - Validates `SpanIngestRequest` (list max 1000 spans via `Field(max_length=1000)`)
    - Calls `await ingest_spans(request.spans, db, redis)`
    - Returns `JSONResponse(content=result.model_dump(), status_code=202)`
  - `GET /v1/spans`:
    - Accepts query params `feature_tag: str | None`, `from_ts: datetime`, `to_ts: datetime`, `limit: int = Field(le=1000, default=100)`
    - Returns `list[InferenceSpanPayload]`
  - Both routes use `Depends(verify_api_key)`, `Depends(get_db)`, `Depends(get_redis)`
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): implement spans API endpoints`_
  - _Satisfies: R11.1, R11.2_

- [x] 12. Implement attribution API endpoints
  - Implement `backend/axon_backend/api/v1/attribution.py`
  - `GET /v1/attribution`:
    - Accepts `feature_tag: str | None`, `from_ts: datetime`, `to_ts: datetime`, `group_by: Literal["model", "provider", "feature_tag"] = "feature_tag"`
    - Calls `await get_attribution(db, feature_tag, from_ts, to_ts, group_by)`
    - Returns `AttributionResponse`
  - `GET /v1/attribution/summary`:
    - Accepts `period: Literal["daily", "weekly", "monthly"] = "daily"`
    - Returns top 10 feature_tags by total cost for the requested period
  - Both routes use `Depends(verify_api_key)` and `Depends(get_db)`
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): implement attribution API endpoints`_
  - _Satisfies: R12.1, R12.2_

- [x] 13. Implement budgets API endpoints
  - Implement `backend/axon_backend/api/v1/budgets.py`
  - Define Pydantic v2 models: `BudgetControlPayload { period, budget_usd, alert_threshold_pct, hard_stop, alert_webhook_url? }`, `BudgetStatusResponse { feature_tag, budget, period, spent_usd, remaining_usd, pct_used, status }`
  - `PUT /v1/budgets/{feature_tag}`: upsert `BudgetControlRecord`; return updated record; 200
  - `GET /v1/budgets/{feature_tag}`: load record + compute current spend via `check_budget()`; return `BudgetStatusResponse`; 404 if not found
  - `GET /v1/budgets`: return `list[BudgetStatusResponse]` for all configured budgets
  - `DELETE /v1/budgets/{feature_tag}`: delete record + invalidate Redis key; 204; 404 if not found
  - All routes use `Depends(verify_api_key)`, `Depends(get_db)`, `Depends(get_redis)`
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): implement budgets API endpoints`_
  - _Satisfies: R13.1_

- [x] 14. Implement cache API endpoints
  - Implement `backend/axon_backend/api/v1/cache.py`
  - Define Pydantic v2 request/response models: `CacheLookupRequest`, `CacheInvalidateRequest`
  - `POST /v1/cache/lookup`: calls `await lookup(request.prompt_hash, request.prompt_embedding, db, settings.cache_similarity_threshold)`; returns `CacheLookupResponse`
  - `POST /v1/cache/store`: calls `await store(request, db)`; returns `201 Created`
  - `POST /v1/cache/invalidate`: deletes by `feature_tag` or `prompt_hash`; returns `{ "invalidated": N }`
  - `GET /v1/cache/stats`: aggregates from `cache_entries` table; returns `{ hit_count, miss_count, hit_rate, total_cost_saved_usd, entry_count }`; optional `feature_tag` filter
  - All routes use `Depends(verify_api_key)` and `Depends(get_db)`
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): implement cache API endpoints`_
  - _Satisfies: R14.1_

- [x] 15. Add FastAPI app with lifespan and middleware
  - Implement `backend/axon_backend/main.py` fully
  - Define `@asynccontextmanager async def lifespan(app: FastAPI)`:
    - Startup: `await init_db()`, `await ping_redis()`, `scheduler.start()`
    - Shutdown: `scheduler.shutdown(wait=False)`, `await engine.dispose()`, `await (await get_redis()).aclose()`
  - Create `app = FastAPI(title="Axon Backend", version="0.2.0", lifespan=lifespan)`
  - Add `CORSMiddleware` with `allow_origins=settings.cors_origins`, `allow_methods=["*"]`, `allow_headers=["*"]`, `allow_credentials=True`
  - Add `RequestLoggingMiddleware` using structlog: log `method`, `path`, `status_code`, `duration_ms` per request — no `print()` statements
  - Add health routes (no auth required): `GET /health → {status: "ok", version: "0.2.0"}`, `GET /health/db → checks DB`, `GET /health/redis → checks Redis ping`
  - Include v1 router: `app.include_router(v1_router, prefix="/v1")`
  - Implement `backend/axon_backend/api/v1/router.py` that aggregates spans, attribution, budgets, cache routers
  - Add module-level docstring; full type annotations; `mypy --strict` clean
  - _Commit: `feat(backend): add FastAPI app with lifespan and middleware`_
  - _Satisfies: R15.1, R15.2_

- [x] 16. Add backend Dockerfile
  - Create `backend/Dockerfile`:
    ```
    FROM python:3.11-slim
    WORKDIR /app
    COPY pyproject.toml .
    RUN pip install -e ".[prod]"
    COPY axon_backend/ axon_backend/
    COPY migrations/ migrations/
    COPY alembic.ini .
    CMD ["sh", "-c", "alembic upgrade head && uvicorn axon_backend.main:app --host 0.0.0.0 --port 8000 --workers 2"]
    ```
  - Verify `docker build -f backend/Dockerfile backend/` succeeds
  - _Commit: `feat(backend): add backend Dockerfile`_
  - _Satisfies: R16.2_

- [x] 17. Add Docker Compose with all services
  - Create `deploy/docker-compose.yml` with four services: `postgres` (`pgvector/pgvector:pg16`), `redis` (`redis:7-alpine`), `axon-backend` (built from `../backend`), `grafana` (`grafana/grafana:10.4.0`)
  - Configure health checks for all services as specified in the design (§5.1)
  - Set `depends_on` with `condition: service_healthy` for `axon-backend` (depends on postgres + redis) and `grafana` (depends on axon-backend)
  - Define volumes: `postgres_data`, `redis_data`, `grafana_data`
  - Configure `axon-backend` environment: `DATABASE_URL`, `REDIS_URL`, `API_KEY` (with fallback default)
  - Configure `grafana` environment: `GF_SECURITY_ADMIN_PASSWORD` (with fallback), `GF_USERS_ALLOW_SIGN_UP=false`
  - Mount Grafana provisioning and dashboard volumes
  - _Commit: `feat(deploy): add Docker Compose with all services`_
  - _Satisfies: R16.1, R16.4, R16.5_

- [x] 18. Add Grafana provisioning and 3 dashboards
  - Create `dashboards/grafana/provisioning/datasources/datasource.yml` — configure Axon backend as a JSON API datasource pointing to `http://axon-backend:8000`
  - Create `dashboards/grafana/provisioning/dashboards/dashboards.yml` — configure dashboard provisioning from `/var/lib/grafana/dashboards` folder, named "Axon"
  - Create `dashboards/grafana/dashboards/cost-overview.json` — panels: total cost time series by feature_tag, cost by model (bar), cost by provider (pie), top 5 feature_tags (table), input vs output tokens (stacked bar)
  - Create `dashboards/grafana/dashboards/compression-roi.json` — panels: tokens saved time series, cost saved by compression (stat, cumulative), compression ratio by feature_tag (table), cache hit rate (time series), cost saved by cache (stat, cumulative)
  - Create `dashboards/grafana/dashboards/budget-burn-rate.json` — panels: budget utilization per feature_tag (gauge), daily spend vs budget (time series), features approaching limit (table sorted by pct_used), alert annotations
  - All dashboard JSON files must be valid Grafana 10.4 JSON format with `schemaVersion`, `title`, `uid`, and `panels` arrays
  - _Commit: `feat(dashboards): add Grafana provisioning and 3 dashboards`_
  - _Satisfies: R17.1, R17.2, R17.3, R17.4, R17.5_

- [x] 19. Add backend HTTP client to SDK (fire-and-forget spans)
  - Create `sdk/python/axon/backend_client.py`
  - Define `BudgetStatus` enum: `OK`, `WARNING`, `EXHAUSTED`
  - Implement `class BackendClient`:
    - `__init__(self, base_url: str, api_key: str) -> None` — creates `httpx.AsyncClient(base_url=base_url, headers={"X-Axon-API-Key": api_key}, timeout=2.0)`
    - `async def send_span(self, span: InferenceSpan) -> None` — POST `[span.model_dump()]` to `/v1/spans`; catch all exceptions, log with structlog; never raise
    - `async def check_budget(self, feature_tag: str) -> BudgetStatus` — GET `/v1/budgets/{feature_tag}`; parse `status` field; return `BudgetStatus.OK` on any error
    - `async def close(self) -> None` — `await self._client.aclose()`
  - Full type annotations; `mypy --strict` clean
  - Do NOT create `sdk/python/axon/cache/` in this commit — that is task 20
  - Verify `cd sdk/python && pytest --cov=axon --cov-fail-under=80` still passes
  - _Commit: `feat(sdk): add backend HTTP client (fire-and-forget spans)`_
  - _Satisfies: R18.1_

- [x] 20. Add semantic cache client to SDK
  - Create `sdk/python/axon/cache/__init__.py` (empty, with module docstring)
  - Create `sdk/python/axon/cache/semantic_cache.py`
  - Define `CacheLookupResult` as `@dataclass(frozen=True)` with fields `hit: bool`, `response_preview: str | None`, `similarity: float | None`
  - Implement `class SemanticCacheClient`:
    - `__init__(self, backend_client: BackendClient) -> None`
    - `async def lookup(self, messages: list[dict[str, Any]], model: str) -> CacheLookupResult | None`:
      - Compute prompt hash (SHA-256 of normalized content — reuse `_hash_prompt` logic from instrumentor)
      - Compute embedding using `axon.compression.relevance_scorer._model.encode(content, normalize_embeddings=True).tolist()`
      - POST to `/v1/cache/lookup` via `self._backend_client._client`
      - Return `CacheLookupResult` on success; return `None` on any error (fail open)
    - `async def store(self, messages, response_text, model, feature_tag, cost_usd) -> None`:
      - Compute hash and embedding
      - POST to `/v1/cache/store`; catch all exceptions; never raise
  - Full type annotations; `mypy --strict` clean
  - Verify `cd sdk/python && pytest --cov=axon --cov-fail-under=80` still passes
  - _Commit: `feat(sdk): add semantic cache client`_
  - _Satisfies: R19.1_

- [x] 21. Update configure() to accept backend_url
  - Modify `sdk/python/axon/core/instrumentor.py` — update `configure()` signature only:
    ```python
    def configure(
        otlp_endpoint: str | None = None,
        export_to_stdout: bool = True,
        local_span_log: str | None = None,
        backend_url: str | None = None,
        backend_api_key: str | None = None,
    ) -> None:
    ```
  - Add module-level `_backend_client: BackendClient | None = None`
  - In `configure()`: if `backend_url` is set, create `BackendClient(backend_url, backend_api_key or "")` and store in `_backend_client`; if already configured, skip (idempotent)
  - In `_run_pipeline()`: after `emit_span(span)`, if `_backend_client is not None`, call `asyncio.create_task(_backend_client.send_span(span))` — fire and forget, independent of OTEL path
  - Import `BackendClient` from `axon.backend_client` at the top of `instrumentor.py` using `TYPE_CHECKING` guard or lazy import to avoid circular imports
  - Verify `cd sdk/python && mypy axon --strict` passes
  - Verify `cd sdk/python && pytest --cov=axon --cov-fail-under=80` passes
  - _Commit: `feat(sdk): update configure() to accept backend_url`_
  - _Satisfies: R18.2_

- [x] 22. Add unit tests for all backend services
  - Create `backend/tests/conftest.py`:
    - `async_client` fixture using `httpx.AsyncClient(app=app, base_url="http://test")` with test DB override
    - `db_session` fixture: creates a transaction, yields session, rolls back after test
    - `redis_mock` fixture: `fakeredis.aioredis.FakeRedis()`
    - `sample_span_payload()` factory: returns a valid `InferenceSpanPayload` dict
    - `sample_spans_batch(n=10)` factory: returns list of n valid payloads
  - Create `backend/tests/unit/test_span_ingestion.py`:
    - Test `ingest_spans` with valid spans → returns correct `accepted` count
    - Test `ingest_spans` with future-timestamped span → that span counted as rejected
    - Test `ingest_spans` with mixed valid/future → valid ones inserted, future ones rejected
    - Test webhook failure does not prevent successful ingestion
  - Create `backend/tests/unit/test_cost_attribution.py`:
    - Test `materialize_hourly` inserts correct aggregated rows
    - Test `materialize_hourly` is idempotent (call twice, assert same DB state)
    - Test `materialize_hourly` returns 0 when no spans exist for hour
    - Test `get_attribution` returns correct totals
  - Create `backend/tests/unit/test_budget_enforcer.py`:
    - Test `check_budget` returns `OK` when below threshold
    - Test `check_budget` returns `WARNING` when between threshold and limit
    - Test `check_budget` returns `EXHAUSTED` when at 100% of budget with `hard_stop=True`
    - Test Redis fast path used when key exists
    - Test `check_budget` returns `OK` on DB error (fail open)
    - Test `fire_webhook` does not raise on timeout
    - Test `fire_webhook` does not raise on 5xx response
  - Create `backend/tests/unit/test_semantic_cache.py`:
    - Test `lookup` with matching hash returns hit without pgvector search
    - Test `lookup` with no match returns miss
    - Test `lookup` returns non-hit gracefully on DB error
    - Test `store` inserts new entry
    - Test `store` updates hit_count on duplicate hash
  - Run `cd backend && pytest tests/unit/` — all tests must pass
  - _Commit: `test(backend): add unit tests for all services`_
  - _Satisfies: R20.1, R20.3_

- [x] 23. Add integration tests for all API endpoints
  - Create `backend/tests/integration/test_spans_api.py`:
    - Test `POST /v1/spans` with 1000 valid spans → 202 with `accepted=1000`
    - Test `POST /v1/spans` with span having future timestamp → that span rejected
    - Test `POST /v1/spans` without API key → 401
    - Test `POST /v1/spans` with batch > 1000 → 422
    - Test `GET /v1/spans` returns spans matching feature_tag filter
  - Create `backend/tests/integration/test_attribution_api.py`:
    - Test `GET /v1/attribution` without API key → 401
    - Test `GET /v1/attribution` with valid params → 200 with valid `AttributionResponse`
    - Test `GET /v1/attribution?group_by=invalid` → 422
    - Test `GET /v1/attribution/summary?period=daily` → 200
  - Create `backend/tests/integration/test_budgets_api.py`:
    - Test `PUT /v1/budgets/test-tag` → 200 with created record
    - Test `GET /v1/budgets/test-tag` → 200 with `spent_usd` field present
    - Test `GET /v1/budgets/nonexistent` → 404
    - Test `DELETE /v1/budgets/test-tag` → 204 after PUT
    - Test `GET /health` → 200 even before scheduler starts
    - Test all budget endpoints return 401 without API key
  - Run `cd backend && pytest tests/integration/` — all tests must pass
  - Run `cd backend && pytest --cov=axon_backend --cov-fail-under=75` — must pass
  - _Commit: `test(backend): add integration tests for all API endpoints`_
  - _Satisfies: R20.2, R20.3_

- [x] 24. Add backend test job to CI workflow
  - Update `.github/workflows/ci.yml` — add `backend-test` job:
    - `runs-on: ubuntu-latest`
    - Services: `postgres` (`pgvector/pgvector:pg16`, env: `POSTGRES_USER=axon`, `POSTGRES_PASSWORD=axon`, `POSTGRES_DB=axon_test`, port 5432); `redis` (`redis:7-alpine`, port 6379)
    - Steps: `actions/checkout@v4`, `cd backend && pip install -e ".[dev]"`, `cd backend && alembic upgrade head`, `cd backend && pytest tests/ --cov=axon_backend --cov-fail-under=75`
  - Verify the YAML is valid and the existing `sdk-test` job is unchanged
  - _Commit: `ci: add backend test job to CI workflow`_
  - _Satisfies: R21.1, R21.2, R21.3, R21.4_

- [x] 25. Update README with Docker Compose quickstart
  - Add a "## Docker Compose Quickstart" section to `README.md`:
    - Prerequisites: Docker Desktop, no other setup required
    - Step 1: `docker compose -f deploy/docker-compose.yml up -d`
    - Step 2: Wait for healthy — `curl http://localhost:8000/health`
    - Step 3: Open Grafana at `http://localhost:3000` (default credentials in `.env.example`)
    - Step 4: POST a test span to verify ingestion
    - Step 5: `docker compose -f deploy/docker-compose.yml down -v` to clean up
  - Update `deploy/.env.example` to ensure all variables have inline comments
  - _Commit: `docs: update README with Docker Compose quickstart`_
  - _Satisfies: R22.1_

- [x] 26. Phase 2 complete — backend validated, all checks passing
  - Run the full validation checklist from the spec:
    - [x] `cd backend && mypy axon_backend --strict` → 0 errors
    - [x] `cd backend && ruff check axon_backend tests` → clean
    - [x] `cd backend && pytest --cov=axon_backend --cov-fail-under=75` → passes
    - [x] `cd sdk/python && pytest --cov=axon --cov-fail-under=80` → passes (Phase 1 regression)
    - [x] `docker compose -f deploy/docker-compose.yml up -d` → all 4 services healthy
    - [x] `curl http://localhost:8000/health` → `{"status":"ok"}`
    - [x] `curl http://localhost:8000/health/db` → `{"status":"ok"}`
    - [x] `curl http://localhost:8000/health/redis` → `{"status":"ok"}`
    - [ ] Grafana accessible at `http://localhost:3000` → 3 dashboards visible
    - [x] `POST /v1/spans` with valid API key → 202
    - [x] `POST /v1/spans` without API key → 401
    - [x] `docker compose -f deploy/docker-compose.yml down -v` → clean shutdown
  - Fix any issues found during validation (counted as sub-tasks of this commit if trivial, or as an additional commit if substantial)
  - Update `CHANGELOG.md` with Phase 2 release entry
  - _Commit: `chore: Phase 2 complete — backend validated, all checks passing`_
  - _Satisfies: All Phase 2 requirements_
