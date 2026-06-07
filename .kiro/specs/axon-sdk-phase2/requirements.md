# Axon Phase 2 — Requirements

## Introduction

Phase 2 extends the Axon SDK into a complete self-hosted observability platform. Phase 1 delivered a Python SDK with trajectory compression, cost calculation, and OTEL telemetry. Phase 2 adds the backend service layer, persistent storage, semantic caching, budget enforcement, and operational dashboards.

**Constraint**: Phase 1 SDK code under `sdk/python/` must not be modified except for the two explicitly listed additions (`backend_client.py` and `cache/semantic_cache.py`) and the corresponding update to `configure()` to accept `backend_url` and `backend_api_key`.

**Phase 1 regression requirement**: `cd sdk/python && pytest --cov=axon --cov-fail-under=80` must continue to pass after all Phase 2 changes.

---

## Glossary

| Term | Definition |
|------|-----------|
| Span | A single instrumented LLM API call record as defined by `InferenceSpan` in Phase 1 |
| Feature tag | A string label for cost attribution grouping (e.g. "support-bot") |
| Hour bucket | A timestamp truncated to the start of an hour; the unit of attribution materialization |
| Budget period | The rolling time window for spend tracking: `"daily"`, `"weekly"`, or `"monthly"` |
| Hard stop | When `hard_stop=True` on a budget, calls can be blocked when the budget is exhausted |
| Semantic similarity | Cosine similarity between two 384-dimensional sentence embeddings |
| pgvector | PostgreSQL extension providing vector storage and similarity search operators |
| Shadow mode | Phase 1 concept: compression analysis runs but original messages are forwarded |
| Fire-and-forget | An async call that does not await a result and never raises to the caller |
| BudgetStatus | Enum: `OK`, `WARNING`, `EXHAUSTED` |

---

## Requirement 1: Backend Service Initialization

### Requirement 1.1: Repository Structure

**User Story:** As a developer deploying Axon, I want a well-organized backend service structure so that I can understand the codebase immediately and set up local development within five minutes.

#### Acceptance Criteria

1. WHEN the repository is cloned, THEN the directory tree under `axon/backend/` SHALL match exactly the structure defined in the design (§2), including all `__init__.py` files.
2. WHEN `cd backend && pip install -e ".[dev]"` is run, THEN the installation SHALL succeed with zero errors.
3. WHEN `cd backend && python -c "import axon_backend"` is run after installation, THEN the import SHALL succeed.
4. THE `backend/pyproject.toml` SHALL declare `name = "axon-backend"`, `version = "0.2.0"`, and `requires-python = ">=3.11"`.
5. THE `backend/pyproject.toml` SHALL list all runtime dependencies with minimum compatible versions as specified in the spec.
6. THE `backend/pyproject.toml` SHALL include a `[project.optional-dependencies]` section with `dev` and `prod` extras.

---

## Requirement 2: Configuration Management

### Requirement 2.1: Settings via pydantic-settings

**User Story:** As a developer, I want all backend configuration driven by environment variables with sensible defaults so that I can run the service locally without any setup and override values in production with environment variables.

#### Acceptance Criteria

1. WHEN no environment variables are set, THEN `Settings()` SHALL instantiate successfully with default values that work for local development.
2. WHEN `DATABASE_URL` environment variable is set, THEN `Settings().database_url` SHALL reflect that value.
3. THE `Settings` class SHALL expose all fields defined in the design (§3.1): `database_url`, `database_pool_size`, `database_max_overflow`, `redis_url`, `redis_cache_ttl_seconds`, `api_host`, `api_port`, `api_workers`, `cors_origins`, `api_key_header`, `api_key`, `cache_similarity_threshold`, `cache_max_entries`, `budget_alert_webhook_timeout_seconds`.
4. WHEN an unknown environment variable is present, THEN `Settings()` SHALL NOT raise — `extra="ignore"` SHALL be configured.
5. WHEN `CACHE_SIMILARITY_THRESHOLD` is set to `0.95`, THEN `Settings().cache_similarity_threshold` SHALL equal `0.95`.

---

## Requirement 3: Async Database Layer

### Requirement 3.1: SQLAlchemy Async Setup

**User Story:** As a backend engineer, I want an async database layer so that the service handles concurrent requests without blocking.

#### Acceptance Criteria

