# Implementation Plan: Axon Phase 5 — Differentiation & Scale

## Overview

Phase 5 delivers Track A (ML routing, conformal prediction, batch routing, provider
expansion, plugin system, cost prediction, anomaly detection) and Track B (telemetry
reporter, benchmark registry, community infrastructure, research artifacts, launch docs)
on top of the fully validated Phase 4 platform. Tasks follow the exact 25-commit sequence
defined in the design document, organized to maximize parallelism across waves. All 481
existing tests must remain green at every commit.

---

## Tasks

- [x] 1. feat(backend): add migration 0003 — routing_decision, batch_jobs, benchmark_submissions
  - [x] 1.1 Create `backend/migrations/versions/0003_phase5_schema.py` with `revision="0003"`, `down_revision="0002"`, and a module-level docstring
    - _Requirements: 1.5, 3.5, 8.6_
  - [x] 1.2 Implement `upgrade()`: add nullable `routing_decision` Text column to `inference_spans`; create `batch_jobs` table with all columns (`id` UUID PK, `job_id` str unique, `provider` str, `status` str, `submitted_at` datetime, `span_count` int, `estimated_completion_at` datetime nullable, `created_at` datetime server_default); add indexes `ix_batch_jobs_job_id` and `ix_batch_jobs_status`; create `benchmark_submissions` table with all columns; add index `ix_benchmarks_submitted_at`
    - _Requirements: 1.5, 3.5, 8.6_
  - [x] 1.3 Implement `downgrade()`: drop `benchmark_submissions`, drop `batch_jobs`, drop column `inference_spans.routing_decision` in reverse order
    - _Requirements: 1.5, 3.5, 8.6_
  - [x] 1.4 Verify `mypy --strict` passes with zero errors on the migration file
    - _Requirements: 1.5_

- [x] 2. feat(backend): add BenchmarkSubmissionRecord ORM model
  - [x] 2.1 Create `backend/axon_backend/models/benchmark.py` — `BenchmarkSubmissionRecord(Base)` with all columns matching migration 0003's `benchmark_submissions` table; include module-level docstring and Google-style class docstring
    - _Requirements: 8.6, 9.1_
  - [x] 2.2 Add `BenchmarkSubmissionRecord` to `backend/axon_backend/models/__init__.py` exports so Alembic can discover it
    - _Requirements: 8.6_
  - [x] 2.3 Verify `mypy --strict` passes with zero errors on `models/benchmark.py` and `models/__init__.py`
    - _Requirements: 8.6_

- [x] 3. feat(sdk): add MLModelArtifact dataclass and feature extractor
  - [x] 3.1 Create `sdk/python/axon/router/ml_router.py` with module-level docstring; define `MLModelArtifact` dataclass with fields: `coefficients: list[list[float]]`, `intercept: list[float]`, `classes: list[str]`, `feature_names: list[str]`, `training_sample_count: int`, `trained_at: datetime`
    - _Requirements: 1.1, 1.5_
  - [x] 3.2 Implement `_extract_features(messages: list[dict[str, Any]], requested_model: str, timestamp: datetime) -> np.ndarray` — 18-dimensional vector: task_type one-hot ×10 (indices 0–9 following `list(TaskType)` order), `complexity_score` (index 10), `input_token_count / 8000.0` clipped to [0,1] (index 11), `has_code_blocks` 1.0/0.0 (index 12), `has_tool_calls` 1.0/0.0 (index 13), `hour_of_day` cyclic `[sin(2π·h/24), cos(2π·h/24)]` (indices 14–15), `day_of_week` cyclic `[sin(2π·d/7), cos(2π·d/7)]` (indices 16–17)
    - _Requirements: 1.1_
  - [x] 3.3 Add `InsufficientDataError` as a subclass of `AxonError` to `sdk/python/axon/exceptions.py`
    - _Requirements: 1.6_
  - [x] 3.4 Verify `mypy --strict` and `ruff check` pass with zero errors on `ml_router.py` and `exceptions.py`
    - _Requirements: 1.1_

