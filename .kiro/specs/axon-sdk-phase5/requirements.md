# Requirements Document

## Introduction

Phase 5 of the Axon platform adds seven technical features (Track A) and five credibility and
community deliverables (Track B) on top of the fully validated Phase 4 foundation.

Track A introduces ML-based model routing with conformal prediction quality guarantees, batch
routing integration with OpenAI and Anthropic batch APIs, provider expansion to AWS Bedrock and
Google Vertex AI, a plugin system for extensibility, predictive cost modeling, and IQR-based
anomaly detection. All Track A features extend existing Phase 1–4 code only through the
explicitly listed new files and the narrow additions to `scheduler.py`.

Track B adds production telemetry collection (opt-in, aggregate-only), a public benchmark
registry dashboard page, community governance infrastructure, launch and blog content drafts, and
an arXiv-ready technical paper with honest evaluation placeholders. No fabricated benchmark
numbers are permitted anywhere in the codebase or documents.

All 481 existing tests must continue to pass at every commit. Overall Python SDK coverage must
remain at or above 85%. New modules must individually reach at least 80% coverage. The
`TelemetryReporter` is disabled by default and requires explicit user opt-in — this is a
hard, non-negotiable requirement.

---

## Glossary

- **MLRouter**: The machine-learning-based model router implemented in
  `sdk/python/axon/router/ml_router.py`. Uses logistic regression trained on historical
  routing decisions. Falls back to `RuleRouter` when the training set contains fewer than
  500 labeled examples.
- **RuleRouter**: The existing Phase 3 rule-based router in
  `sdk/python/axon/router/rule_router.py`. Used as fallback by `MLRouter`.
- **ConformalPredictor**: The split conformal prediction calibration module in
  `sdk/python/axon/router/conformal.py`. Implements the Angelopoulos & Bates (2021) algorithm.
- **ConformalRouter**: A router wrapper that enforces the statistical coverage guarantee
  `P(quality >= threshold) >= 1 - alpha` using conformal prediction.
- **BatchRouter**: The batch submission router in `sdk/python/axon/batch/batch_router.py`.
  Routes eligible spans to OpenAI Batch API or Anthropic Message Batches for 50% cost reduction.
- **JobTracker**: The PostgreSQL-backed batch job persistence layer in
  `sdk/python/axon/batch/job_tracker.py`.
- **BedrockAdapter**: The AWS Bedrock provider adapter in
  `sdk/python/axon/providers/bedrock.py`.
- **VertexAdapter**: The Google Vertex AI provider adapter in
  `sdk/python/axon/providers/vertex.py`.
- **CompressionPlugin**: An abstract base class (ABC) for compression plugins in
  `sdk/python/axon/plugins/base.py`.
- **RoutingPlugin**: An abstract base class (ABC) for routing plugins in
  `sdk/python/axon/plugins/base.py`.
- **ArtifactClassifierPlugin**: An abstract base class (ABC) for artifact classifier plugins in
  `sdk/python/axon/plugins/base.py`.
- **PluginRegistry**: The in-process plugin registry in `sdk/python/axon/plugins/registry.py`.
- **PluginLoader**: The entry-point-based plugin loader in `sdk/python/axon/plugins/loader.py`.
- **CostPredictor**: The predictive cost modeling service in
  `backend/axon_backend/services/cost_predictor.py`. Returns a point estimate and 90% prediction
  interval for a request's cost.
- **AnomalyDetector**: The IQR-based anomaly detection service in
  `backend/axon_backend/services/anomaly_detector.py`. Uses a rolling 7-day window.
- **TelemetryReporter**: The opt-in aggregate telemetry reporter in
  `sdk/python/axon/core/telemetry_reporter.py`. Disabled by default.
- **BenchmarkRegistry**: The public benchmark registry dashboard page and backend API
  (`backend/axon_backend/api/v1/benchmarks.py`, `dashboard/src/pages/BenchmarkRegistry.tsx`).
- **Split Conformal Prediction**: The method from Angelopoulos & Bates (2021) that splits a
  calibration dataset into proper training and calibration sets to compute quantile-based
  prediction sets with finite-sample marginal coverage guarantees.
- **Coverage Guarantee**: The statistical property
  `P(quality >= threshold) >= 1 - alpha` guaranteed by `ConformalRouter`, where `alpha`
  is the miscoverage rate set by the caller (default `0.1` for 90% coverage).
- **IQR**: Interquartile range — `Q3 - Q1` of a metric distribution, used by
  `AnomalyDetector` to define anomaly bounds as `[Q1 - 1.5*IQR, Q3 + 1.5*IQR]`.
