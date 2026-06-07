# Spec: Axon SDK — Phase 1 (Validation)

## Status: ACTIVE
## Owner: engineering
## Target: PyPI publishable package, CLI functional, compression in shadow mode

---

## Requirements

### R1 — Instrumentation

R1.1 The SDK must wrap OpenAI and Anthropic Python clients
      with zero changes to the caller's existing code beyond
      adding the `@axon.instrument()` decorator or calling
      `axon.patch()`.

R1.2 Every instrumented LLM call must produce an `InferenceSpan`
     containing: trace_id, span_name, timestamp, duration_ms,
     provider, model, input_tokens, output_tokens, cached_tokens,
     cost_usd, feature_tag, prompt_hash, artifact_type,
     compression_applied, cache_hit, environment.

R1.3 Token counts must be sourced from provider response objects,
     not estimated. Streaming responses that do not expose final
     token counts must be marked with token_count_method="estimated"
     and use tiktoken for the estimate.

R1.4 Cost must be calculated using the static pricing table
     in `axon/core/pricing.py`. Unknown models must return
     cost_usd=None with a logged warning, never raise an exception
     that disrupts the caller's application.

R1.5 The SDK must not add more than 5ms median overhead
     to the instrumented call. This is verified by benchmark.

R1.6 The SDK must support async and sync LLM clients.

### R2 — Artifact Classification

R2.1 Every message segment in a context window must be classified
     into one of: SYSTEM_PROMPT, USER_MESSAGE, ASSISTANT_MESSAGE,
     TOOL_RESULT, TOOL_CALL, RAG_CHUNK, FEW_SHOT_EXAMPLE,
     REASONING_BLOCK, UNKNOWN.

R2.2 Classification must be deterministic, heuristic-only (no ML),
     and complete in < 1ms per message.

R2.3 SYSTEM_PROMPT classification must have zero false negatives.
     Misclassifying a system prompt as anything else is a
     critical bug. The compression engine depends on this.

### R3 — Trajectory Compression (Shadow Mode)

R3.1 The compression engine must accept a messages array in
     canonical format and return a CompressionResult containing:
     original_tokens, compressed_tokens, tokens_saved,
     compression_ratio, segments_analyzed, segments_retained,
     segments_summarized, segments_dropped, shadow_mode=True,
     strategy_applied, and the (unmodified) messages array.

R3.2 In shadow mode, the original messages array is always
     returned unchanged. The CompressionResult documents
     what would have happened.

R3.3 Protection rules (never violable):
     - All SYSTEM_PROMPT segments are immutable.
     - The last 3 user+assistant turn pairs are immutable.
     - Any segment explicitly marked with metadata
       `axon_preserve: true` is immutable.

R3.4 Compression candidates are scored by:
     recency_weight=0.4, semantic_relevance_weight=0.4,
     reference_count_weight=0.2.

R3.5 Semantic relevance scoring uses all-MiniLM-L6-v2
     running locally. The model is loaded once at module
     import and cached for the process lifetime.

R3.6 Three strategies must be implemented:
     CONSERVATIVE (target 20% reduction),
     MODERATE (target 35% reduction),
     AGGRESSIVE (target 55% reduction).
     Default: CONSERVATIVE.

R3.7 TOOL_RESULT segments older than 3 turns with score < 0.3
     are candidates for summarization (one sentence).
     REASONING_BLOCK segments with score < 0.4 are candidates
     for dropping. Nothing else is dropped in CONSERVATIVE mode.

R3.8 The engine must support LangChain, AutoGen, and raw
     OpenAI message formats via the adapter interface.

### R4 — OpenTelemetry Export

R4.1 The SDK must emit OTEL spans for every instrumented call.
R4.2 Default exporter: ConsoleSpanExporter (stdout, human-readable).
R4.3 Optional exporter: OTLPSpanExporter (gRPC) configurable via
     environment variable AXON_OTLP_ENDPOINT.
R4.4 Span attributes must follow OTEL GenAI semantic conventions
     where they exist, with `axon.*` namespace for Axon-specific
     attributes.

### R5 — CLI

R5.1 `axon analyze --input <file.jsonl>` reads a JSONL file
     of InferenceSpan records and outputs a cost summary:
     total cost, cost by model, cost by feature_tag,
     total tokens, estimated savings from compression (shadow).

R5.2 `axon version` prints the package version.