- [x] 4. feat(sdk): implement MLRouter with fallback to RuleRouter
  - [x] 4.1 Implement `MLRouter` class with `MIN_TRAINING_SAMPLES: int = 500`; `__init__` guards `import sklearn` and raises `AxonDependencyError` if not installed; loads `MLModelArtifact` from JSON at `model_artifact_path` if provided (logs warning and enters fallback mode on load failure)
    - _Requirements: 1.1, 1.9, 1.11_
  - [x] 4.2 Implement `route(messages, requested_model, override_task_type=None) -> RoutingDecision` — delegates to `RuleRouter` when untrained or sample count < 500; otherwise calls `_extract_features`, runs `lr.predict()`, returns `RoutingDecision` with `routing_rule` prefixed `"ml."`; catches all exceptions and falls back to `RuleRouter` (never raises)
    - _Requirements: 1.2, 1.3, 1.4, 1.10_
  - [x] 4.3 Implement `is_trained() -> bool` and `training_stats() -> dict[str, Any]` helper methods with Google-style docstrings
    - _Requirements: 1.5_
  - [x] 4.4 Add `sklearn` as optional dependency in `sdk/python/pyproject.toml` under `[project.optional-dependencies]` with key `"ml"`
    - _Requirements: 1.11_
  - [x] 4.5 Verify `mypy --strict` passes with zero errors on `ml_router.py`
    - _Requirements: 1.1_

- [x] 5. feat(backend): implement MLTrainingService
  - [x] 5.1 Create `backend/axon_backend/services/ml_training.py` with module-level docstring; implement `MLTrainingService` class with configurable `artifact_path` defaulting to `settings.ml_model_path` or `/tmp/axon_ml_model.json`
    - _Requirements: 1.5, 1.7_
  - [x] 5.2 Implement `async def train(db: AsyncSession) -> MLModelArtifact` — query `InferenceSpanRecord` rows with non-null `routing_decision`, extract features using the same 18-dim logic, fit `LogisticRegression`, return `MLModelArtifact`; raise `InsufficientDataError` if zero rows found
    - _Requirements: 1.5, 1.6_
  - [x] 5.3 Implement `async def run_weekly_training_job(db: AsyncSession) -> None` — calls `train()`, persists artifact JSON to `artifact_path`, logs result via structlog; catches all exceptions and never re-raises
    - _Requirements: 1.7_
  - [x] 5.4 Verify `mypy --strict` passes with zero errors on `ml_training.py`
    - _Requirements: 1.5_

- [x] 6. feat(backend): add ml_weekly_training APScheduler job
  - [x] 6.1 Add `async def _run_ml_weekly_training() -> None` to `backend/axon_backend/workers/scheduler.py` — creates `MLTrainingService`, calls `run_weekly_training_job`, logs result; catches all exceptions (never re-raises)
    - _Requirements: 1.8_
  - [x] 6.2 Add `scheduler.add_job(_run_ml_weekly_training, trigger="cron", day_of_week="sun", hour=1, minute=0, id="ml_weekly_training", replace_existing=True)` inside `register_jobs()` without modifying any existing job registrations
    - _Requirements: 1.8_
  - [x] 6.3 Verify all four pre-existing scheduler jobs are unchanged and `mypy --strict` passes on `scheduler.py`
    - _Requirements: 1.8_

- [x] 7. test(sdk): property and unit tests for MLRouter
  - [x] 7.1 Create `sdk/python/tests/unit/test_ml_router.py`; write unit tests: `is_trained()` returns `False` with fewer than 500 training examples; `route()` delegates to `RuleRouter` when untrained; `training_stats()` returns a dict with the correct keys and types
    - _Requirements: 1.2, 1.3, 1.5_
  - [x] 7.2 Write property test (Hypothesis): `MLRouter.route()` never raises for any valid `messages` input — Property 1 from design §2.3
    - **Property 1: MLRouter.route() never raises**
    - **Validates: Requirements 1.4**
  - [x] 7.3 Write unit test: `routing_rule` is prefixed `"ml."` when a trained artifact with ≥ 500 samples is loaded
    - _Requirements: 1.10_
  - [x] 7.4 Verify all tests pass and coverage on `ml_router.py` is ≥ 80%
    - _Requirements: 1.1_

- [x] 8. test(backend): unit tests for MLTrainingService
  - [x] 8.1 Create `backend/tests/unit/test_ml_training.py`; write unit test: `train()` raises `InsufficientDataError` on empty DB (mock `AsyncSession` with `AsyncMock`)
    - _Requirements: 1.6_
  - [x] 8.2 Write unit test: `run_weekly_training_job()` catches all exceptions and never re-raises; verify via `pytest.raises` not triggered when underlying `train()` raises
    - _Requirements: 1.7_