1. WHEN `init_db()` is called, THEN all SQLAlchemy tables SHALL be created in the database if they do not already exist.
2. WHEN `get_db()` is used as a FastAPI dependency, THEN it SHALL yield an `AsyncSession` that is automatically closed after the request.
3. THE database engine SHALL be configured with `pool_size` and `max_overflow` from `Settings`.
4. WHEN the database is unavailable, THEN `GET /health/db` SHALL return a non-200 response rather than crashing the application.
5. ALL database operations in services SHALL use `await` — no synchronous DB calls are permitted.

---

## Requirement 4: Redis Integration

### Requirement 4.1: Redis Client Singleton

**User Story:** As a backend engineer, I want a Redis client that is initialized once and reused across all requests so that connection pool overhead is minimized.

#### Acceptance Criteria

1. WHEN `get_redis()` is called multiple times, THEN the SAME connection pool instance SHALL be returned each time.
2. WHEN the Redis server is available, THEN `GET /health/redis` SHALL return `{ "status": "ok" }`.
3. WHEN `ping_redis()` fails on startup, THEN the application SHALL log the error and continue starting (Redis is not required for startup).
4. ALL Redis keys SHALL be namespaced with the prefix `"axon:"` — no bare keys.
5. WHEN `get_redis()` is called for the first time, THEN a connection pool SHALL be created using `Settings.redis_url`.

---

## Requirement 5: Database Models and Migration

### Requirement 5.1: SQLAlchemy 2.0 Models

**User Story:** As a data engineer, I want well-defined database schemas with proper indexes so that queries are fast and the schema is auditable.

#### Acceptance Criteria

1. ALL models SHALL use SQLAlchemy 2.0 `mapped_column` syntax — no legacy `Column` usage.
2. THE `InferenceSpanRecord` model SHALL have all columns defined in the design (§3.4) with correct types.
3. THE `CostAttributionRecord` model SHALL have a `UniqueConstraint` on `(feature_tag, hour_bucket, provider, model)`.
4. THE `BudgetControlRecord` model SHALL have a unique constraint on `feature_tag`.
5. THE `CacheEntryRecord` model SHALL use `pgvector.sqlalchemy.Vector(384)` for the `embedding` column.
6. WHEN the Alembic migration `0001_initial_schema.py` is applied with `alembic upgrade head`, THEN all four tables SHALL be created with all columns, indexes, and constraints.
7. THE migration SHALL include `CREATE EXTENSION IF NOT EXISTS vector` before table creation.
8. THE migration SHALL be reversible — `alembic downgrade base` SHALL drop all tables without errors.
9. COMPOSITE indexes SHALL exist on `(feature_tag, timestamp)` and `(environment, timestamp)` in the `inference_spans` table.

---

## Requirement 6: Span Ingestion Service

### Requirement 6.1: Bulk Span Persistence

**User Story:** As an SDK user, I want spans sent to the backend to be persisted reliably so that I can query historical cost data.

#### Acceptance Criteria

1. WHEN `ingest_spans()` is called with a list of valid spans, THEN all valid spans SHALL be bulk-inserted into the `inference_spans` table.
2. WHEN a span has a `timestamp` more than 60 seconds in the future, THEN that span SHALL be counted as rejected and NOT inserted.
3. WHEN some spans are rejected and others are valid, THEN the valid spans SHALL still be inserted.
4. THE `SpanIngestResponse` SHALL include the count of `accepted` spans and `rejected` spans.
5. WHEN a span is inserted that would violate a unique constraint, THEN `on_conflict_do_nothing` SHALL be used — no error raised.
6. WHEN span ingestion is complete, THEN budget check SHALL be triggered for each unique `feature_tag` in the accepted spans.

---

## Requirement 7: Cost Attribution Service

### Requirement 7.1: Hourly Attribution Materialization

**User Story:** As a team lead, I want cost data aggregated by hour and feature tag so that I can analyze spending trends at fine granularity.

#### Acceptance Criteria

