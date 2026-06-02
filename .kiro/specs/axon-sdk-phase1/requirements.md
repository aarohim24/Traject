# Requirements Document

## Introduction

Axon SDK Phase 1 is a pip-installable Python package (`axon-sdk`) that
instruments OpenAI and Anthropic LLM API calls to produce structured
OpenTelemetry spans with cost attribution, artifact classification, and
trajectory compression analysis. The SDK wraps existing provider clients
via a single decorator (`@instrument()`) or patch call (`patch()`), adding
observability at the infrastructure layer with no behavioral change required
from the developer.

Phase 1 delivers five subsystems: instrumentation, artifact classification,
trajectory compression (shadow mode only), OTEL telemetry export, and a CLI.
There is no backend service, no database, and no network dependency beyond
the provider APIs the user already calls.

---

## Glossary

- **Axon_SDK**: The `axon-sdk` Python package as a whole.
- **Instrumentor**: The component in `axon/core/instrumentor.py` that wraps
  provider calls via `@instrument()` and `patch()`.
- **ProviderAdapter**: The component in `axon/core/provider_adapter.py` that
  normalizes provider-specific response shapes into `UsageData`.
- **CostCalculator**: The component in `axon/core/cost_calculator.py` that
  converts token counts to `Decimal` cost values.
- **Classifier**: The component in `axon/classifier/artifact_type.py` that
  classifies message segments into `ArtifactType` values.
- **CompressionEngine**: The component in `axon/compression/engine.py` that
  runs the full compression pipeline.
- **RelevanceScorer**: The component in `axon/compression/relevance_scorer.py`
  that scores segment relevance using a composite formula.
- **SegmentParser**: The component in `axon/compression/segment_parser.py`
  that converts a messages array into `Segment` objects.
- **FrameworkAdapter**: The ABC in `axon/compression/adapters/base.py` that
  normalizes framework-specific message formats to canonical `list[dict]`.
- **OTELExporter**: The component in `axon/telemetry/otel_exporter.py` that
  converts `InferenceSpan` models to OTEL spans.
- **CLI**: The `axon` command-line tool implemented in `axon/cli/main.py`.
- **InferenceSpan**: The Pydantic v2 model representing a single instrumented
  LLM API call, defined in `axon/models.py`.
- **CompressionResult**: The Pydantic v2 model representing the output of a
  compression pipeline run, defined in `axon/models.py`.
- **Segment**: The Pydantic v2 model representing a single message within a
  compression analysis, defined in `axon/models.py`.
- **ArtifactType**: The enum with 9 values: `SYSTEM_PROMPT`, `USER_MESSAGE`,
  `ASSISTANT_MESSAGE`, `TOOL_RESULT`, `TOOL_CALL`, `RAG_CHUNK`,
  `FEW_SHOT_EXAMPLE`, `REASONING_BLOCK`, `UNKNOWN`.
- **CompressionStrategy**: The enum with 3 values: `CONSERVATIVE`,
  `MODERATE`, `AGGRESSIVE`.
- **Shadow_Mode**: A mode in which the compression pipeline runs fully but
  the original uncompressed messages are always returned to the caller.
- **AxonError**: The base exception class for all SDK-raised exceptions,
  defined in `axon/exceptions.py`.
- **PROVIDER_PRICING**: The static dict in `axon/core/pricing.py` mapping
  model identifier strings to `ModelPricing` dataclass instances.
- **Protected_Segment**: A `Segment` whose `protected` field is `True`,
  meaning the compression engine must not drop or modify it.

---

## Requirements

### Requirement 1: Instrumentation — Client Wrapping

**User Story:** As a developer, I want to instrument my existing OpenAI or
Anthropic client calls with a single decorator or patch call, so that I gain
observability without modifying any of my existing call-site code.

#### Acceptance Criteria

1. WHEN a developer applies `@axon.instrument()` to a function that calls an
   OpenAI or Anthropic client, THE Instrumentor SHALL wrap that function
   transparently such that the function's return value, signature, and
   exception behavior are identical to the unwrapped version.