- [x] 9. feat(sdk): implement ConformalPredictor and ConformalRouter
  - [x] 9.1 Create `sdk/python/axon/router/conformal.py` with module-level docstring; define `ConformalPredictionResult` dataclass with fields `covered: bool`, `q_hat: float`, `alpha: float`, `predicted_quality_lb: float`
    - _Requirements: 2.3_
  - [x] 9.2 Implement `ConformalPredictor` class with `__init__(threshold: float = 3.5)`; implement `calibrate(calibration_data: list[tuple[np.ndarray, float]], alpha: float) -> None` — compute non-conformity scores as `threshold - quality_i`, compute `q_hat = np.quantile(scores, ceil((n+1)*(1-alpha))/n, method="higher")`, store `q_hat` and `alpha`; raise `ValueError` if `calibration_data` is empty or `alpha` not in `(0, 1)`
    - _Requirements: 2.1, 2.2_
  - [x] 9.3 Implement `ConformalPredictor.predict_set(features: np.ndarray) -> ConformalPredictionResult` — raise `RuntimeError` if called before `calibrate()`; return result with `covered = (threshold - q_hat <= score)`, `predicted_quality_lb = threshold - q_hat`
    - _Requirements: 2.3_
  - [x] 9.4 Implement `ConformalRouter` class wrapping any `route()`-compatible inner router; `route()` delegates to inner router, evaluates conformal set; when `covered=False` escalates `ModelTier` one step and prefixes `routing_rule` with `"conformal_escalation."`; when uncalibrated logs structlog warning and returns inner decision unchanged; ensure `ConformalPredictor` is pickle-serializable
    - _Requirements: 2.4, 2.5, 2.7, 2.8_
  - [x] 9.5 Verify `mypy --strict` and `ruff check` pass with zero errors on `conformal.py`
    - _Requirements: 2.1_

- [x] 10. test(sdk): property and unit tests for ConformalPredictor
  - [x] 10.1 Create `sdk/python/tests/unit/test_conformal.py`; write unit tests: `calibrate()` raises `ValueError` on empty data; `calibrate()` raises `ValueError` on `alpha=0` and `alpha=1`; `predict_set()` raises `RuntimeError` before `calibrate()` is called
    - _Requirements: 2.2_
  - [x] 10.2 Write property test (Hypothesis): empirical coverage `mean(quality_i >= threshold - q_hat)` is `>= 1 - alpha` on the calibration set for any valid `calibration_data` and `alpha` in `(0.01, 0.5)` — Property 2 from design §3.1
    - **Property 2: Empirical coverage >= 1 - alpha on calibration set**
    - **Validates: Requirements 2.6, 2.9**
  - [x] 10.3 Write unit test: `ConformalRouter` delegates to inner router unchanged when uncalibrated
    - _Requirements: 2.7_
  - [x] 10.4 Write unit test: `ConformalRouter` escalates tier and prefixes `routing_rule` with `"conformal_escalation."` when `covered=False`
    - _Requirements: 2.5_
  - [x] 10.5 Verify all tests pass and coverage on `conformal.py` is ≥ 90%
    - _Requirements: 2.1_

- [x] 11. feat(sdk): add ProviderResponse dataclass and lazy import guards
  - [x] 11.1 Create `sdk/python/axon/providers/__init__.py` with module-level docstring; define `ProviderResponse` dataclass with fields `content: str`, `input_tokens: int`, `output_tokens: int`, `model: str`, `provider: str`, `raw_response: dict[str, Any]` (with inline `# Any:` comment)
    - _Requirements: 4.3, 4.10_
  - [x] 11.2 Implement `__getattr__(name: str) -> Any` lazy import guard returning `BedrockAdapter` or `VertexAdapter` on demand; raise `AttributeError` for unknown names
    - _Requirements: 4.9_
  - [x] 11.3 Verify `mypy --strict` passes on `providers/__init__.py`
    - _Requirements: 4.9, 4.10_

- [x] 12. feat(sdk): implement BedrockAdapter
  - [x] 12.1 Create `sdk/python/axon/providers/bedrock.py` with module-level docstring; implement `BedrockAdapter.__init__(region_name: str | None = None)` — guard `import boto3` inside `__init__`, raise `AxonDependencyError` with install instructions if missing
    - _Requirements: 4.1, 4.7_
  - [x] 12.2 Implement `complete(messages: list[dict[str, Any]], model: str, **kwargs: Any) -> ProviderResponse` — select request body shape by `model.startswith()` prefix: Amazon Titan (`amazon.titan` → `{"inputText": ...}`), Anthropic Claude via Bedrock (`anthropic.claude` → Anthropic Messages API format), Meta Llama via Bedrock (`meta.llama` → `{"prompt": ..., "max_gen_len": ...}`); call `InvokeModel`; extract token counts per family's response shape; return `ProviderResponse(provider="bedrock", ...)`
    - _Requirements: 4.1, 4.2, 4.3_
  - [x] 12.3 Add `boto3` to `sdk/python/pyproject.toml` under `[project.optional-dependencies]` with key `"bedrock"`
    - _Requirements: 4.7_
  - [x] 12.4 Verify `mypy --strict --ignore-missing-imports` passes on `bedrock.py`
    - _Requirements: 4.1_