1. WHEN `materialize_hourly(db, hour)` is called, THEN it SHALL aggregate all `inference_spans` with `timestamp` in `[hour, hour + 1h)` grouped by `(feature_tag, provider, model)`.
2. WHEN called twice for the same hour, THEN `materialize_hourly` SHALL be idempotent — the upsert SHALL update existing rows rather than creating duplicates.
3. THE aggregation SHALL compute: `SUM(input_tokens)`, `SUM(output_tokens)`, `SUM(cached_tokens)`, `SUM(cost_usd)`, `SUM(tokens_saved)`, `COUNT(*)`, `COUNT(*) WHERE cache_hit = true`, `PERCENTILE_CONT(0.50)` and `PERCENTILE_CONT(0.95)` of `duration_ms`.
4. WHEN there are no spans for the given hour, THEN `materialize_hourly` SHALL return `0` without inserting any rows.
5. THE return value SHALL be the number of rows upserted.

### Requirement 7.2: Attribution Query

**User Story:** As a developer, I want to query attribution data with flexible grouping so that I can answer "how much did feature X cost last week?"

#### Acceptance Criteria

1. WHEN `get_attribution()` is called with `feature_tag=None`, THEN it SHALL return data for all feature tags.
2. WHEN `group_by="model"`, THEN the `breakdown` list SHALL have one entry per distinct model.
3. THE `AttributionResponse.total_cost_usd` SHALL equal the sum of all `total_cost_usd` values in `breakdown`.
4. WHEN `from_ts` and `to_ts` are provided, THEN only records with `hour_bucket >= from_ts AND hour_bucket < to_ts` SHALL be included.

---

## Requirement 8: Budget Enforcement

### Requirement 8.1: Budget Controls

**User Story:** As an engineering manager, I want to set spend budgets per feature tag so that runaway costs are caught before they become a problem.

#### Acceptance Criteria

1. WHEN `check_budget()` is called for a feature tag with a configured budget, THEN it SHALL return `BudgetStatus.OK` when spend is below `alert_threshold_pct * budget_usd`.
2. WHEN spend is between `alert_threshold_pct * budget_usd` and `budget_usd`, THEN `check_budget()` SHALL return `BudgetStatus.WARNING`.
3. WHEN spend equals or exceeds `budget_usd`, THEN `check_budget()` SHALL return `BudgetStatus.EXHAUSTED`.
4. WHEN there is no budget configured for a feature tag, THEN `check_budget()` SHALL return `BudgetStatus.OK`.
5. WHEN the Redis key `axon:budget:{feature_tag}` exists, THEN `check_budget()` SHALL use that cached value without querying the database (fast path).
6. WHEN the Redis cache misses, THEN `check_budget()` SHALL compute spend from the database and cache the result in Redis.
7. WHEN any error occurs in `check_budget()`, THEN the function SHALL catch the exception, log it, and return `BudgetStatus.OK` (fail open).

### Requirement 8.2: Webhook Alerting

**User Story:** As an engineer, I want to receive webhook notifications when budgets are approaching or exceeded so that I can react before costs spiral.

#### Acceptance Criteria

1. WHEN `fire_webhook()` is called, THEN it SHALL POST to `webhook_url` with a JSON payload containing `feature_tag`, `budget_usd`, `spent_usd`, `pct_used`, `status`, and `timestamp`.
2. WHEN the webhook POST times out (> `budget_alert_webhook_timeout_seconds`), THEN `fire_webhook()` SHALL log the error and return without raising.
3. WHEN the webhook returns a 5xx status, THEN `fire_webhook()` SHALL log the failure and return without raising.
4. WHEN any exception occurs in `fire_webhook()`, THEN span ingestion SHALL NOT be affected — the webhook runs as a `BackgroundTask`.
5. THE webhook timeout SHALL use `Settings.budget_alert_webhook_timeout_seconds` (default 10s).

---

## Requirement 9: Semantic Cache Service (Backend)

### Requirement 9.1: Cache Lookup

**User Story:** As an SDK user, I want repeated similar prompts served from cache so that I pay for each unique query at most once.

#### Acceptance Criteria

1. WHEN `lookup()` is called with a `prompt_hash` that exactly matches a cache entry, THEN it SHALL return a hit WITHOUT performing a vector similarity search.
2. WHEN the exact hash is not found, THEN `lookup()` SHALL perform a pgvector cosine similarity search: `ORDER BY embedding <=> :query_embedding LIMIT 1`.
3. WHEN the nearest result has similarity >= `threshold`, THEN `lookup()` SHALL return `CacheLookupResponse(hit=True, ...)`.
4. WHEN the nearest result has similarity < `threshold`, THEN `lookup()` SHALL return `CacheLookupResponse(hit=False, ...)`.
5. WHEN any database error occurs, THEN `lookup()` SHALL catch the exception and return `CacheLookupResponse(hit=False, response_preview=None, similarity=None)` (fail open).