2. WHEN a developer calls `axon.patch(client)` on an OpenAI or Anthropic
   client instance, THE Instrumentor SHALL instrument all subsequent calls
   made through that client without requiring any other changes to the
   caller's code.

3. WHEN an instrumented function raises an exception from the underlying
   provider call, THE Instrumentor SHALL re-raise that exception unchanged
   and SHALL NOT suppress or wrap it.

4. WHEN an internal Axon pipeline step raises an `AxonError` subclass during
   an instrumented call, THE Instrumentor SHALL catch that error, log it via
   structlog, and return the original provider response unmodified.

5. THE Instrumentor SHALL support both synchronous and asynchronous callable
   functions decorated with `@instrument()`.

---

### Requirement 2: Instrumentation — InferenceSpan Production

**User Story:** As a platform engineer, I want every instrumented LLM call to
produce a complete, structured `InferenceSpan` record, so that I can perform
cost attribution, latency analysis, and compression auditing downstream.

#### Acceptance Criteria

1. WHEN an instrumented LLM call completes successfully, THE Instrumentor
   SHALL produce an `InferenceSpan` containing all of the following fields:
   `id`, `trace_id`, `span_name`, `timestamp`, `duration_ms`, `provider`,
   `model`, `input_tokens`, `output_tokens`, `cached_tokens`,
   `token_count_method`, `cost_usd`, `feature_tag`, `prompt_hash`,
   `artifact_type`, `compression_applied`, `shadow_mode`,
   `pre_compression_tokens`, `tokens_saved`, `cache_hit`, `environment`.

2. WHEN building an `InferenceSpan`, THE Instrumentor SHALL set `span_name`
   to the format `gen_ai.{provider}.{model}` (e.g., `gen_ai.openai.gpt-4o`).

3. WHEN building an `InferenceSpan`, THE Instrumentor SHALL set `prompt_hash`
   to the SHA-256 hex digest of the normalized prompt content, where
   normalization is defined as: concatenate all `content` string fields,
   strip leading and trailing whitespace, and lowercase the result.

4. WHEN building an `InferenceSpan`, THE Instrumentor SHALL set
   `artifact_type` by calling `classify()` on the first message in the
   messages array with `position_index=0`.

5. WHEN building an `InferenceSpan`, THE Instrumentor SHALL set
   `compression_applied=False` when `shadow_mode=True`, and
   `compression_applied=True` only when `shadow_mode=False` and compression
   was actually applied.

6. WHEN building an `InferenceSpan`, THE Instrumentor SHALL set
   `cache_hit=True` if and only if `cached_tokens > 0`.

---

### Requirement 3: Instrumentation — Token Counts and Cost

**User Story:** As a cost analyst, I want token counts sourced from provider
response objects and costs calculated with Decimal precision, so that my cost
attribution data is accurate and free of floating-point drift.

#### Acceptance Criteria

1. WHEN a non-streaming OpenAI response is received, THE ProviderAdapter
   SHALL read `usage.prompt_tokens` and `usage.completion_tokens` from the
   response object and set `token_count_method="exact"`.

2. WHEN a non-streaming Anthropic response is received, THE ProviderAdapter
   SHALL read `usage.input_tokens` and `usage.output_tokens` from the
   response object and set `token_count_method="exact"`.

3. WHEN a streaming response does not expose final token counts in the
   response object, THE ProviderAdapter SHALL estimate token counts using
   `tiktoken` and set `token_count_method="estimated"`.

4. WHEN an OpenAI response includes `usage.prompt_tokens_details.cached_tokens`,
   THE ProviderAdapter SHALL read that value as `cached_tokens`; otherwise
   `cached_tokens` SHALL be `0`.

5. WHEN an Anthropic response includes `usage.cache_read_input_tokens`,
   THE ProviderAdapter SHALL read that value as `cached_tokens`; otherwise
   `cached_tokens` SHALL be `0`.

6. WHEN `calculate_cost()` is called with a model identifier present in
   `PROVIDER_PRICING` and non-negative token counts, THE CostCalculator
   SHALL return a `Decimal` value greater than or equal to `Decimal("0")`.