- [x] 13. feat(sdk): implement VertexAdapter
  - [x] 13.1 Create `sdk/python/axon/providers/vertex.py` with module-level docstring; implement `VertexAdapter.__init__(project: str | None = None, location: str = "us-central1")` — guard `import google.cloud.aiplatform` inside `__init__`, raise `AxonDependencyError` with install instructions if missing
    - _Requirements: 4.4, 4.8_
  - [x] 13.2 Implement `complete(messages: list[dict[str, Any]], model: str, **kwargs: Any) -> ProviderResponse` — call `generateContent` API; extract `response.usage_metadata.prompt_token_count` and `response.usage_metadata.candidates_token_count`; support `gemini-1.5-pro`, `gemini-1.5-flash`, `gemini-1.0-pro`; return `ProviderResponse(provider="vertex", ...)`
    - _Requirements: 4.4, 4.5, 4.6_
  - [x] 13.3 Add `google-cloud-aiplatform` to `sdk/python/pyproject.toml` under `[project.optional-dependencies]` with key `"vertex"`
    - _Requirements: 4.8_
  - [x] 13.4 Verify `mypy --strict --ignore-missing-imports` passes on `vertex.py`
    - _Requirements: 4.4_

- [x] 14. test(sdk): unit tests for BedrockAdapter and VertexAdapter
  - [x] 14.1 Create `sdk/python/tests/unit/test_bedrock_adapter.py` — mock `boto3.client` at HTTP transport layer; test raises `AxonDependencyError` when `boto3` is missing; test correct token extraction from Titan response shape; test correct token extraction from Claude-via-Bedrock response shape; test correct token extraction from Llama response shape
    - _Requirements: 4.1, 4.2, 4.3, 4.7_
  - [x] 14.2 Create `sdk/python/tests/unit/test_vertex_adapter.py` — mock `google.cloud.aiplatform`; test raises `AxonDependencyError` when package is missing; test correct token extraction from `usage_metadata`
    - _Requirements: 4.4, 4.5, 4.6, 4.8_
  - [x] 14.3 Verify coverage ≥ 80% on `bedrock.py` and `vertex.py`
    - _Requirements: 4.1, 4.4_

- [x] 15. feat(sdk): implement plugin ABC hierarchy and PluginRegistry
  - [x] 15.1 Create `sdk/python/axon/plugins/base.py` with module-level docstring; define `CompressionPlugin(ABC)` with abstract `compress(segments: list[str], **kwargs: Any) -> list[str]`; define `RoutingPlugin(ABC)` with abstract `route(messages: list[dict[str, Any]], requested_model: str, **kwargs: Any) -> RoutingDecision | None`; define `ArtifactClassifierPlugin(ABC)` with abstract `classify(content: str, **kwargs: Any) -> ArtifactType | None`; all with Google-style docstrings
    - _Requirements: 5.1_
  - [x] 15.2 Create `sdk/python/axon/plugins/registry.py` with module-level docstring; implement `PluginRegistry` singleton (`_instance: PluginRegistry | None = None`); implement `register(plugin) -> None` raising `TypeError` for non-plugin arguments; implement `get_compression_plugins()`, `get_routing_plugins()`, `get_classifier_plugins()`, `clear()` methods
    - _Requirements: 5.2, 5.3_
  - [x] 15.3 Create `sdk/python/axon/plugins/__init__.py` — export `CompressionPlugin`, `RoutingPlugin`, `ArtifactClassifierPlugin`, `PluginRegistry`, `PluginLoader`
    - _Requirements: 5.8_
  - [x] 15.4 Verify `mypy --strict` passes with zero errors on `plugins/base.py` and `plugins/registry.py`
    - _Requirements: 5.1, 5.2_

- [x] 16. feat(sdk): implement PluginLoader via entry-point discovery
  - [x] 16.1 Create `sdk/python/axon/plugins/loader.py` with module-level docstring; implement `PluginLoader` class with Google-style class docstring
    - _Requirements: 5.4_
  - [x] 16.2 Implement `load_all(registry: PluginRegistry) -> int` — iterate `importlib.metadata.entry_points(group="axon.plugins")`, instantiate each entry point class, call `registry.register(instance)`, log each successful load via structlog; catch `Exception` per plugin and continue (non-fatal); return success count
    - _Requirements: 5.4, 5.5_
  - [x] 16.3 Verify `mypy --strict` passes with zero errors on `loader.py`
    - _Requirements: 5.4_