R5.3 `axon doctor` checks that required dependencies are installed
     (sentence-transformers, openai or anthropic) and prints
     status for each.

R5.4 CLI uses `typer` for argument parsing. Output uses `rich`
     for tables and formatting.

### R6 — Privacy

R6.1 Prompt content is never stored or logged. Only SHA-256
     hash of normalized (stripped, lowercased) content is retained.

R6.2 The SDK must not read, log, or transmit provider API keys.

### R7 — Distribution

R7.1 Package is publishable to PyPI as `axon-sdk`.
R7.2 `pip install axon-sdk` and `pip install axon-sdk[langchain]`
     must both work cleanly in a fresh virtualenv.
R7.3 `pip install axon-sdk[autogen]` for AutoGen support.

---

## Design

### Module map

```
axon/
├── __init__.py              # Public API surface: instrument(), patch(), configure()
├── py.typed
├── exceptions.py            # AxonError, AxonConfigError, AxonDependencyError
├── core/
│   ├── __init__.py
│   ├── instrumentor.py      # @instrument() decorator, patch() function
│   ├── provider_adapter.py  # ProviderAdapter ABC + OpenAI/Anthropic implementations
│   ├── span_emitter.py      # InferenceSpan → OTEL span
│   ├── cost_calculator.py   # Token counts → Decimal cost
│   └── pricing.py           # Static pricing table (Decimal values)
├── compression/
│   ├── __init__.py
│   ├── engine.py            # Main compression pipeline
│   ├── segment_parser.py    # messages[] → List[Segment]
│   ├── relevance_scorer.py  # Segment → float (0.0–1.0)
│   ├── strategies.py        # CompressionStrategy, CompressionConfig
│   └── adapters/
│       ├── __init__.py
│       ├── base.py          # FrameworkAdapter ABC
│       ├── langchain.py
│       ├── autogen.py
│       └── raw_openai.py
├── classifier/
│   ├── __init__.py
│   └── artifact_type.py     # ArtifactType enum + classify()
├── telemetry/
│   ├── __init__.py
│   └── otel_exporter.py     # Exporter config + span construction
├── models.py                # Pydantic models: InferenceSpan, CompressionResult, Segment
└── cli/
    ├── __init__.py
    └── main.py              # typer app
```

### Public API (axon/__init__.py)

```python
# These are the only symbols a user ever imports from axon directly.

def instrument(
    feature_tag: str = "default",
    shadow_mode: bool = True,
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
    environment: str = "production",
) -> Callable[..., Any]: ...

def patch(
    client: Any,  # openai.OpenAI | anthropic.Anthropic
    feature_tag: str = "default",
    shadow_mode: bool = True,
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
    environment: str = "production",
) -> None: ...

def configure(
    otlp_endpoint: str | None = None,
    export_to_stdout: bool = True,
    local_span_log: str | None = None,
) -> None: ...
```

### Key data models (axon/models.py)

```python
class InferenceSpan(BaseModel):
    id: UUID
    trace_id: str
    parent_span_id: str | None
    span_name: str
    timestamp: datetime
    duration_ms: int
    provider: str
    model: str
    api_version: str | None
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    token_count_method: Literal["exact", "estimated"]
    cost_usd: Decimal | None
    feature_tag: str
    prompt_hash: str          # SHA-256
    artifact_type: ArtifactType
    compression_applied: bool
    shadow_mode: bool
    pre_compression_tokens: int | None
    tokens_saved: int | None
    cache_hit: bool
    environment: str

class Segment(BaseModel):
    index: int
    role: str
    content: str
    artifact_type: ArtifactType
    token_count: int
    turn_index: int           # which conversation turn this belongs to
    protected: bool           # True if compression must not touch this
    embedding: list[float] | None = None

class CompressionResult(BaseModel):
    original_tokens: int
    compressed_tokens: int
    tokens_saved: int
    compression_ratio: float
    segments_analyzed: int
    segments_retained: int
    segments_summarized: int
    segments_dropped: int
    shadow_mode: bool
    strategy_applied: CompressionStrategy
    messages: list[dict[str, Any]]  # original if shadow, compressed if live
    warnings: list[str]
```

---

## Tasks

### T1 — Repository scaffold
- [ ] Initialize git repo with .gitignore (Python standard)
- [ ] Create all directories in module map above
- [ ] Create empty __init__.py files
- [ ] Create LICENSE (MIT, copyright Aarohi)
- [ ] Create CHANGELOG.md with Unreleased section
- [ ] Create CONTRIBUTING.md with setup instructions
- [ ] Commit: "chore: initialize repository structure"