- **APScheduler**: The `apscheduler` library used by the backend for background jobs. Already
  present in the Phase 4 codebase.

---

## Requirements

### Requirement 1: ML Model Router V2

**User Story:** As an engineering lead, I want the Axon router to learn optimal model
assignments from historical routing decisions, so that routing accuracy improves automatically
over time without manual rule tuning.

#### Acceptance Criteria

1. THE `MLRouter` SHALL implement logistic regression (using scikit-learn's
   `LogisticRegression`) to predict the optimal `ModelTier` from features derived from
   the incoming `messages` list and `requested_model` string.

2. WHEN the training dataset contains fewer than 500 labeled routing examples,
   THE `MLRouter` SHALL delegate all routing decisions to an injected `RuleRouter`
   instance and log a structlog info event indicating the fallback reason.

3. WHEN the training dataset contains 500 or more labeled routing examples,
   THE `MLRouter` SHALL use the trained logistic regression model to make routing
   decisions, overriding rule-based routing.

4. THE `MLRouter.route()` method SHALL have the same signature as `RuleRouter.route()`:
   `route(messages, requested_model, override_task_type=None) -> RoutingDecision`.
   It SHALL never raise; any unhandled exception MUST fall back to `RuleRouter`.

5. THE `MLTrainingService` in `backend/axon_backend/services/ml_training.py` SHALL
   expose an `async def train(db: AsyncSession) -> MLModelArtifact` method that queries
   historical `InferenceSpanRecord` rows with non-null `routing_decision`, extracts
   features, trains a `LogisticRegression` model, and returns a serialized
   `MLModelArtifact` dataclass containing the trained model, feature names, training
   sample count, and training timestamp.

6. IF the training query returns zero rows, THEN THE `MLTrainingService.train()` SHALL
   raise an `InsufficientDataError` with a descriptive message.

7. THE `MLTrainingService` SHALL expose an `async def run_weekly_training_job(db) -> None`
   method that calls `train()`, persists the artifact to the filesystem at a
   configurable path, logs the result via structlog, and catches all exceptions
   (never re-raises).

8. THE weekly ML training job SHALL be registered in `backend/axon_backend/workers/scheduler.py`
   with `trigger="cron", day_of_week="sun", hour=1, minute=0, id="ml_weekly_training"`.

9. THE `MLRouter` SHALL accept an optional `model_artifact_path: str | None` constructor
   parameter. WHEN provided, it SHALL attempt to load a previously trained
   `MLModelArtifact` from that path at construction time. IF loading fails, THE
   `MLRouter` SHALL log a warning and proceed in fallback mode.

10. WHEN a routing decision is made by the `MLRouter`,
    THE returned `RoutingDecision.routing_rule` field SHALL be prefixed with `"ml."` to
    distinguish ML-generated decisions from rule-generated decisions.

11. THE `sklearn` package SHALL be listed as an optional dependency in
    `sdk/python/axon`'s `pyproject.toml` under `[project.optional-dependencies]`
    with key `"ml"`. IF `sklearn` is not installed and `MLRouter` is instantiated,
    THE `MLRouter` SHALL raise an `AxonDependencyError` with instructions to install
    `axon-sdk[ml]`.

---

### Requirement 2: Conformal Prediction Quality Guarantees

**User Story:** As a platform engineer, I want the router to provide a statistically valid
quality coverage guarantee on every routing decision, so that I can set an acceptable
miscoverage rate and rely on the guarantee being mathematically correct.

#### Acceptance Criteria

1. THE `ConformalPredictor` in `sdk/python/axon/router/conformal.py` SHALL implement
   split conformal prediction as described in Angelopoulos & Bates (2021):
   given a calibration set of `(features, quality_score)` pairs, it SHALL compute
   the `ceil((n+1)*(1-alpha))/n`-quantile of non-conformity scores on the held-out
   calibration split and store it as the conformal threshold `q_hat`.

2. THE `ConformalPredictor.calibrate(calibration_data, alpha)` method SHALL:
   - Accept `calibration_data: list[tuple[np.ndarray, float]]` (feature vectors paired
     with observed quality scores) and `alpha: float` in `(0, 1)`.
   - Compute non-conformity scores as `score_i = threshold - quality_i` for each
     calibration example.
   - Compute `q_hat` using the finite-sample-corrected quantile formula
     `np.quantile(scores, ceil((n+1)*(1-alpha))/n, method="higher")`.
   - Store `q_hat` and `alpha` as instance attributes.
   - Raise `ValueError` if `calibration_data` is empty or `alpha` not in `(0, 1)`.