7. WHEN `calculate_cost()` is called with a model identifier not present in
   `PROVIDER_PRICING`, THE CostCalculator SHALL return `None`, log a warning
   via structlog, and SHALL NOT raise any exception.

8. THE CostCalculator SHALL use `Decimal` arithmetic exclusively for all
   monetary calculations and SHALL NOT use `float` at any point in the cost
   computation.

9. WHEN `calculate_cost()` is called with `cached_tokens > 0` and the model
   has a `cache_read_cost_per_1m_tokens` entry in `PROVIDER_PRICING`, THE
   CostCalculator SHALL apply the cache read rate to the cached portion and
   the standard input rate to the non-cached portion.

---

### Requirement 4: Instrumentation — Performance

**User Story:** As a developer, I want the SDK instrumentation overhead to be
negligible, so that adding observability does not meaningfully affect my
application's latency.

#### Acceptance Criteria

1. WHEN 1000 instrumented calls are executed against a mock provider that
   responds in under 1ms, THE Instrumentor SHALL add no more than 5ms of
   median (p50) wall-clock overhead per call, as measured by
   `bench_sdk_overhead.py`.

2. WHEN the OTEL span is emitted after an instrumented call, THE OTELExporter
   SHALL emit the span in a non-blocking manner so that span export latency
   does not contribute to the instrumented call's overhead.

---

### Requirement 5: Artifact Classification

**User Story:** As a compression engineer, I want every message segment
classified into a deterministic artifact type, so that the compression engine
can apply protection rules and scoring weights correctly.

#### Acceptance Criteria

1. WHEN `classify()` is called on any message dict, THE Classifier SHALL
   return exactly one `ArtifactType` enum member and SHALL NOT raise any
   exception for any input, including empty dicts and dicts with missing keys.

2. WHEN `classify()` is called on a message where `message["role"] == "system"`,
   THE Classifier SHALL return `ArtifactType.SYSTEM_PROMPT` regardless of
   `position_index`, `total_messages`, or the content of the message.

3. WHEN `classify()` is called twice with identical arguments, THE Classifier
   SHALL return the same `ArtifactType` value both times.

4. WHEN `classify()` is called, THE Classifier SHALL apply heuristics in the
   following strict priority order, returning on the first match:
   (1) `role == "system"` → `SYSTEM_PROMPT`;
   (2) `role == "tool"` → `TOOL_RESULT`;
   (3) non-empty `tool_calls` field → `TOOL_CALL`;
   (4) `role == "assistant"` with reasoning markers → `REASONING_BLOCK`;
   (5) `role == "user"` at `position_index == 0` with few-shot markers → `FEW_SHOT_EXAMPLE`;
   (6) `role == "user"` with RAG markers → `RAG_CHUNK`;
   (7) `role == "user"` → `USER_MESSAGE`;
   (8) `role == "assistant"` → `ASSISTANT_MESSAGE`;
   (9) all other cases → `UNKNOWN`.

5. WHEN `classify()` is called on a single message, THE Classifier SHALL
   complete in less than 1ms as measured by `time.perf_counter`.

6. WHEN `classify_sequence()` is called on a list of messages, THE Classifier
   SHALL return a list of `ArtifactType` values of the same length as the
   input list, with each value corresponding to the classification of the
   message at the same index.

---

### Requirement 6: Trajectory Compression — Pipeline and Shadow Mode

**User Story:** As a developer evaluating compression, I want the compression
pipeline to run fully in shadow mode and report what it would have done,
without ever modifying the messages I send to the provider.

#### Acceptance Criteria

1. WHEN `compress()` is called with `config.shadow_mode=True`, THE
   CompressionEngine SHALL return a `CompressionResult` whose `messages`
   field is the identical object (or an equal copy) of the input `messages`
   argument.

2. WHEN `compress()` is called, THE CompressionEngine SHALL execute the
   following pipeline stages in order: NORMALIZE (framework adapter),
   CLASSIFY (artifact types), PARSE (segments with token counts), PROTECT
   (mark protected segments), SCORE (relevance scoring), COMPRESS (apply
   strategy decisions), VALIDATE (invariant check), and RECORD
   (build `CompressionResult`).