### Requirement 9.2: Cache Store

**User Story:** As an SDK user, I want responses automatically stored in cache so that future similar prompts benefit without any manual cache management.

#### Acceptance Criteria

1. WHEN `store()` is called with a new `prompt_hash`, THEN a new `CacheEntryRecord` SHALL be inserted.
2. WHEN `store()` is called with an existing `prompt_hash`, THEN the existing record's `hit_count` SHALL be incremented and `last_hit_at` SHALL be updated — no duplicate row created.
3. THE `expires_at` field SHALL be set to `now() + Settings.redis_cache_ttl_seconds` when provided by the caller.

---

## Requirement 10: Background Workers

### Requirement 10.1: Scheduled Jobs

**User Story:** As a platform operator, I want background jobs running automatically so that attribution data is fresh and cache entries are cleaned up without manual intervention.

#### Acceptance Criteria

1. WHEN the FastAPI app starts, THEN the APScheduler `AsyncIOScheduler` SHALL start automatically.
2. THE `materialize_attribution` job SHALL run every hour at minute 5 (cron: `minute=5`).
3. THE `expire_cache_entries` job SHALL run daily at 02:00.
4. THE `recompute_budget_counters` job SHALL run every 15 minutes.
5. WHEN a scheduled job raises an unhandled exception, THEN it SHALL be caught and logged — the scheduler SHALL NOT crash.
6. WHEN the FastAPI app shuts down, THEN the scheduler SHALL be stopped gracefully before the DB pool is closed.

---

## Requirement 11: Spans API Endpoints

### Requirement 11.1: POST /v1/spans

**User Story:** As an SDK developer, I want to POST spans to the backend so that the backend can persist and analyze them.

#### Acceptance Criteria

1. WHEN a valid batch of spans is POSTed to `/v1/spans`, THEN the response SHALL be `202 Accepted` with `SpanIngestResponse`.
2. WHEN the batch contains more than 1000 spans, THEN the endpoint SHALL return `422 Unprocessable Entity`.
3. WHEN a span in the batch has a future timestamp (> 60s ahead), THEN that span SHALL be counted as rejected in the response.
4. WHEN the `X-Axon-API-Key` header is missing or invalid, THEN the endpoint SHALL return `401 Unauthorized`.
5. WHEN the batch contains 0 valid spans (all rejected), THEN the endpoint SHALL still return `202` with `accepted=0`.

### Requirement 11.2: GET /v1/spans

**User Story:** As a developer, I want to query spans by feature tag and time range so that I can inspect historical call data.

#### Acceptance Criteria

1. WHEN a valid GET request is made with `feature_tag`, `from_ts`, and `to_ts` query parameters, THEN the response SHALL contain only spans matching all filters.
2. WHEN `limit` exceeds 1000, THEN the endpoint SHALL return `422 Unprocessable Entity`.
3. THE endpoint SHALL require `X-Axon-API-Key` authentication.

---

## Requirement 12: Attribution API Endpoints

### Requirement 12.1: GET /v1/attribution

**User Story:** As a team lead, I want a REST API for cost attribution so that I can build custom cost dashboards or integrate with internal tools.

#### Acceptance Criteria

1. WHEN `GET /v1/attribution` is called with valid parameters, THEN it SHALL return `200 OK` with `AttributionResponse`.
2. WHEN `group_by` is not one of `model`, `provider`, `feature_tag`, THEN the endpoint SHALL return `422`.
3. THE `total_cost_usd` in the response SHALL equal the sum of all `total_cost_usd` values in `breakdown`.
4. THE endpoint SHALL require authentication.

### Requirement 12.2: GET /v1/attribution/summary

**User Story:** As a manager, I want a quick cost summary by period so that I can answer "how much did we spend this week?" in one API call.

#### Acceptance Criteria

1. WHEN `period` is `"daily"`, `"weekly"`, or `"monthly"`, THEN the response SHALL contain the top 10 feature_tags by cost for that period.
2. WHEN `period` is an invalid value, THEN the endpoint SHALL return `422`.

---

## Requirement 13: Budgets API Endpoints

### Requirement 13.1: Budget CRUD

**User Story:** As a team lead, I want a REST API to manage budgets so that I can set and update cost limits without touching the database directly.