3. THE `ConformalPredictor.predict_set(features)` method SHALL return a
   `ConformalPredictionResult` dataclass with fields `covered: bool`,
   `q_hat: float`, `alpha: float`, and `predicted_quality_lb: float`
   (the lower bound on predicted quality = `threshold - q_hat`).

4. THE `ConformalRouter` in `sdk/python/axon/router/conformal.py` SHALL wrap any
   router implementing the `route()` interface and, after routing, evaluate the
   conformal prediction set for the selected model.

5. WHEN `ConformalRouter.route()` is called:
   - IF `covered=True` (the conformal prediction set covers the quality threshold),
     THE `ConformalRouter` SHALL return the inner router's `RoutingDecision` unchanged.
   - IF `covered=False`, THE `ConformalRouter` SHALL escalate to the next model tier
     (one step up in `ModelTier`) and return a `RoutingDecision` with
     `routing_rule` prefixed with `"conformal_escalation."`.

6. THE coverage guarantee SHALL be maintained:
   `P(quality >= threshold) >= 1 - alpha` where `alpha` is the miscoverage rate
   passed to `ConformalPredictor.calibrate()`. This guarantee holds in the
   marginal (average) sense over the calibration distribution.

7. IF `ConformalRouter.route()` is called before `ConformalPredictor.calibrate()` has
   been called, THEN THE `ConformalRouter` SHALL delegate directly to the inner router
   without applying conformal logic and SHALL log a structlog warning.

8. THE `ConformalPredictor` SHALL be serializable via `pickle` so that a calibrated
   instance can be persisted alongside the `MLModelArtifact`.

9. FOR ALL valid `calibration_data` lists with `n >= 1` and `alpha` in `(0.01, 0.5)`,
   THE empirical coverage on the calibration data
   `mean(quality_i >= threshold - q_hat for i in calibration)` SHALL be
   `>= 1 - alpha`. (Round-trip calibration–coverage correctness property.)

---

### Requirement 3: Batch Routing Integration

**User Story:** As an engineering lead, I want spans tagged as batch-eligible to be
automatically submitted to provider batch APIs, so that I can achieve up to 50% cost
reduction on non-latency-sensitive workloads.

#### Acceptance Criteria

1. THE `BatchRouter` in `sdk/python/axon/batch/batch_router.py` SHALL inspect incoming
   `InferenceSpan` objects and, WHEN `batch_eligible=True`, submit the request to the
   appropriate provider batch API instead of the real-time API.

2. THE `BatchRouter` SHALL support OpenAI Batch API (`POST /v1/batches`) and Anthropic
   Message Batches API. WHEN `provider == "openai"`, THE `BatchRouter` SHALL use the
   OpenAI batch endpoint. WHEN `provider == "anthropic"`, THE `BatchRouter` SHALL use
   the Anthropic batch endpoint.

3. THE `BatchRouter` SHALL not submit requests with `batch_eligible=False` to any batch
   API. Such requests SHALL be passed through unchanged to the real-time API.

4. THE `BatchRouter.submit_batch(spans: list[InferenceSpan], provider: str) -> BatchJobRecord`
   method SHALL return a `BatchJobRecord` dataclass with fields: `job_id: str`,
   `provider: str`, `status: str`, `submitted_at: datetime`, `span_count: int`,
   `estimated_completion_at: datetime | None`.

5. THE `JobTracker` in `sdk/python/axon/batch/job_tracker.py` SHALL persist
   `BatchJobRecord` instances to PostgreSQL and expose:
   - `async def create(db, record: BatchJobRecord) -> BatchJobRecord`
   - `async def get(db, job_id: str) -> BatchJobRecord | None`
   - `async def update_status(db, job_id: str, status: str) -> None`
   - `async def list_pending(db) -> list[BatchJobRecord]`

6. THE `JobTracker.update_status()` SHALL only accept status values from the
   `BatchJobStatus` enum: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `EXPIRED`.

7. IF the batch API call fails for any reason, THE `BatchRouter` SHALL log the error
   via structlog and fall back to submitting the request via the real-time API.
   It SHALL never raise an exception to the caller.

8. THE `BatchRouter` SHALL expose a `async def poll_and_collect(db, provider_client) -> int`
   method that checks all `PENDING` and `IN_PROGRESS` jobs, updates their status, and
   returns the count of newly `COMPLETED` jobs.

9. THE expected cost reduction for batch-routed spans SHALL be documented as
   approximately 50% in `docs/batch-routing.md`. No fabricated cost reduction data
   SHALL be presented as measured results without actual production data.