3. WHEN `compress()` is called and the VALIDATE stage detects an invariant
   violation, THE CompressionEngine SHALL fall back to returning the original
   messages, set `compression_ratio=0.0`, `tokens_saved=0`, and append a
   descriptive warning string to `CompressionResult.warnings`.

4. WHEN `compress()` is called with a messages array in LangChain
   `BaseMessage` format, THE FrameworkAdapter SHALL normalize it to canonical
   `list[dict]` with `role` and `content` keys before processing.

5. WHEN `compress()` is called with a messages array in AutoGen message dict
   format, THE FrameworkAdapter SHALL normalize it to canonical `list[dict]`
   before processing.

6. WHEN `compress()` is called with a raw OpenAI `list[dict]` format, THE
   FrameworkAdapter SHALL accept it without transformation.

---

### Requirement 7: Trajectory Compression — Protection Rules

**User Story:** As a developer, I want the compression engine to guarantee
that critical context is never removed, so that I can trust the compressed
output preserves the information the model needs.

#### Acceptance Criteria

1. WHEN `compress()` is called, THE CompressionEngine SHALL mark all segments
   with `artifact_type == ArtifactType.SYSTEM_PROMPT` as `protected=True`
   during the PARSE stage, and SHALL NOT drop or modify any such segment
   during the COMPRESS stage.

2. WHEN `compress()` is called, THE CompressionEngine SHALL mark all segments
   belonging to the last `config.min_turns_protected` user+assistant turn
   pairs as `protected=True` during the PROTECT stage, and SHALL NOT drop or
   modify any such segment during the COMPRESS stage.

3. WHEN `compress()` is called and a message dict contains metadata field
   `axon_preserve: true`, THE CompressionEngine SHALL mark the corresponding
   segment as `protected=True` and SHALL NOT drop or modify it.

4. WHEN `score_segments()` is called on a list of segments, THE
   RelevanceScorer SHALL return score `1.0` for every segment where
   `segment.protected == True`.

---

### Requirement 8: Trajectory Compression — Scoring

**User Story:** As a compression engineer, I want segment relevance scored
using a composite of recency, semantic similarity, and reference count, so
that the compression decisions are grounded in the segment's actual utility.

#### Acceptance Criteria

1. WHEN `score_segments()` is called, THE RelevanceScorer SHALL compute a
   composite score for each non-protected segment using the formula:
   `0.4 * recency + 0.4 * semantic + 0.2 * reference`, where recency is
   `exp(-0.3 * turns_since_segment)`, semantic is cosine similarity of the
   segment embedding against the task hint embedding (defaulting to `1.0`
   when no task hint is provided), and reference is
   `min(1.0, reference_count / 3)`.

2. WHEN `score_segments()` is called, THE RelevanceScorer SHALL return a
   list of floats of the same length as the input segments list, with every
   value in the range `[0.0, 1.0]` inclusive.

3. WHEN `score_segments()` is called with the same inputs, THE RelevanceScorer
   SHALL return the same scores (deterministic output).

4. THE RelevanceScorer SHALL load the `all-MiniLM-L6-v2` model exactly once
   at module import time and SHALL reuse the same model instance for all
   subsequent calls within the process lifetime.

---

### Requirement 9: Trajectory Compression — Strategy Decisions

**User Story:** As a developer, I want three compression strategies with
defined reduction targets and decision rules, so that I can choose the
aggressiveness of compression appropriate for my use case.

#### Acceptance Criteria

1. WHEN `compress()` is called with `CompressionStrategy.CONSERVATIVE`, THE
   CompressionEngine SHALL target 20% token reduction, protect the last 3
   turn pairs, and apply the following decisions to non-protected segments:
   summarize `TOOL_RESULT` segments older than 3 turns with score < 0.30;
   drop `REASONING_BLOCK` segments with score < 0.40; retain all others.