#### Acceptance Criteria

1. WHEN `PUT /v1/budgets/{feature_tag}` is called, THEN it SHALL create or update (upsert) a budget record and return `200 OK`.
2. WHEN `GET /v1/budgets/{feature_tag}` is called, THEN the response SHALL include `spent_usd`, `remaining_usd`, `pct_used`, and `status` fields in addition to the budget configuration.
3. WHEN `DELETE /v1/budgets/{feature_tag}` is called for an existing budget, THEN it SHALL return `204 No Content` and the budget SHALL be removed.
4. WHEN `DELETE /v1/budgets/{feature_tag}` is called for a non-existent budget, THEN it SHALL return `404 Not Found`.
5. WHEN `GET /v1/budgets` is called, THEN it SHALL return status information for all configured budgets.
6. ALL budget endpoints SHALL require `X-Axon-API-Key` authentication.

---

## Requirement 14: Cache API Endpoints

### Requirement 14.1: Cache Operations

**User Story:** As an SDK developer, I want REST endpoints for cache operations so that the SDK client can perform lookups and stores via HTTP.

#### Acceptance Criteria

1. WHEN `POST /v1/cache/lookup` is called with a valid `prompt_hash` and `prompt_embedding`, THEN it SHALL return `CacheLookupResponse` with `hit`, `response_preview`, and `similarity`.
2. WHEN `POST /v1/cache/store` is called, THEN the cache entry SHALL be persisted and `201 Created` returned.
3. WHEN `POST /v1/cache/invalidate` is called with `feature_tag`, THEN all cache entries for that tag SHALL be deleted and `{ "invalidated": N }` returned.
4. WHEN `GET /v1/cache/stats` is called, THEN it SHALL return aggregate statistics including `hit_count`, `miss_count`, `hit_rate`, `total_cost_saved_usd`, and `entry_count`.
5. ALL cache endpoints SHALL require `X-Axon-API-Key` authentication.

---

## Requirement 15: FastAPI Application

### Requirement 15.1: App Lifecycle

**User Story:** As a platform operator, I want the backend service to start and stop cleanly so that deployments are reliable and there is no data loss during shutdown.

#### Acceptance Criteria

1. WHEN the app starts, THEN `init_db()`, `ping_redis()`, and `scheduler.start()` SHALL be called in that order within the lifespan context manager.
2. WHEN the app shuts down, THEN the scheduler SHALL be stopped before the DB connection pool is closed.
3. WHEN `GET /health` is called at any point after startup, THEN it SHALL return `200 OK` with `{ "status": "ok", "version": "0.2.0" }`.
4. WHEN `GET /health/db` is called and the DB is reachable, THEN it SHALL return `200 OK`.
5. WHEN `GET /health/redis` is called and Redis is reachable, THEN it SHALL return `200 OK`.
6. THE `/health`, `/health/db`, and `/health/redis` endpoints SHALL NOT require API key authentication.

### Requirement 15.2: Middleware

**User Story:** As a developer, I want CORS configured correctly and every request logged so that browser-based clients work and I can debug issues from logs.

#### Acceptance Criteria

1. WHEN a request arrives with an `Origin` header from a value in `Settings.cors_origins`, THEN the response SHALL include appropriate CORS headers.
2. EVERY request SHALL be logged via structlog with fields: `method`, `path`, `status_code`, `duration_ms`.
3. THE request logging SHALL use `structlog.get_logger(__name__)` — no `print()` statements.

---

## Requirement 16: Docker Compose Deployment

### Requirement 16.1: One-Command Startup

**User Story:** As a developer evaluating Axon, I want to start the entire platform with a single command so that I can see it working within five minutes.

#### Acceptance Criteria

1. WHEN `docker compose -f deploy/docker-compose.yml up -d` is run, THEN all four services (postgres, redis, axon-backend, grafana) SHALL start.
2. WHEN all services have started, THEN `curl http://localhost:8000/health` SHALL return `{"status":"ok"}` within 60 seconds.
3. WHEN `axon-backend` starts, THEN it SHALL wait for `postgres` and `redis` to be healthy (`depends_on: condition: service_healthy`) before starting.
4. THE `docker-compose.yml` SHALL define named volumes `postgres_data`, `redis_data`, and `grafana_data` for persistent storage.
5. WHEN `docker compose -f deploy/docker-compose.yml down -v` is run, THEN all services SHALL stop cleanly with no errors.