---

### Requirement 4: Provider Expansion

**User Story:** As a platform engineer, I want to route LLM requests to AWS Bedrock and
Google Vertex AI, so that I can use enterprise cloud provider integrations with existing
Axon instrumentation.

#### Acceptance Criteria

1. THE `BedrockAdapter` in `sdk/python/axon/providers/bedrock.py` SHALL implement a
   `complete(messages, model, **kwargs) -> ProviderResponse` method that calls the
   AWS Bedrock `InvokeModel` API via `boto3`.

2. THE `BedrockAdapter` SHALL translate between the Axon message format
   (`list[dict[str, Any]]`) and the AWS Bedrock request body format for
   supported model families: Amazon Titan, Anthropic Claude (via Bedrock), and
   Meta Llama (via Bedrock).

3. THE `BedrockAdapter` SHALL extract token counts from the Bedrock response object
   and return them in a `ProviderResponse` dataclass with fields:
   `content: str`, `input_tokens: int`, `output_tokens: int`, `model: str`,
   `provider: str` (always `"bedrock"`), `raw_response: dict[str, Any]`.

4. THE `VertexAdapter` in `sdk/python/axon/providers/vertex.py` SHALL implement a
   `complete(messages, model, **kwargs) -> ProviderResponse` method that calls the
   Google Vertex AI `generateContent` API via `google-cloud-aiplatform`.

5. THE `VertexAdapter` SHALL support `gemini-1.5-pro`, `gemini-1.5-flash`, and
   `gemini-1.0-pro` model identifiers.

6. THE `VertexAdapter` SHALL extract token counts from the Vertex AI response and
   return them in the same `ProviderResponse` dataclass as `BedrockAdapter`.

7. IF `boto3` is not installed, THE `BedrockAdapter.__init__()` SHALL raise
   `AxonDependencyError` with instructions to install `axon-sdk[bedrock]`.

8. IF `google-cloud-aiplatform` is not installed, THE `VertexAdapter.__init__()` SHALL
   raise `AxonDependencyError` with instructions to install `axon-sdk[vertex]`.

9. BOTH `BedrockAdapter` and `VertexAdapter` SHALL be importable from
   `axon.providers` without installing optional dependencies,
   via lazy import guards in `sdk/python/axon/providers/__init__.py`.

10. THE `ProviderResponse` dataclass SHALL be defined in
    `sdk/python/axon/providers/__init__.py` and SHALL be importable as
    `from axon.providers import ProviderResponse`.

---

### Requirement 5: Plugin System

**User Story:** As a platform engineer, I want to extend Axon's compression, routing, and
artifact classification behavior via a plugin system, so that I can add custom logic
without modifying the core SDK.

#### Acceptance Criteria

1. THE `sdk/python/axon/plugins/base.py` module SHALL define three abstract base classes
   using `abc.ABC`:
   - `CompressionPlugin(ABC)` with abstract method
     `compress(segments: list[str], **kwargs: Any) -> list[str]`
   - `RoutingPlugin(ABC)` with abstract method
     `route(messages: list[dict[str, Any]], requested_model: str, **kwargs: Any) -> RoutingDecision | None`
   - `ArtifactClassifierPlugin(ABC)` with abstract method
     `classify(content: str, **kwargs: Any) -> ArtifactType | None`

2. THE `PluginRegistry` in `sdk/python/axon/plugins/registry.py` SHALL maintain
   three separate registries (one per plugin type) and expose:
   - `register(plugin: CompressionPlugin | RoutingPlugin | ArtifactClassifierPlugin) -> None`
   - `get_compression_plugins() -> list[CompressionPlugin]`
   - `get_routing_plugins() -> list[RoutingPlugin]`
   - `get_classifier_plugins() -> list[ArtifactClassifierPlugin]`
   - `clear() -> None` (for test isolation)

3. THE `PluginRegistry.register()` SHALL raise `TypeError` if the argument is not an
   instance of one of the three recognized plugin ABCs.

4. THE `PluginLoader` in `sdk/python/axon/plugins/loader.py` SHALL discover and load
   plugins using Python entry points under the group `"axon.plugins"` via
   `importlib.metadata.entry_points(group="axon.plugins")`.

5. THE `PluginLoader.load_all(registry: PluginRegistry) -> int` method SHALL:
   - Iterate over all discovered entry points in the `"axon.plugins"` group.
   - Instantiate each entry point's class.
   - Call `registry.register(instance)`.
   - Log each successful load via structlog.
   - Catch `Exception` on each individual plugin load, log the error via structlog,
     and continue loading remaining plugins (partial failure is non-fatal).
   - Return the count of successfully loaded plugins.