2. WHEN `compress()` is called with `CompressionStrategy.MODERATE`, THE
   CompressionEngine SHALL target 35% token reduction, protect the last 3
   turn pairs, and apply the following decisions to non-protected segments:
   summarize `TOOL_RESULT` segments older than 2 turns with score < 0.40;
   drop `REASONING_BLOCK` segments with score < 0.50; drop `RAG_CHUNK`
   segments with score < 0.35; retain all others.

3. WHEN `compress()` is called with `CompressionStrategy.AGGRESSIVE`, THE
   CompressionEngine SHALL target 55% token reduction, protect the last 2
   turn pairs, and apply the following decisions to non-protected segments:
   summarize `TOOL_RESULT` segments older than 1 turn with score < 0.50;
   drop `REASONING_BLOCK` segments with score < 0.60; drop `RAG_CHUNK`
   segments with score < 0.45; drop `FEW_SHOT_EXAMPLE` segments with
   score < 0.40; retain all others.

4. WHEN the CompressionEngine summarizes a segment, THE CompressionEngine
   SHALL produce the summary as the first 100 characters of the segment's
   content concatenated with the string `" [summarized by Axon]"`, without
   making any LLM API calls.

---

### Requirement 10: Trajectory Compression — Result Invariants

**User Story:** As a developer, I want the `CompressionResult` fields to be
internally consistent, so that I can rely on them for accurate reporting of
compression savings.

#### Acceptance Criteria

1. WHEN `compress()` returns a `CompressionResult`, THE CompressionEngine
   SHALL ensure that
   `segments_retained + segments_summarized + segments_dropped == segments_analyzed`.

2. WHEN `compress()` returns a `CompressionResult`, THE CompressionEngine
   SHALL ensure that `tokens_saved == original_tokens - compressed_tokens`.

3. WHEN `compress()` returns a `CompressionResult`, THE CompressionEngine
   SHALL ensure that `0.0 <= compression_ratio <= 1.0`.

4. WHEN `compress()` is called with `config.shadow_mode=True`, THE
   CompressionEngine SHALL set `compressed_tokens == original_tokens` and
   `tokens_saved == 0` in the returned `CompressionResult`.

---

### Requirement 11: OpenTelemetry Export

**User Story:** As a platform engineer, I want every instrumented call to emit
an OTEL span with standardized attributes, so that I can route span data to
any OTEL-compatible observability backend.

#### Acceptance Criteria

1. WHEN an instrumented call completes, THE OTELExporter SHALL emit an OTEL
   span with the following attribute mapping:
   `gen_ai.system` ← `provider`;
   `gen_ai.request.model` ← `model`;
   `gen_ai.usage.input_tokens` ← `input_tokens`;
   `gen_ai.usage.output_tokens` ← `output_tokens`;
   `axon.cost_usd` ← string representation of `cost_usd` (empty string if `None`);
   `axon.feature_tag` ← `feature_tag`;
   `axon.prompt_hash` ← `prompt_hash`;
   `axon.artifact_type` ← `artifact_type.value`;
   `axon.compression.applied` ← `compression_applied`;
   `axon.compression.shadow_mode` ← `shadow_mode`;
   `axon.compression.tokens_saved` ← `tokens_saved` (0 if `None`);
   `axon.cache_hit` ← `cache_hit`;
   `axon.environment` ← `environment`.

2. WHEN `configure_exporter()` is called and no `AXON_OTLP_ENDPOINT`
   environment variable is set and no `otlp_endpoint` argument is provided,
   THE OTELExporter SHALL use `ConsoleSpanExporter` as the sole exporter.

3. WHEN `configure_exporter()` is called and `AXON_OTLP_ENDPOINT` is set in
   the environment, THE OTELExporter SHALL add an `OTLPSpanExporter`
   targeting that endpoint in addition to any configured stdout exporter.

4. WHEN `configure_exporter()` is called more than once, THE OTELExporter
   SHALL be idempotent: subsequent calls after the first SHALL be no-ops and
   SHALL NOT add duplicate span processors or exporters.

5. WHEN `emit_span()` is called before `configure_exporter()` has been
   explicitly called, THE OTELExporter SHALL call `configure_exporter()` with
   default arguments before emitting the span.

---

### Requirement 12: CLI — analyze Command