### Requirement 16.2: Backend Dockerfile

**User Story:** As a DevOps engineer, I want a production-ready Dockerfile so that the backend can be containerized and deployed consistently.

#### Acceptance Criteria

1. THE Dockerfile SHALL use `python:3.11-slim` as the base image.
2. THE CMD SHALL run `alembic upgrade head` before starting uvicorn so that the schema is always current on startup.
3. WHEN the Docker image is built, THEN `pip install -e ".[prod]"` SHALL succeed.

---

## Requirement 17: Grafana Dashboards

### Requirement 17.1: Provisioned Dashboards

**User Story:** As a developer, I want pre-built Grafana dashboards available immediately after `docker compose up` so that I can start monitoring without manual configuration.

#### Acceptance Criteria

1. WHEN Grafana starts, THEN all three dashboards (`cost-overview`, `compression-roi`, `budget-burn-rate`) SHALL be visible in the Grafana UI under an "Axon" folder without any manual import.
2. THE `dashboards/grafana/provisioning/datasources/datasource.yml` SHALL configure the Axon backend as a JSON API data source.
3. THE `dashboards/grafana/provisioning/dashboards/dashboards.yml` SHALL point to the `dashboards/grafana/dashboards/` directory.
4. EACH dashboard SHALL contain the panels specified in the design (§6).
5. Grafana SHALL be accessible at `http://localhost:3000` after `docker compose up`.

---

## Requirement 18: SDK Backend Client

### Requirement 18.1: BackendClient

**User Story:** As an SDK user, I want spans automatically sent to the backend when I configure `backend_url` so that I don't have to change my instrumented code.

#### Acceptance Criteria

1. WHEN `BackendClient.send_span(span)` is called, THEN it SHALL POST the span to `POST /v1/spans` with the `X-Axon-API-Key` header set.
2. WHEN the backend is unreachable or times out (> 2 seconds), THEN `send_span()` SHALL log the error and return without raising.
3. WHEN any HTTP error (4xx, 5xx) is returned, THEN `send_span()` SHALL log the error and return without raising.
4. WHEN `BackendClient.check_budget(feature_tag)` is called and the backend returns `EXHAUSTED` status, THEN it SHALL return `BudgetStatus.EXHAUSTED`.
5. WHEN `check_budget()` encounters any error (network, HTTP, parse), THEN it SHALL return `BudgetStatus.OK` (fail open).
6. WHEN `BackendClient.close()` is called, THEN the underlying `httpx.AsyncClient` SHALL be closed.
7. THE `BackendClient` constructor SHALL create an `httpx.AsyncClient` with `timeout=2.0` and the API key set in a default header.

### Requirement 18.2: configure() Update

**User Story:** As an SDK user, I want to enable backend integration by calling `axon.configure(backend_url=..., backend_api_key=...)` so that the change is a single line in my setup code.

#### Acceptance Criteria

1. WHEN `configure(backend_url="http://...", backend_api_key="key")` is called, THEN a `BackendClient` instance SHALL be created and stored module-level.
2. WHEN `configure()` is called without `backend_url`, THEN no `BackendClient` SHALL be created and Phase 1 behavior SHALL be unchanged.
3. WHEN a `BackendClient` is configured, THEN `_run_pipeline()` SHALL send the span to the backend via `BackendClient.send_span()` in addition to OTEL export.
4. THE backend send path SHALL NOT block the OTEL emit path — both SHALL run independently.
5. THE `configure()` function SHALL remain backward-compatible — existing calls without `backend_url` SHALL behave identically to Phase 1.

---

## Requirement 19: Semantic Cache Client (SDK)

### Requirement 19.1: SemanticCacheClient

**User Story:** As an SDK user, I want to check the semantic cache before hitting the LLM provider so that I can avoid paying for repeated queries.

#### Acceptance Criteria