6. WHEN a `CompressionPlugin` is registered and a compression pipeline runs,
   THE pipeline SHALL call `plugin.compress(segments)` for each registered
   `CompressionPlugin` in registration order, passing the output of one plugin
   as the input to the next (pipeline composition).

7. WHEN a `RoutingPlugin` is registered and `route()` is called,
   THE plugin SHALL be invoked before the default router. IF the plugin returns
   a non-None `RoutingDecision`, THEN that decision SHALL be used and the default
   router SHALL NOT be called for that request.

8. THE `sdk/python/axon/plugins/__init__.py` SHALL export:
   `CompressionPlugin`, `RoutingPlugin`, `ArtifactClassifierPlugin`,
   `PluginRegistry`, `PluginLoader`.

---

### Requirement 6: Predictive Cost Modeling

**User Story:** As an engineering lead, I want to request a cost prediction for a planned
LLM call before submitting it, so that I can gate high-cost requests and plan budgets
accurately.

#### Acceptance Criteria

1. THE backend SHALL expose a `POST /v1/predictions/cost` endpoint defined in
   `backend/axon_backend/api/v1/predictions.py` that accepts a request body with fields:
   `feature_tag: str`, `model: str`, `estimated_input_tokens: int`,
   `estimated_output_tokens: int`, and returns a `CostPredictionResponse`.

2. THE `CostPredictionResponse` SHALL be a Pydantic model with fields:
   `point_estimate_usd: str` (Decimal serialized as string),
   `lower_bound_usd: str`, `upper_bound_usd: str`,
   `prediction_interval_pct: int` (always 90),
   `model: str`, `feature_tag: str`, `sample_count: int`.

3. THE `CostPredictor` in `backend/axon_backend/services/cost_predictor.py` SHALL
   compute the point estimate as:
   `(estimated_input_tokens / 1_000_000) * input_price + (estimated_output_tokens / 1_000_000) * output_price`
   where prices are sourced from `axon.core.pricing.PROVIDER_PRICING` (Decimal).

4. THE `CostPredictor` SHALL compute the 90% prediction interval by:
   - Querying up to 1000 historical `InferenceSpanRecord` rows for the same
     `model` within the last 30 days.
   - IF fewer than 10 historical rows exist, THEN THE `CostPredictor` SHALL
     return a prediction interval of `±50%` around the point estimate.
   - IF 10 or more historical rows exist, THEN THE `CostPredictor` SHALL compute
     the 5th and 95th percentile of historical `cost_usd` values scaled to the
     requested token counts, and use those as the interval bounds.

5. THE `POST /v1/predictions/cost` endpoint SHALL require `engineer` role
   (via `require_role("engineer")`).

6. IF `estimated_input_tokens < 0` or `estimated_output_tokens < 0`,
   THEN THE endpoint SHALL return HTTP 422 with a descriptive error message.

7. IF the `model` is not found in `PROVIDER_PRICING`,
   THEN THE endpoint SHALL return HTTP 404 with message
   `"Model '{model}' not found in pricing table"`.

8. THE `CostPredictor` SHALL use `Decimal` for all intermediate monetary arithmetic.
   No `float` arithmetic SHALL be used for cost values.

9. FOR ALL valid `(model, estimated_input_tokens, estimated_output_tokens)` inputs,
   THE `lower_bound_usd <= point_estimate_usd <= upper_bound_usd` invariant SHALL hold.

---

### Requirement 7: Anomaly Detection

**User Story:** As a platform engineer, I want the backend to automatically detect
anomalous cost or token-usage spikes relative to the rolling 7-day baseline, so that
I receive an early warning before budget exhaustion.

#### Acceptance Criteria

1. THE `AnomalyDetector` in `backend/axon_backend/services/anomaly_detector.py` SHALL
   implement IQR-based anomaly detection on cost and token metrics.

2. THE `AnomalyDetector` SHALL use a rolling 7-day lookback window. For each
   `feature_tag`, it SHALL compute `Q1`, `Q3`, and `IQR = Q3 - Q1` over the
   7-day hourly aggregated cost values from `AttributionHourlyRecord`.