**User Story:** As a developer, I want to analyze a local JSONL file of
`InferenceSpan` records and see a cost summary table, so that I can
understand my LLM spending and compression savings without a backend service.

#### Acceptance Criteria

1. WHEN `axon analyze --input <file.jsonl>` is executed with a valid JSONL
   file of `InferenceSpan` records, THE CLI SHALL parse each line as an
   `InferenceSpan` and output a rich table with the following columns:
   Model, Feature Tag, Calls, Input Tokens, Output Tokens, Cost (USD),
   Shadow Savings (tokens), Cache Hits.

2. WHEN `axon analyze --input <file.jsonl>` is executed, THE CLI SHALL
   aggregate rows by `(model, feature_tag)` pair and display one row per
   unique pair.

3. WHEN `axon analyze --input <file.jsonl> --format json` is executed, THE
   CLI SHALL output the same summary data as a JSON object instead of a
   rich table.

4. IF the input file does not exist or cannot be parsed as JSONL, THEN THE
   CLI SHALL print a descriptive error message and exit with a non-zero exit
   code.

---

### Requirement 13: CLI — version and doctor Commands

**User Story:** As a developer, I want quick CLI commands to check the SDK
version and dependency health, so that I can diagnose installation issues
without reading source code.

#### Acceptance Criteria

1. WHEN `axon version` is executed, THE CLI SHALL print the string
   `axon-sdk 0.1.0` to stdout.

2. WHEN `axon doctor` is executed and all required dependencies
   (`sentence-transformers`, `opentelemetry-sdk`, `tiktoken`) are importable,
   THE CLI SHALL print a status table showing each dependency as installed
   and exit with code 0.

3. WHEN `axon doctor` is executed and one or more required dependencies are
   not importable, THE CLI SHALL print a status table marking the missing
   required dependencies as missing and exit with code 1.

4. WHEN `axon doctor` is executed, THE CLI SHALL check the following packages
   and display their status: `sentence-transformers` (required),
   `opentelemetry-sdk` (required), `tiktoken` (required),
   `openai` (optional), `anthropic` (optional).

5. THE CLI SHALL use `typer` for argument parsing and `rich` for all table
   and formatted output.

---

### Requirement 14: Privacy

**User Story:** As a security-conscious developer, I want the SDK to never
store or transmit raw prompt content or provider API keys, so that I can
instrument my LLM calls without introducing a data exfiltration risk.

#### Acceptance Criteria

1. WHEN the Instrumentor processes a messages array, THE Instrumentor SHALL
   compute the SHA-256 hex digest of the normalized content (all `content`
   string fields concatenated, stripped, and lowercased) and store only that
   64-character hex digest in the `prompt_hash` field of the `InferenceSpan`.

2. WHEN the Instrumentor processes a messages array, THE Instrumentor SHALL
   NOT write, log, or include raw prompt content in any `InferenceSpan`
   field, structlog event, or OTEL span attribute.

3. THE Instrumentor SHALL NOT read, store, log, or transmit provider API keys
   at any point; it SHALL wrap the user's existing client object without
   accessing its credential fields.

4. WHEN `_hash_prompt()` is called with an empty messages list, THE
   Instrumentor SHALL return the SHA-256 hex digest of the empty string
   (`"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"`).

---

### Requirement 15: Distribution and Package Structure

**User Story:** As a developer, I want to install the SDK with a single pip
command and optionally pull in framework-specific extras, so that I can
integrate Axon into any Python project without dependency conflicts.

#### Acceptance Criteria

1. THE Axon_SDK SHALL be publishable to PyPI under the package name `axon-sdk`
   using a `pyproject.toml` with `hatchling` as the build backend.

2. WHEN `pip install axon-sdk` is executed in a fresh Python 3.11 virtualenv,
   THE Axon_SDK SHALL install successfully with all runtime dependencies
   (`opentelemetry-sdk`, `opentelemetry-api`,
   `opentelemetry-exporter-otlp-proto-grpc`, `pydantic`, `structlog`,
   `sentence-transformers`, `tiktoken`, `typer`, `rich`).