### T2 — Exceptions module
- [ ] Implement axon/exceptions.py with AxonError base,
      AxonConfigError, AxonDependencyError, AxonCompressionError
- [ ] Full docstrings
- [ ] Commit: "feat(core): define exception hierarchy"

### T3 — Pricing table
- [ ] Implement axon/core/pricing.py
- [ ] Models: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo,
      claude-3-5-sonnet-20241022, claude-3-5-haiku-20241022,
      claude-3-opus-20240229, gemini-1.5-pro, gemini-1.5-flash
- [ ] All prices as Decimal strings (e.g., "2.50" = $2.50 per 1M tokens)
- [ ] Separate: input_cost_per_1m, output_cost_per_1m,
      cache_read_cost_per_1m (where applicable)
- [ ] Verify prices against official provider pricing pages
      before committing. Add pricing source URLs as comments.
- [ ] Commit: "feat(core): add provider pricing table"

### T4 — Cost calculator
- [ ] Implement axon/core/cost_calculator.py
- [ ] calculate_cost(model, input_tokens, output_tokens,
      cached_tokens=0) -> Decimal | None
- [ ] get_pricing(model) -> ModelPricing | None
- [ ] Tests: all models, edge cases (zero tokens, cached-only,
      unknown model), Decimal precision
- [ ] Commit: "feat(core): implement cost calculator"

### T5 — Artifact classifier
- [ ] Implement axon/classifier/artifact_type.py
- [ ] ArtifactType enum (9 values)
- [ ] classify(message, position_index, total_messages) -> ArtifactType
- [ ] classify_sequence(messages) -> list[ArtifactType]
- [ ] Tests: all artifact types, system prompt zero false negatives,
      tool result detection, edge cases
- [ ] Commit: "feat(classifier): implement artifact type classifier"

### T6 — Data models
- [ ] Implement axon/models.py
      InferenceSpan, Segment, CompressionResult, ModelPricing
- [ ] All Pydantic v2 models
- [ ] Validators where needed (e.g., compression_ratio 0.0–1.0)
- [ ] Commit: "feat(core): define SDK data models"

### T7 — Compression strategies
- [ ] Implement axon/compression/strategies.py
- [ ] CompressionStrategy enum
- [ ] CompressionConfig dataclass
- [ ] get_config(), validate_config()
- [ ] Tests: all strategies, config validation
- [ ] Commit: "feat(compression): add strategy configuration"

### T8 — Segment parser
- [ ] Implement axon/compression/segment_parser.py
- [ ] parse(messages, artifact_types) -> list[Segment]
- [ ] Token counting using tiktoken
- [ ] Adapter pattern: delegate format normalization to adapters
- [ ] Tests: LangChain format, raw OpenAI format, mixed types
- [ ] Commit: "feat(compression): implement segment parser"

### T9 — Compression adapters
- [ ] Implement axon/compression/adapters/base.py (ABC)
- [ ] Implement adapters/raw_openai.py (always available)
- [ ] Implement adapters/langchain.py (guarded import)
- [ ] Implement adapters/autogen.py (guarded import)
- [ ] Tests: each adapter with representative message arrays
- [ ] Commit: "feat(compression): add framework adapters"

### T10 — Relevance scorer
- [ ] Implement axon/compression/relevance_scorer.py
- [ ] Load all-MiniLM-L6-v2 once at module import
- [ ] score(segment, task_context_embedding) -> float
- [ ] score_batch(segments, task_context_embedding) -> list[float]
- [ ] Recency decay function (exponential, configurable k)
- [ ] Reference count heuristic
- [ ] Tests: score ordering (recent > old), protected segments,
      empty segments
- [ ] Benchmark: < 50ms for 20-segment context on CPU
- [ ] Commit: "feat(compression): implement relevance scorer"

### T11 — Compression engine
- [ ] Implement axon/compression/engine.py
- [ ] compress(messages, strategy, shadow_mode, task_hint) -> CompressionResult
- [ ] Full 7-step pipeline (parse → protect → score →
      compress → inject metadata → validate → record)
- [ ] CompressionValidationError triggers fallback to original
- [ ] Protection rules are unit-tested as invariants
- [ ] Tests: shadow mode correctness, protection invariants,
      all strategies, empty context, single-message context,
      context with only system prompt