3. THE `AnomalyDetector.run_scan(db: AsyncSession) -> list[AnomalyAlert]` method SHALL:
   - Query all `feature_tag` values with at least 7 days of attribution history.
   - For each `feature_tag`, compute the IQR bounds:
     `lower_fence = Q1 - 1.5 * IQR`, `upper_fence = Q3 + 1.5 * IQR`.
   - Compare the most recent hourly cost value against the fences.
   - WHEN the most recent value exceeds `upper_fence`, emit an `AnomalyAlert`
     with `direction="high"`.
   - WHEN the most recent value falls below `lower_fence`, emit an `AnomalyAlert`
     with `direction="low"`.
   - Return the list of all detected alerts (may be empty).

4. THE `AnomalyAlert` SHALL be a `@dataclass` with fields:
   `feature_tag: str`, `metric: str` (e.g. `"cost_usd"`), `direction: str`
   (`"high"` or `"low"`), `observed_value: float`, `upper_fence: float`,
   `lower_fence: float`, `detected_at: datetime`.

5. WHEN `AnomalyDetector.run_scan()` encounters a `feature_tag` with fewer than
   7 days of hourly data, THE `AnomalyDetector` SHALL skip that `feature_tag`
   and continue processing others. It SHALL not raise.

6. THE anomaly scan SHALL be registered as an APScheduler job in
   `backend/axon_backend/workers/scheduler.py` with
   `trigger="interval", hours=6, id="anomaly_scan"`.

7. WHEN an `AnomalyAlert` is generated, THE scheduler job SHALL emit a structlog
   warning with fields: `feature_tag`, `metric`, `direction`, `observed_value`,
   `upper_fence`, `lower_fence`.

8. THE `AnomalyDetector.run_scan()` SHALL never raise. All exceptions SHALL be
   caught, logged via structlog, and the method SHALL return an empty list on error.

9. FOR ALL `feature_tag` values with exactly 7 days of constant hourly cost (no
   variance), THE `AnomalyDetector` SHALL produce `IQR = 0` and treat any value
   above the constant as a `"high"` anomaly. (Zero-variance edge case.)

---

### Requirement 8: Production Telemetry Collector

**User Story:** As an Axon maintainer, I want to receive aggregate, anonymized benchmark
data from consenting users, so that I can populate a public benchmark registry with
real-world performance data.

#### Acceptance Criteria

1. THE `TelemetryReporter` in `sdk/python/axon/core/telemetry_reporter.py` SHALL be
   disabled by default. It SHALL only activate WHEN the user explicitly instantiates
   it with `TelemetryReporter(enabled=True)` or sets
   `AXON_TELEMETRY_ENABLED=true` in the environment.
   There SHALL be NO mechanism that enables telemetry without explicit user action.

2. THE `TelemetryReporter` SHALL collect only aggregate, non-personally-identifiable
   metrics: `p50_cost_usd`, `p95_cost_usd`, `p50_compression_ratio`,
   `p95_compression_ratio`, `avg_routing_accuracy`, `sdk_version`,
   `python_version`, `sample_count`. No prompt content, user IDs, API keys,
   or host identifiers SHALL ever be transmitted.

3. THE `TelemetryReporter.submit(payload: TelemetryPayload) -> bool` method SHALL
   call `POST /v1/benchmarks/submit` on the configured Axon backend URL. WHEN the
   request succeeds (HTTP 200–299), it SHALL return `True`. WHEN it fails for any
   reason (network error, non-2xx response), it SHALL return `False` and log a
   structlog warning. It SHALL never raise.

4. THE `TelemetryPayload` SHALL be a Pydantic v2 model with fields:
   `sdk_version: str`, `python_version: str`, `sample_count: int`,
   `p50_cost_usd: str`, `p95_cost_usd: str`,
   `p50_compression_ratio: float`, `p95_compression_ratio: float`,
   `avg_routing_accuracy: float`, `submitted_at: datetime`.
   All monetary values SHALL be strings (Decimal-serialized).

5. THE `TelemetryReporter.__init__()` SHALL log a structlog info event clearly stating
   that telemetry is enabled and describing what data is being collected,
   WHEN `enabled=True`. WHEN `enabled=False` (default), it SHALL not log anything.

6. THE `POST /v1/benchmarks/submit` endpoint SHALL require no authentication
   (public endpoint) and SHALL validate the `TelemetryPayload` schema.
   IF validation fails, it SHALL return HTTP 422. IF validation succeeds, it SHALL
   persist the payload to the database and return HTTP 201 with the assigned `id`.

7. THE `GET /v1/benchmarks` endpoint SHALL be public (no authentication required) and
   SHALL return a list of `BenchmarkRecord` objects ordered by `submitted_at` descending,
   with a default limit of 50 and maximum limit of 500.

---

### Requirement 9: Public Benchmark Registry Dashboard Page