3. WHERE the `[openai]` extra is specified, THE Axon_SDK SHALL install
   `openai>=1.30` as an additional dependency.

4. WHERE the `[anthropic]` extra is specified, THE Axon_SDK SHALL install
   `anthropic>=0.28` as an additional dependency.

5. WHERE the `[langchain]` extra is specified, THE Axon_SDK SHALL install
   `langchain-core>=0.2` as an additional dependency.

6. WHERE the `[autogen]` extra is specified, THE Axon_SDK SHALL install
   `pyautogen>=0.2` as an additional dependency.

7. WHERE the `[dev]` extra is specified, THE Axon_SDK SHALL install all
   development dependencies including `pytest`, `pytest-asyncio`,
   `pytest-cov`, `respx`, `hypothesis`, `mypy`, `ruff`, and `pre-commit`.

8. THE Axon_SDK SHALL expose the `axon` CLI entry point via
   `[project.scripts]` in `pyproject.toml` pointing to `axon.cli.main:app`.

---

### Requirement 16: Code Quality and Architecture

**User Story:** As a maintainer, I want the codebase to enforce strict type
safety, linting, test coverage, and dependency direction, so that the SDK
remains correct and maintainable as it grows.

#### Acceptance Criteria

1. THE Axon_SDK SHALL pass `mypy --strict` with zero errors on every commit.

2. THE Axon_SDK SHALL pass `ruff check` and `ruff format --check` with zero
   issues on every commit.

3. THE Axon_SDK SHALL achieve a minimum of 80% overall test coverage and a
   minimum of 90% test coverage on `axon/compression/engine.py`, as measured
   by `pytest --cov`.

4. IF any exception is raised by library code within the `axon` package, THEN
   that exception SHALL be an instance of `AxonError` or one of its
   subclasses (`AxonConfigError`, `AxonDependencyError`,
   `AxonCompressionError`, `AxonProviderError`).

5. THE Axon_SDK SHALL use `Decimal` for all monetary values and SHALL NOT use
   `float` for any currency calculation.

6. THE Axon_SDK SHALL use Pydantic v2 models or frozen `@dataclass` instances
   for all data structures that cross module boundaries; raw `dict` objects
   SHALL only be used as local intermediates within a single function body.

7. THE Axon_SDK SHALL use `structlog.get_logger(__name__)` exclusively for
   all logging and SHALL NOT contain any `print()` statements in library code.

8. THE Axon_SDK SHALL enforce the following strict module dependency
   direction with no circular imports:
   `classifier` → (no internal dependencies);
   `compression` → `classifier` only;
   `core` → `classifier` and `compression`;
   `telemetry` → `core`;
   `cli` → `core` and `telemetry`.

---

### Requirement 17: Error Handling

**User Story:** As a developer integrating the SDK, I want all SDK errors to
be typed, actionable, and non-disruptive, so that Axon failures never break
my application.

#### Acceptance Criteria

1. WHEN an unknown provider string is passed to `get_adapter()`, THE
   ProviderAdapter SHALL raise `AxonProviderError` with a message identifying
   the unknown provider and listing supported providers.

2. WHEN a framework adapter is constructed and the required framework package
   is not installed, THE FrameworkAdapter SHALL raise `AxonDependencyError`
   with a message specifying the missing package and the pip install command
   to resolve it.

3. WHEN `validate_config()` is called with a `CompressionConfig` where
   `target_reduction_pct` is not in `(0.0, 1.0)`, or `min_turns_protected`
   is negative, or `protect_system_prompt` is `False`, THE CompressionEngine
   SHALL raise `AxonConfigError` with a descriptive message.

4. WHEN the compression result fails the VALIDATE stage invariant check, THE
   CompressionEngine SHALL raise `AxonCompressionError` internally, catch it,
   fall back to the original messages, and log a warning; it SHALL NOT
   propagate the `AxonCompressionError` to the caller.

5. WHEN `no adapter accepts the messages format in `_detect_adapter()`, THE
   CompressionEngine SHALL raise `AxonCompressionError` with a message
   listing the supported formats and the install commands for optional
   adapters.