- [ ] Commit: "feat(compression): implement compression engine"

### T12 — Provider adapter
- [ ] Implement axon/core/provider_adapter.py
- [ ] ProviderAdapter ABC
- [ ] OpenAIAdapter: extract tokens from response, detect streaming,
      extract model, extract cached tokens
- [ ] AnthropicAdapter: same
- [ ] Tests: mock HTTP responses for both providers
- [ ] Commit: "feat(core): add provider adapters"

### T13 — OTEL exporter
- [ ] Implement axon/telemetry/otel_exporter.py
- [ ] InferenceSpan → OTEL span with correct semantic conventions
- [ ] ConsoleSpanExporter by default
- [ ] OTLPSpanExporter when AXON_OTLP_ENDPOINT env var is set
- [ ] axon.* attribute namespace for Axon-specific fields
- [ ] Tests: span attribute mapping, exporter selection
- [ ] Commit: "feat(telemetry): implement OTEL span exporter"

### T14 — Instrumentor
- [ ] Implement axon/core/instrumentor.py
- [ ] @instrument() decorator (sync + async)
- [ ] patch() function for client-level wrapping
- [ ] Calls: provider_adapter → cost_calculator → compression engine
      (shadow) → span_emitter
- [ ] Overhead benchmark: median < 5ms on 1000 synthetic calls
- [ ] Tests: decorator on sync function, decorator on async function,
      patch on mock client, error in wrapped call
      (must not suppress original exception)
- [ ] Commit: "feat(core): implement instrumentation layer"

### T15 — Public API
- [ ] Implement axon/__init__.py
- [ ] Export: instrument, patch, configure, CompressionStrategy
- [ ] Version: __version__ = "0.1.0"
- [ ] Commit: "feat: expose public SDK API"

### T16 — CLI
- [ ] Implement axon/cli/main.py using typer
- [ ] Commands: analyze, version, doctor
- [ ] analyze: read JSONL, output rich table (cost by model,
      by feature_tag, compression savings, total)
- [ ] doctor: check sentence-transformers, openai/anthropic installed
- [ ] Tests: CLI invocation via typer's test client
- [ ] Commit: "feat(cli): implement analyze, version, doctor commands"

### T17 — pyproject.toml
- [ ] Build system: hatchling
- [ ] All runtime + optional dependencies
- [ ] Scripts: [project.scripts] axon = "axon.cli.main:app"
- [ ] Ruff config: line-length=88, target-version=py311,
      select all relevant rule sets
- [ ] Mypy config: strict=true
- [ ] Pytest config: testpaths, asyncio_mode=auto
- [ ] Coverage config: source=axon, fail_under=80
- [ ] Commit: "chore: add pyproject.toml"

### T18 — CI workflow
- [ ] .github/workflows/ci.yml
- [ ] Jobs: lint, type-check, test (with coverage), benchmark
- [ ] Benchmark job fails if SDK overhead > 5ms median
- [ ] .github/workflows/publish.yml
- [ ] Triggers on git tag v*; publishes to PyPI via trusted publisher
- [ ] Commit: "ci: add GitHub Actions workflows"

### T19 — Documentation
- [ ] README.md: what it is, what it is not, quickstart,
      architecture, structure, contributing
- [ ] docs/quickstart.md: 5-minute guide, three code examples
      (raw OpenAI, LangChain, async OpenAI)
- [ ] docs/compression-guide.md: shadow mode, strategies,
      enabling live compression, interpreting CompressionResult
- [ ] examples/openai-basic/main.py: runnable example
- [ ] examples/langchain-agent/main.py: runnable example
- [ ] Commit: "docs: add README, quickstart, compression guide, examples"

### T20 — Final validation
- [ ] `mypy axon --strict` passes with zero errors
- [ ] `ruff check axon tests` passes clean
- [ ] `pytest --cov=axon --cov-fail-under=80` passes
- [ ] `pip install -e ".[langchain,autogen,dev]"` succeeds
      in a fresh Python 3.11 virtualenv
- [ ] `axon doctor` runs and reports all dependencies present
- [ ] `axon version` prints "0.1.0"
- [ ] Compression shadow mode benchmark: < 50ms on 20-segment context
- [ ] SDK overhead benchmark: < 5ms median on 1000 calls