**User Story:** As a prospective Axon user, I want to see a public page showing
real-world benchmark results submitted by the community, so that I can evaluate Axon's
performance before adopting it.

#### Acceptance Criteria

1. THE `BenchmarkRegistry` page at `dashboard/src/pages/BenchmarkRegistry.tsx` SHALL
   be accessible without authentication (no `X-Axon-API-Key` header required for the
   backing API calls).

2. WHEN at least one benchmark record exists, THE `BenchmarkRegistry` page SHALL display
   a table with columns: `submitted_at`, `sdk_version`, `sample_count`,
   `p50_cost_usd`, `p95_cost_usd`, `p50_compression_ratio`, `avg_routing_accuracy`.

3. WHEN the `BenchmarkRegistry` page renders and no benchmark records exist,
   THE page SHALL hide the table and display an empty-state message:
   `"No benchmark data yet. Be the first to submit!"` with a link to
   `docs/production-validation.md`.

4. THE `BenchmarkRegistry` page SHALL be added to the dashboard navigation sidebar
   with the label `"Benchmarks"` and SHALL be accessible at route `/benchmarks`.

5. THE `BenchmarkRegistry` page SHALL be a new page in the existing React dashboard
   (`dashboard/src/pages/BenchmarkRegistry.tsx`) and SHALL use the existing layout,
   design system (Tailwind classes, `bg-gray-950`, teal accent), and component patterns
   established in Phase 4.

6. THE page SHALL include a prominent note: `"All data submitted by users. Axon does not
   verify individual submissions."` rendered in `text-gray-400`.

---

### Requirement 10: Community Infrastructure

**User Story:** As a prospective contributor, I want clear governance documentation and
a streamlined contributor setup process, so that I can understand how decisions are made
and get my environment ready quickly.

#### Acceptance Criteria

1. THE `community/GOVERNANCE.md` file SHALL describe the project governance model
   including: maintainer responsibilities, decision-making process, RFC process
   (linking to `RFC_TEMPLATE.md`), code of conduct reference, and release cadence.

2. THE `community/RFC_TEMPLATE.md` file SHALL provide a template for Axon RFCs
   (Request for Comments) with sections: Summary, Motivation, Detailed Design,
   Drawbacks, Alternatives, Unresolved Questions.

3. THE `community/scripts/setup_contributor.sh` script SHALL:
   - Check for Python >= 3.11 and Node >= 20 and print a human-readable error if
     either is missing.
   - Create a Python virtual environment at `.venv/`.
   - Install SDK dependencies with `pip install -e "sdk/python[dev,ml,bedrock,vertex]"`.
   - Install backend dependencies with `pip install -e "backend[dev]"`.
   - Install dashboard dependencies with `npm install` inside `dashboard/`.
   - Install pre-commit hooks with `pre-commit install`.
   - Print a success message listing the commands the contributor can now run.

4. THE `.github/workflows/ci.yml` SHALL include a `welcome-contributor` job that
   posts a welcome comment on pull requests from first-time contributors
   using the `actions/first-interaction@v1` action.

---

### Requirement 11: Distribution Foundations

**User Story:** As an Axon maintainer, I want launch and blog post content drafts that
are truthful and properly gated, so that public communications are accurate and released
only after real production data is available.

#### Acceptance Criteria

1. THE `docs/launch/HN_LAUNCH.md` file SHALL contain the exact line:
   `"Do not post until production validation data is collected"` as a prominent
   warning at the top of the document (within the first 5 lines of the file).

2. THE `docs/launch/HN_LAUNCH.md` file SHALL contain a draft Hacker News "Show HN"
   post with: title, description of what Axon does, links to the GitHub repo and docs,
   and a section for benchmark results marked as `[PLACEHOLDER: insert production data]`.

3. THE `docs/launch/BLOG_POST_DRAFT.md` file SHALL be a draft technical blog post
   covering: Axon's architecture, the compression engine, the routing system, and
   Phase 5 features. Any performance claims SHALL use `[PLACEHOLDER]` markers and
   SHALL NOT present synthetic benchmark data as production measurements.

4. NEITHER `HN_LAUNCH.md` NOR `BLOG_POST_DRAFT.md` SHALL contain fabricated performance
   numbers presented as measured results from real user workloads.

---

### Requirement 12: Technical Paper Draft

**User Story:** As an Axon researcher, I want an arXiv-ready paper draft that accurately
represents the system and its evaluation status, so that I can submit it once real
benchmark data is collected.

#### Acceptance Criteria