1. WHEN `SemanticCacheClient.lookup(messages, model)` is called, THEN it SHALL compute a local embedding of the messages using `all-MiniLM-L6-v2` and call the backend cache lookup endpoint.
2. WHEN the backend returns a cache hit, THEN `lookup()` SHALL return a `CacheLookupResult` with `hit=True` and the `response_preview`.
3. WHEN the backend returns a cache miss, THEN `lookup()` SHALL return `CacheLookupResult(hit=False, ...)`.
4. WHEN any error occurs (network, parse, model failure), THEN `lookup()` SHALL return `None` (fail open).
5. WHEN `SemanticCacheClient.store(messages, response_text, model, feature_tag, cost_usd)` is called, THEN it SHALL compute an embedding and POST to the backend cache store endpoint.
6. WHEN `store()` encounters any error, THEN it SHALL log the error and return without raising.
7. THE `SemanticCacheClient` SHALL reuse the `all-MiniLM-L6-v2` singleton from `axon.compression.relevance_scorer._model` — no additional model load.

---

## Requirement 20: Backend Testing

### Requirement 20.1: Unit Tests

**User Story:** As a backend engineer, I want comprehensive unit tests so that I can refactor with confidence.

#### Acceptance Criteria

1. WHEN `pytest tests/unit/` is run, THEN all unit tests SHALL pass.
2. ALL Redis interactions in unit tests SHALL use `fakeredis.aioredis` — no live Redis required.
3. ALL HTTP webhook calls in unit tests SHALL be mocked — no live HTTP required.
4. THE `conftest.py` SHALL provide `db_session`, `redis_mock`, `async_client`, `sample_span_payload()`, and `sample_spans_batch()` fixtures.
5. WHEN `check_budget()` is tested with spend at 100% of budget and `hard_stop=True`, THEN the test SHALL assert `BudgetStatus.EXHAUSTED`.
6. WHEN `fire_webhook()` is tested with a timeout, THEN the test SHALL assert span ingestion is not affected.
7. WHEN `lookup()` is tested with a matching prompt hash, THEN the test SHALL assert the exact hash path is taken without pgvector search.
8. WHEN `materialize_hourly()` is called twice for the same hour, THEN the test SHALL assert the result is idempotent.

### Requirement 20.2: Integration Tests

**User Story:** As a QA engineer, I want integration tests that validate the full API surface so that I know the endpoints work end to end.

#### Acceptance Criteria

1. WHEN `pytest tests/integration/` is run, THEN all integration tests SHALL pass.
2. WHEN `POST /v1/spans` is called with 1000 valid spans, THEN the test SHALL assert `202` with `accepted=1000`.
3. WHEN `POST /v1/spans` is called with a span whose timestamp is 120 seconds in the future, THEN that span SHALL be rejected while valid spans in the same batch are accepted.
4. WHEN any endpoint is called without `X-Axon-API-Key`, THEN the test SHALL assert `401`.
5. WHEN `GET /health` is called, THEN the test SHALL assert `200` with `status="ok"`.

### Requirement 20.3: Coverage

**User Story:** As a team lead, I want measurable test coverage so that I can track quality objectively.

#### Acceptance Criteria

1. WHEN `pytest --cov=axon_backend --cov-fail-under=75` is run, THEN the test run SHALL pass.
2. WHEN `cd sdk/python && pytest --cov=axon --cov-fail-under=80` is run after all Phase 2 changes, THEN it SHALL still pass (Phase 1 regression).

---

## Requirement 21: CI Integration

### Requirement 21.1: Backend CI Job

**User Story:** As a developer, I want backend tests to run on every pull request so that regressions are caught before merge.

#### Acceptance Criteria

1. THE `.github/workflows/ci.yml` SHALL include a `backend-test` job with PostgreSQL and Redis service containers.
2. WHEN a pull request is opened, THEN the `backend-test` job SHALL run `alembic upgrade head` and `pytest tests/ --cov=axon_backend --cov-fail-under=75`.
3. WHEN the backend tests fail, THEN the CI job SHALL fail with a non-zero exit code.
4. THE CI job SHALL use `pgvector/pgvector:pg16` for the Postgres service container (not plain `postgres:16`).

---

## Requirement 22: Documentation

### Requirement 22.1: Docker Compose Quickstart

**User Story:** As a new user, I want the README to tell me exactly how to run the full platform so that I can be productive in under five minutes.

#### Acceptance Criteria

1. THE `README.md` SHALL contain a "Docker Compose Quickstart" section with the exact command to start all services.
2. THE quickstart section SHALL include: `docker compose -f deploy/docker-compose.yml up -d`, the URL for the health check, and the URL for Grafana.
3. THE `deploy/.env.example` SHALL list all configurable environment variables with comments explaining each one.