- [x] 17. test(sdk): property and unit tests for plugin system
  - [x] 17.1 Create `sdk/python/tests/unit/test_plugin_registry.py` — write unit tests: `register()` raises `TypeError` for non-plugin argument (Property 6 from design §6.2); registration succeeds for valid `CompressionPlugin`, `RoutingPlugin`, `ArtifactClassifierPlugin` instances; `clear()` empties all three registries; duplicate name raises `AxonConfigError` if applicable
    - **Property 6: TypeError raised for non-plugin arguments**
    - **Validates: Requirements 5.3**
    - _Requirements: 5.2, 5.3_
  - [x] 17.2 Create `sdk/python/tests/unit/test_plugin_loader.py` — write unit tests: `load_all()` skips failing plugins and continues; `load_all()` returns correct success count; `load_all()` integrates correctly with mock `entry_points`
    - _Requirements: 5.4, 5.5_
  - [x] 17.3 Verify coverage ≥ 90% on `registry.py` and ≥ 80% on `loader.py`
    - _Requirements: 5.2, 5.4_

- [x] 18. feat(sdk): implement BatchRouter and BatchJobRecord
  - [x] 18.1 Create `sdk/python/axon/batch/__init__.py` with module-level docstring
    - _Requirements: 3.1_
  - [x] 18.2 Create `sdk/python/axon/batch/batch_router.py` with module-level docstring; define `BatchJobStatus(StrEnum)` with values `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `EXPIRED`; define `BatchJobRecord` dataclass with fields `job_id: str`, `provider: str`, `status: str`, `submitted_at: datetime`, `span_count: int`, `estimated_completion_at: datetime | None`
    - _Requirements: 3.4_
  - [x] 18.3 Implement `BatchRouter` class with `__init__(openai_client=None, anthropic_client=None)`; implement `async def submit_batch(spans: list[InferenceSpan], provider: str) -> BatchJobRecord` — filter `batch_eligible=True` spans; dispatch to OpenAI `POST /v1/batches` or Anthropic `POST /v1/messages/batches`; on API failure log error via structlog and return `BatchJobRecord(status=FAILED)`; never raises
    - _Requirements: 3.1, 3.2, 3.3, 3.7_
  - [x] 18.4 Implement `async def poll_and_collect(db: AsyncSession, provider_client: Any) -> int` — poll all `PENDING`/`IN_PROGRESS` jobs, update status via `JobTracker`, return count of newly `COMPLETED` jobs; never raises
    - _Requirements: 3.8_
  - [x] 18.5 Verify `mypy --strict` passes with zero errors on `batch_router.py`
    - _Requirements: 3.1_

- [x] 19. feat(sdk): implement JobTracker for PostgreSQL persistence
  - [x] 19.1 Create `sdk/python/axon/batch/job_tracker.py` with module-level docstring; define `BatchJobORM(Base)` matching the `batch_jobs` table from migration 0003: `id: Mapped[uuid.UUID]` (PK), `job_id: Mapped[str]` (unique index), `provider: Mapped[str]`, `status: Mapped[str]`, `submitted_at: Mapped[datetime]`, `span_count: Mapped[int]`, `estimated_completion_at: Mapped[datetime | None]`, `created_at: Mapped[datetime]` (server_default)
    - _Requirements: 3.5_
  - [x] 19.2 Implement `JobTracker` class with async methods: `create(db, record: BatchJobRecord) -> BatchJobRecord`, `get(db, job_id: str) -> BatchJobRecord | None`, `update_status(db, job_id: str, status: str) -> None` (validates `status ∈ BatchJobStatus`, raises `ValueError` for invalid values), `list_pending(db) -> list[BatchJobRecord]` (returns `PENDING` and `IN_PROGRESS` rows)
    - _Requirements: 3.5, 3.6_
  - [x] 19.3 Verify `mypy --strict` passes with zero errors on `job_tracker.py`
    - _Requirements: 3.5_

- [x] 20. test(sdk): unit tests for BatchRouter and JobTracker
  - [x] 20.1 Create `sdk/python/tests/unit/test_batch_router.py` — write unit tests: `submit_batch()` filters out non-eligible spans (`batch_eligible=False`); `submit_batch()` logs error and returns `FAILED` record on API failure; `poll_and_collect()` returns `0` on empty job list
    - _Requirements: 3.3, 3.7, 3.8_
  - [x] 20.2 Write property test (Hypothesis): `route_or_immediate()` returns a `Future` for `batch_eligible=True` spans — validates BatchRouter handles eligible spans
    - **Property (BatchRouter): batch_eligible=True spans return Future**
    - **Validates: Requirements 3.1**
  - [x] 20.3 Create `sdk/python/tests/unit/test_job_tracker.py` — write unit tests: `update_status()` raises `ValueError` for invalid status values not in `BatchJobStatus`; `list_pending()` returns rows with `PENDING` and `IN_PROGRESS` status; mock `AsyncSession` with `AsyncMock`
    - _Requirements: 3.6_
  - [x] 20.4 Verify coverage ≥ 80% on `batch_router.py` and `job_tracker.py`
    - _Requirements: 3.1, 3.5_

- [x] 21. feat(backend): implement CostPredictor and POST /v1/predictions/cost
  - [x] 21.1 Create `backend/axon_backend/services/cost_predictor.py` with module-level docstring; implement `CostPredictor` using `Decimal` arithmetic throughout; implement `compute_point_estimate(model, estimated_input_tokens, estimated_output_tokens) -> Decimal` from `PROVIDER_PRICING`; raise `KeyError` if model not found
    - _Requirements: 6.3, 6.7, 6.8_
  - [x] 21.2 Implement 90% prediction interval logic: query up to 1000 historical `InferenceSpanRecord.cost_usd` rows for the same model within 30 days; when fewer than 10 rows return `±50%` fallback; when ≥ 10 rows scale historical costs to requested token volume and use 5th/95th percentiles; enforce `lower_bound <= point_estimate <= upper_bound` post-condition, fall back to `±50%` if violated
    - _Requirements: 6.4, 6.9_
  - [x] 21.3 Create `backend/axon_backend/api/v1/predictions.py` with module-level docstring; define `CostPredictionResponse` Pydantic model; implement `POST /v1/predictions/cost` guarded by `require_role("engineer")`; return HTTP 422 when `estimated_input_tokens < 0` or `estimated_output_tokens < 0`; return HTTP 404 when model not in pricing table
    - _Requirements: 6.1, 6.2, 6.5, 6.6, 6.7_
  - [x] 21.4 Add predictions router to `backend/axon_backend/api/v1/router.py`
    - _Requirements: 6.1_
  - [x] 21.5 Verify `mypy --strict` passes with zero errors on `cost_predictor.py` and `predictions.py`
    - _Requirements: 6.3_

- [x] 22. feat(backend): implement AnomalyDetector and anomaly_scan job
  - [x] 22.1 Create `backend/axon_backend/services/anomaly_detector.py` with module-level docstring; define `AnomalyAlert` dataclass with fields `feature_tag: str`, `metric: str`, `direction: str`, `observed_value: float`, `upper_fence: float`, `lower_fence: float`, `detected_at: datetime`
    - _Requirements: 7.4_
  - [x] 22.2 Implement `AnomalyDetector` class with `async def run_scan(db: AsyncSession) -> list[AnomalyAlert]` — query all `feature_tag` values with ≥ 7 days of `AttributionHourlyRecord` data; compute `Q1`, `Q3`, `IQR = Q3 - Q1`, `upper_fence = Q3 + 1.5*IQR`, `lower_fence = Q1 - 1.5*IQR`; compare most recent hourly value against fences; skip feature_tags with < 7 days data; emit `AnomalyAlert` for violations; catch all exceptions and return `[]` on error; never raises
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.8, 7.9_
  - [x] 22.3 Add `async def _run_anomaly_scan() -> None` to `backend/axon_backend/workers/scheduler.py`; add `scheduler.add_job(_run_anomaly_scan, trigger="interval", hours=6, id="anomaly_scan", replace_existing=True)` inside `register_jobs()` without modifying existing jobs; emit structlog warning per `AnomalyAlert` with all required fields
    - _Requirements: 7.6, 7.7_
  - [x] 22.4 Verify `mypy --strict` passes with zero errors on `anomaly_detector.py` and updated `scheduler.py`
    - _Requirements: 7.1_

- [x] 23. test(backend): property and unit tests for CostPredictor and AnomalyDetector
  - [x] 23.1 Create `backend/tests/unit/test_cost_predictor.py` — write unit test: returns `±50%` fallback when fewer than 10 historical rows; write unit test: raises `KeyError` on unknown model
    - _Requirements: 6.4, 6.7_
  - [x] 23.2 Write property test (Hypothesis): `lower_bound <= point_estimate <= upper_bound` holds for all valid `(model, estimated_input_tokens, estimated_output_tokens)` inputs — Property 3 from design §7
    - **Property 3: lower_bound <= point_estimate <= upper_bound**
    - **Validates: Requirements 6.9**
  - [x] 23.3 Create `backend/tests/unit/test_anomaly_detector.py` — write unit tests: normal data (no spikes) returns no alerts; spike value above `upper_fence` is correctly detected; `run_scan()` returns `[]` on exception (never raises)
    - _Requirements: 7.3, 7.5, 7.8_
  - [x] 23.4 Write property test (Hypothesis): computed `IQR` matches `numpy.percentile`-based calculation — Property 4 from design §8
    - **Property 4: IQR matches numpy percentile calculation**
    - **Validates: Requirements 7.2**
  - [x] 23.5 Write unit test: zero-variance data (constant hourly cost) produces `IQR = 0` and flags any value above the constant as `"high"` anomaly
    - _Requirements: 7.9_
  - [x] 23.6 Verify coverage ≥ 80% on `cost_predictor.py` and `anomaly_detector.py`
    - _Requirements: 6.3, 7.1_

- [x] 24. feat(sdk): implement TelemetryReporter (disabled by default)
  - [x] 24.1 Create `sdk/python/axon/core/telemetry_reporter.py` with module-level docstring; define `TelemetryPayload` Pydantic v2 model with fields `sdk_version: str`, `python_version: str`, `sample_count: int`, `p50_cost_usd: str`, `p95_cost_usd: str`, `p50_compression_ratio: float`, `p95_compression_ratio: float`, `avg_routing_accuracy: float`, `submitted_at: datetime`; no PII fields
    - _Requirements: 8.2, 8.4_
  - [x] 24.2 Implement `TelemetryReporter` class with `__init__(enabled: bool = False)` — when `enabled=False` (default) do nothing; when `enabled=True` log structlog info event describing what data is collected; support `AXON_TELEMETRY_ENABLED` env var override
    - _Requirements: 8.1, 8.5_
  - [x] 24.3 Implement `submit(payload: TelemetryPayload) -> bool` — no-op returning `False` when `enabled=False`; when `enabled=True` POST to `/v1/benchmarks/submit` via `httpx` with 5s timeout; return `True` on HTTP 200–299; return `False` and log structlog warning on any failure; never raises
    - _Requirements: 8.3_
  - [x] 24.4 Create `sdk/python/tests/unit/test_telemetry_reporter.py` — write unit test: zero network calls made when `enabled=False` (Property 5); write unit test: `enabled=True` submits correct aggregate fields; write unit test: payload never includes `feature_tag` or prompt content; write unit test: fails silently on network error; write unit test: `AXON_TELEMETRY_ENABLED=false` keeps reporter disabled
    - **Property 5: 0 network calls when disabled**
    - **Validates: Requirements 8.1**
    - _Requirements: 8.1, 8.2, 8.3_
  - [x] 24.5 Verify coverage ≥ 90% on `telemetry_reporter.py` and `mypy --strict` passes
    - _Requirements: 8.1_

- [x] 25. feat(backend+dashboard): add benchmarks API, BenchmarkRegistry page, community + research + docs
  - [x] 25.1 Create `backend/axon_backend/api/v1/benchmarks.py` with module-level docstring; implement `POST /v1/benchmarks/submit` (public, no auth, HTTP 201); implement `GET /v1/benchmarks` (public, HTTP 200, `limit` param, default 50 max 500, ordered by `submitted_at` desc); add benchmarks router to `backend/axon_backend/api/v1/router.py`
    - _Requirements: 8.6, 8.7_
  - [x] 25.2 Create `dashboard/src/pages/BenchmarkRegistry.tsx` — public route `/benchmarks`; table with columns `submitted_at`, `sdk_version`, `sample_count`, `p50_cost_usd`, `p95_cost_usd`, `p50_compression_ratio`, `avg_routing_accuracy` when data exists; empty-state message `"No benchmark data yet. Be the first to submit!"` with link to `docs/production-validation.md` when no records; prominent disclaimer `"All data submitted by users. Axon does not verify individual submissions."` in `text-gray-400`; add to `App.tsx` routes and `Sidebar.tsx` navigation with label `"Benchmarks"` at `/benchmarks`; no `X-Axon-API-Key` header required
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_
  - [x] 25.3 Create `community/GOVERNANCE.md` — maintainer responsibilities, decision-making process, RFC process linking to `RFC_TEMPLATE.md`, code of conduct reference, release cadence; create `community/RFC_TEMPLATE.md` — sections: Summary, Motivation, Detailed Design, Drawbacks, Alternatives, Unresolved Questions; create `community/scripts/setup_contributor.sh` — check Python ≥ 3.11 and Node ≥ 20, create `.venv/`, install SDK/backend/dashboard deps, run `pre-commit install`, print success message
    - _Requirements: 10.1, 10.2, 10.3_
  - [x] 25.4 Create `docs/launch/HN_LAUNCH.md` — first 5 lines MUST contain the exact line `"Do not post until production validation data is collected"`; draft Show HN post with title, description, GitHub and docs links, benchmark results section marked `[PLACEHOLDER: insert production data]`; create `docs/launch/BLOG_POST_DRAFT.md`
    - _Requirements: 11.1, 11.2_
  - [x] 25.5 Create `research/paper/axon_paper.md` — arXiv-ready structure (Abstract, Introduction, Related Work, System Design, Evaluation, Conclusion) with `[TBD]` placeholders in evaluation section; create `research/notebooks/compression_analysis.ipynb` — skeleton with cleared output cells; no fabricated benchmark numbers anywhere
    - _Requirements: 11.1_
  - [x] 25.6 Create `docs/ml-router-guide.md`, `docs/batch-routing.md` (document ~50% cost reduction as expected, not measured), `docs/provider-expansion.md`, `docs/plugin-development.md` (include example `pyproject.toml` entry point), `docs/production-validation.md`
    - _Requirements: 3.9, 5.8_
  - [x] 25.7 Add `welcome-contributor` job to `.github/workflows/ci.yml` using `actions/first-interaction@v1` to post a welcome comment on first-time contributor PRs
    - _Requirements: 10.4_
  - [x] 25.8 Update `backend/axon_backend/core/config.py` version string to `"0.5.0"`; update `README.md` — mark Phase 5 in roadmap, add link to `research/paper/axon_paper.md`
    - _Requirements: 11.1_
  - [x] 25.9 Run full validation checklist: `mypy sdk/python/axon --strict` → 0 errors; `mypy backend/axon_backend --strict` → 0 errors; `ruff check sdk/python/axon sdk/python/tests` → clean; `pytest sdk/python/tests --cov=axon --cov-fail-under=85` → passes; `pytest backend/tests --cov=axon_backend --cov-fail-under=75` → passes; `cd dashboard && npm run typecheck` → 0 errors
    - _Requirements: 1.1, 2.1, 3.1, 4.1, 5.1, 6.1, 7.1, 8.1, 9.1_

- [x] 26. Checkpoint — Ensure all 481+ tests pass, ask the user if questions arise.
  - Verify `git log --oneline` shows exactly 25 new commits since Phase 4 tag
  - Confirm all pre-existing Phase 1–4 tests still pass with zero regressions

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP build
- Each task references specific requirements for traceability
- Property tests use Hypothesis; unit tests use pytest with AsyncMock for async DB sessions
- Monetary values use `Decimal` throughout — no `float` for currency per ADR-006
- All new Python files require module-level docstrings per workspace standards
- `mypy --strict` must pass at every commit; `ruff check` must be clean
- The `TelemetryReporter` disabled-by-default requirement (Req 8.1) is non-negotiable
- No fabricated benchmark numbers anywhere in the codebase or documents
- Phase 1–4 code is untouched except for the narrow additions listed in the design

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "11.1", "11.2", "15.1", "15.2", "15.3"] },
    { "id": 1, "tasks": ["1.4", "2.1", "2.2", "3.1", "3.2", "3.3", "11.3", "15.4", "16.1", "16.2"] },
    { "id": 2, "tasks": ["2.3", "3.4", "4.1", "4.2", "4.3", "4.4", "12.1", "12.2", "12.3", "13.1", "13.2", "13.3", "16.3", "17.1"] },
    { "id": 3, "tasks": ["4.5", "5.1", "5.2", "5.3", "9.1", "9.2", "9.3", "9.4", "12.4", "13.4", "14.1", "14.2", "17.2", "18.1", "18.2", "18.3", "18.4"] },
    { "id": 4, "tasks": ["5.4", "6.1", "6.2", "9.5", "10.1", "14.3", "17.3", "18.5", "19.1", "19.2"] },
    { "id": 5, "tasks": ["6.3", "7.1", "8.1", "10.2", "10.3", "10.4", "19.3", "20.1", "20.2", "20.3", "21.1", "21.2", "21.3", "21.4"] },
    { "id": 6, "tasks": ["7.2", "7.3", "8.2", "10.5", "20.4", "21.5", "22.1", "22.2", "22.3", "24.1", "24.2", "24.3"] },
    { "id": 7, "tasks": ["7.4", "22.4", "23.1", "23.3", "24.4"] },
    { "id": 8, "tasks": ["23.2", "23.4", "23.5", "24.5"] },
    { "id": 9, "tasks": ["23.6", "25.1", "25.2", "25.3", "25.4", "25.5", "25.6", "25.7", "25.8"] },
    { "id": 10, "tasks": ["25.9"] }
  ]
}
```