1. THE `research/paper/axon_paper.md` file SHALL be structured as an arXiv-ready paper
   with sections: Abstract, Introduction, System Design, Compression Engine,
   Adaptive Routing, Conformal Prediction Guarantees, Evaluation, Related Work,
   Conclusion.

2. THE Evaluation section SHALL use `[TBD]` placeholders for all numeric results.
   It SHALL explicitly state: `"Evaluation results are pending collection of production
   data. Placeholders are marked [TBD] and will be replaced with measured values."`.
   NO fabricated performance numbers SHALL appear in the Evaluation section.

3. THE paper SHALL accurately describe the conformal prediction guarantee:
   `P(quality >= threshold) >= 1 - alpha`, citing Angelopoulos & Bates (2021).

4. THE paper SHALL accurately describe the benchmark as synthetic (based on the
   existing Phase 1 synthetic workload) and SHALL NOT claim that any results were
   measured on production user data until such data is collected.

5. THE `research/notebooks/compression_analysis.ipynb` Jupyter notebook SHALL contain
   executable cells demonstrating: loading synthetic benchmark data, computing
   compression ratios, visualizing the distribution of token savings, and computing
   summary statistics. All output cells SHALL be cleared (no cached outputs committed).

---

### Requirement 13: Documentation Completeness

**User Story:** As a developer adopting Phase 5 features, I want comprehensive guides
for each new capability, so that I can integrate ML routing, batch processing, new
providers, and plugins without referring to source code.

#### Acceptance Criteria

1. THE `docs/ml-router-guide.md` SHALL document: how to enable `MLRouter`, the 500-example
   threshold for ML activation, fallback behavior to `RuleRouter`, conformal prediction
   setup with `ConformalPredictor`, and how to interpret `routing_rule` field prefixes.

2. THE `docs/batch-routing.md` SHALL document: marking spans as `batch_eligible`,
   configuring `BatchRouter`, polling for job completion, and the expected ~50%
   cost reduction (noting this is approximate and subject to provider pricing).

3. THE `docs/provider-expansion.md` SHALL document: installing optional dependencies
   (`axon-sdk[bedrock]`, `axon-sdk[vertex]`), AWS credentials setup for Bedrock,
   GCP service account setup for Vertex AI, and supported model identifiers.

4. THE `docs/plugin-development.md` SHALL document: implementing each plugin ABC,
   registering plugins via entry points in `pyproject.toml`, testing plugins in
   isolation, and the pipeline composition behavior for `CompressionPlugin`.

5. THE `docs/production-validation.md` SHALL document: what production validation
   means in the Axon context, how to use `TelemetryReporter` for opt-in submission,
   the format of `TelemetryPayload`, and instructions for accessing the public
   benchmark registry.

---

### Requirement 14: Test Coverage and Regression Guard

**User Story:** As the Axon CI system, I want all Phase 5 changes to maintain quality
gates, so that no Phase 1–4 behavior is broken and all new code meets coverage standards.

#### Acceptance Criteria

1. WHEN all 25 Phase 5 commits are applied, THE `pytest sdk/python/tests` command
   SHALL pass with all 481 existing tests green plus all new Phase 5 tests.

2. WHEN all Phase 5 changes are applied,
   `pytest sdk/python/tests --cov=axon --cov-fail-under=85` SHALL pass.

3. WHEN all Phase 5 changes are applied,
   `pytest backend/tests --cov=axon_backend --cov-fail-under=75` SHALL pass.

4. EACH new Phase 5 Python module (listed in the new file locations in the introduction)
   SHALL individually achieve at least 80% test coverage as measured by `pytest --cov`.

5. WHEN all Phase 5 changes are applied,
   `mypy sdk/python/axon --strict` SHALL exit with 0 errors.

6. WHEN all Phase 5 changes are applied,
   `mypy backend/axon_backend --strict` SHALL exit with 0 errors.

7. WHEN all Phase 5 changes are applied,
   `ruff check sdk/python/axon sdk/python/tests` SHALL report no violations.

8. WHEN all Phase 5 changes are applied,
   `cd dashboard && npm run typecheck` SHALL exit with 0 errors.

9. IF `TelemetryReporter` is instantiated with no arguments (default),
   THEN telemetry SHALL be disabled and NO network requests SHALL be made.
   (Opt-in only — hard regression guard.)

10. THE `HN_LAUNCH.md` file SHALL be asserted in the CI test suite to contain
    the line `"Do not post until production validation data is collected"`.

11. WHEN all Phase 5 changes are applied,
    `curl http://localhost:8000/health` SHALL return
    `{"status":"ok","version":"0.5.0"}`.
