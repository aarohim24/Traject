# Implementation Plan: Axon SDK — Phase 1

## Overview

22 atomic commits that build the `axon-sdk` Python package from an empty
repository to a fully tested, PyPI-publishable SDK. Each task maps to exactly
one commit. All tests for a module are committed in the same task as the
module itself. The implementation language is **Python 3.11**.

---

## Tasks

- [-] 1. Initialize repository structure and license
  - Create the complete directory tree under `sdk/python/axon/` with all
    `__init__.py` files and the `py.typed` marker
  - Create `sdk/python/tests/` with `conftest.py` (empty fixtures scaffold)
    and `__init__.py` files for `unit/`, `integration/`, and `benchmarks/`
  - Create `.github/workflows/ci.yml` (stub), `.github/workflows/publish.yml`
    (stub), `.github/ISSUE_TEMPLATE/bug_report.md`,
    `.github/ISSUE_TEMPLATE/feature_request.md`,
    `.github/pull_request_template.md`
  - Create `docs/quickstart.md`, `docs/compression-guide.md`,
    `docs/architecture.md` (stubs with H1 headings only)
  - Create `examples/openai-basic/main.py`,
    `examples/openai-basic/README.md`,
    `examples/langchain-agent/main.py`,
    `examples/langchain-agent/README.md` (stubs)
  - Create `.gitignore` (Python standard: `__pycache__/`, `*.pyc`, `.venv/`,
    `dist/`, `*.egg-info/`, `.coverage`, `htmlcov/`, `.mypy_cache/`,
    `.ruff_cache/`)
  - Create `.pre-commit-config.yaml` (stub with `repos: []`)
  - Create `CHANGELOG.md` with `## [Unreleased]` section
  - Create `CONTRIBUTING.md` with setup instructions referencing
    `pip install -e ".[dev]"`
  - Create `LICENSE` (MIT, copyright Aarohi, current year)
  - _Commit: `chore: initialize repository structure and license`_
  - _Satisfies: R15.1, R16.8_

- [ ] 2. Define exception hierarchy
  - [~] 2.1 Implement `sdk/python/axon/exceptions.py`
    - Module docstring: one-sentence summary + extended description
    - `AxonError(Exception)` — base class; Google-style docstring
    - `AxonConfigError(AxonError)` — invalid configuration values
    - `AxonDependencyError(AxonError)` — optional framework not installed
    - `AxonCompressionError(AxonError)` — compression pipeline failure
    - `AxonProviderError(AxonError)` — unknown or unsupported provider
    - Each subclass has a one-line docstring and accepts a `message: str`
      argument forwarded to `super().__init__(message)`
    - Full type annotations; `mypy --strict` clean
    - _Requirements: R16.4, R17_
  - [ ]* 2.2 Write unit tests for exception hierarchy
    - File: `sdk/python/tests/unit/test_exceptions.py`
    - Test that each class is instantiable with a string message
    - Test that each subclass is an instance of `AxonError`
    - Test that `AxonError` is an instance of `Exception`
    - Test `str(exc)` returns the message passed at construction
    - _Requirements: R16.4, R17_
  - _Commit: `feat(core): define exception hierarchy`_
  - _Satisfies: R16.4, R17_

- [ ] 3. Add provider pricing table with verified prices
  - [~] 3.1 Implement `sdk/python/axon/core/pricing.py`
    - Module docstring explaining ADR-006 (Decimal) and ADR-010 (auditable)
    - Import `ModelPricing` from `axon.models` (forward reference — models
      module will be created in Task 6; use `TYPE_CHECKING` guard or define
      `ModelPricing` locally as a frozen dataclass here and re-export from
      models in Task 6)
    - `PROVIDER_PRICING: dict[str, ModelPricing]` with exactly 9 entries:
      `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`, `gpt-3.5-turbo`,
      `claude-3-5-sonnet-20241022`, `claude-3-5-haiku-20241022`,
      `claude-3-opus-20240229`, `gemini-1.5-pro`, `gemini-1.5-flash`
    - All `Decimal` values constructed from string literals (e.g.,
      `Decimal("2.50")`) — never from float literals (ADR-006)
    - Source URL comment above each provider block (OpenAI, Anthropic, Google)
    - `last_verified=date(2025, 1, 1)` on every entry
    - Exact values from design §2.8: gpt-4o input=2.50, output=10.00,
      cache_read=1.25; gpt-4o-mini input=0.15, output=0.60, cache_read=0.075;
      gpt-4-turbo input=10.00, output=30.00; gpt-3.5-turbo input=0.50,
      output=1.50; claude-3-5-sonnet input=3.00, output=15.00,
      cache_read=0.30, cache_write=3.75; claude-3-5-haiku input=0.80,
      output=4.00, cache_read=0.08, cache_write=1.00; claude-3-opus
      input=15.00, output=75.00, cache_read=1.50, cache_write=18.75;
      gemini-1.5-pro input=1.25, output=5.00, cache_read=0.3125;
      gemini-1.5-flash input=0.075, output=0.30, cache_read=0.01875
    - _Requirements: R1.4, R3.6, R16.5_
  - [ ]* 3.2 Write unit tests for pricing table
    - File: `sdk/python/tests/unit/test_pricing.py`
    - Assert all 9 model keys are present in `PROVIDER_PRICING`
    - Assert every `input_cost_per_1m_tokens` and
      `output_cost_per_1m_tokens` is a `Decimal` instance
    - Assert every cost value is `>= Decimal("0")`
    - Assert `cache_read_cost_per_1m_tokens` is `Decimal` or `None`
    - Assert `last_verified` is a `date` instance on every entry
    - Parametrize over all 9 model keys
    - _Requirements: R1.4, R3.6, R16.5_
  - _Commit: `feat(core): add provider pricing table with verified prices`_
  - _Satisfies: R1.4, R3.6, R16.5_

- [ ] 4. Implement cost calculator with Decimal precision
  - [~] 4.1 Implement `sdk/python/axon/core/cost_calculator.py`
    - Module docstring
    - `get_pricing(model: str) -> ModelPricing | None` — looks up
      `PROVIDER_PRICING`; returns `None` for unknown models (no exception)
    - `calculate_cost(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> Decimal | None`
    - Algorithm from design §2.2: `non_cached_input = input_tokens - cached_tokens`;
      `input_cost = (Decimal(non_cached_input) / Decimal("1000000")) * pricing.input_cost_per_1m_tokens`;
      `cache_cost = (Decimal(cached_tokens) / Decimal("1000000")) * pricing.cache_read_cost_per_1m_tokens`
      when `cached_tokens > 0` and `cache_read_cost_per_1m_tokens is not None`;
      `output_cost = (Decimal(output_tokens) / Decimal("1000000")) * pricing.output_cost_per_1m_tokens`;
      return `(input_cost + cache_cost + output_cost).quantize(Decimal("0.00000001"))`
    - Unknown model: log warning via `structlog.get_logger(__name__)` with
      key `"axon.cost.unknown_model"` and field `model=model`; return `None`
    - No `float` arithmetic anywhere in this module (ADR-006)
    - Full type annotations; Google-style docstrings with Args/Returns/Raises
    - _Requirements: R1.4, R3.6, R3.7, R3.8, R3.9, R16.5_
  - [ ]* 4.2 Write unit tests for cost calculator
    - File: `sdk/python/tests/unit/test_cost_calculator.py`
    - Parametrize over all 9 known models: assert return value is `Decimal`
      and `>= Decimal("0")`
    - Test zero input and output tokens: assert result is `Decimal("0")`
    - Test cached-only scenario: `input_tokens=1000, cached_tokens=1000,
      output_tokens=0` — assert cache rate applied, not standard input rate
    - Test unknown model string: assert return is `None`, no exception raised
    - Test Decimal precision: assert result has no more than 8 decimal places
    - Test no float drift: compute cost for 1,000,000 tokens and assert
      result equals expected `Decimal` exactly (not approximately)
    - **Property P9**: `@given(st.sampled_from(list(PROVIDER_PRICING.keys())), st.integers(min_value=0, max_value=10**6), st.integers(min_value=0, max_value=10**6))` — assert `calculate_cost(model, a, b) >= Decimal("0")`
    - **Property P10**: `@given(st.text())` filtered to exclude known keys — assert `calculate_cost(model, 0, 0) is None`
    - _Requirements: R3.6, R3.7, R3.8, R3.9_
  - _Commit: `feat(core): implement cost calculator with Decimal precision`_
  - _Satisfies: R1.4, R3.6, R3.7, R3.8, R3.9, R16.5_

- [ ] 5. Implement artifact type classifier
  - [~] 5.1 Implement `sdk/python/axon/classifier/artifact_type.py`
    - Module docstring
    - `ArtifactType(str, Enum)` with 9 members: `SYSTEM_PROMPT`,
      `USER_MESSAGE`, `ASSISTANT_MESSAGE`, `TOOL_RESULT`, `TOOL_CALL`,
      `RAG_CHUNK`, `FEW_SHOT_EXAMPLE`, `REASONING_BLOCK`, `UNKNOWN`
    - Module-level frozen sets from design §2.3:
      `_RAG_MARKERS`, `_FEW_SHOT_MARKERS`, `_REASONING_MARKERS`
    - Private helpers `_has_rag_markers`, `_has_few_shot_markers`,
      `_has_reasoning_markers` — each lowercases content and checks
      `any(marker in lower for marker in _MARKERS)`
    - `classify(message: dict[str, Any], position_index: int, total_messages: int) -> ArtifactType`
      — strict 9-priority chain from design §2.3; never raises for any input
      including empty dict or missing keys; uses `.get()` with defaults
    - `classify_sequence(messages: list[dict[str, Any]]) -> list[ArtifactType]`
      — calls `classify(msg, i, len(messages))` for each message; returns
      list of same length
    - No I/O, no ML, no imports beyond stdlib and `axon.exceptions`
    - _Requirements: R2.1, R2.2, R2.3, R5.1–5.6_
  - [ ]* 5.2 Write unit tests for artifact classifier
    - File: `sdk/python/tests/unit/test_artifact_classifier.py`
    - Test each of the 9 artifact types with a representative message
    - **Property P1 (system prompt zero false negatives)**: parametrize over
      20 context shapes (varying `position_index` 0–9, `total_messages` 1–20,
      content strings including empty, whitespace, long text) — assert
      `classify({"role": "system", "content": c}, i, n) == ArtifactType.SYSTEM_PROMPT`
    - **Property P2 (determinism)**: `@given(...)` — assert calling twice
      with same args returns same value
    - **Property P3 (total function)**: `@given(st.dictionaries(...))` —
      assert no exception raised and return is `ArtifactType` member
    - Edge cases: empty dict `{}`, dict with no `"role"` key, dict with
      `"role": None`, empty `"content"` string, `"content"` as list
    - Test `classify_sequence` returns list of same length as input
    - Test `classify_sequence` on empty list returns `[]`
    - Performance: assert `classify(msg, 0, 1)` completes in < 1ms using
      `time.perf_counter` (run 100 times, assert max < 1ms)
    - _Requirements: R2.1, R2.2, R2.3, R5.1–5.6_
  - _Commit: `feat(classifier): implement artifact type classifier`_
  - _Satisfies: R2.1, R2.2, R2.3, R5.1–5.6_

- [ ] 6. Define SDK data models with Pydantic v2
  - [~] 6.1 Implement `sdk/python/axon/models.py`
    - Module docstring
    - `ModelPricing` as `@dataclass(frozen=True)` with fields: `provider: str`,
      `model: str`, `input_cost_per_1m_tokens: Decimal`,
      `output_cost_per_1m_tokens: Decimal`,
      `cache_read_cost_per_1m_tokens: Decimal | None`,
      `cache_write_cost_per_1m_tokens: Decimal | None`,
      `pricing_url: str`, `last_verified: date`
    - `InferenceSpan(BaseModel)` — all fields from design §1.6.1; validators:
      `@field_validator("duration_ms")` asserts `>= 0`;
      `@field_validator("input_tokens", "output_tokens", "cached_tokens")`
      asserts `>= 0`;
      `@field_validator("prompt_hash")` asserts matches `^[a-f0-9]{64}$`;
      `@field_validator("cost_usd")` asserts `None` or `>= Decimal("0")`
    - `Segment(BaseModel)` — all fields from design §1.6.2; validators:
      `token_count >= 0`, `turn_index >= 0`;
      `embedding` is `None` or list of exactly 384 floats
    - `CompressionResult(BaseModel)` — all fields from design §1.6.3;
      validators: `0.0 <= compression_ratio <= 1.0`;
      `@model_validator(mode="after")` asserts
      `tokens_saved == original_tokens - compressed_tokens` and
      `segments_retained + segments_summarized + segments_dropped == segments_analyzed`
    - Update `axon/core/pricing.py` to import `ModelPricing` from
      `axon.models` (remove any local definition added in Task 3)
    - _Requirements: R2.1, R6.1, R10.1–10.4, R16.6_
  - [ ]* 6.2 Write unit tests for data models
    - File: `sdk/python/tests/unit/test_models.py`
    - Test valid `InferenceSpan` construction with all required fields
    - Test `duration_ms < 0` raises `ValidationError`
    - Test `input_tokens < 0` raises `ValidationError`
    - Test `prompt_hash` with 63-char hex raises `ValidationError`
    - Test `prompt_hash` with 64-char hex passes
    - Test `cost_usd = Decimal("-0.01")` raises `ValidationError`
    - Test valid `Segment` construction
    - Test `embedding` with 383 floats raises `ValidationError`
    - Test `embedding` with 384 floats passes
    - Test `CompressionResult` with `compression_ratio = 1.1` raises
      `ValidationError`
    - Test `CompressionResult` with inconsistent `tokens_saved` raises
      `ValidationError`
    - Test `ModelPricing` is immutable (assigning a field raises `FrozenInstanceError`)
    - _Requirements: R10.1–10.4, R16.6_
  - _Commit: `feat(core): define SDK data models with Pydantic v2`_
  - _Satisfies: R2.1, R6.1, R10.1–10.4, R16.6_

- [ ] 7. Add compression strategy configuration and defaults
  - [~] 7.1 Implement `sdk/python/axon/compression/strategies.py`
    - Module docstring
    - `CompressionStrategy(str, Enum)` with 3 members: `CONSERVATIVE`,
      `MODERATE`, `AGGRESSIVE` (string values lowercase)
    - `CompressionConfig` as `@dataclass(frozen=True)` with fields:
      `strategy: CompressionStrategy`, `target_reduction_pct: float`,
      `min_turns_protected: int`, `protect_system_prompt: bool`,
      `shadow_mode: bool`
    - `STRATEGY_DEFAULTS: dict[CompressionStrategy, CompressionConfig]`
      with exact values from design §2.10: CONSERVATIVE target=0.20
      min_turns=3; MODERATE target=0.35 min_turns=3; AGGRESSIVE
      target=0.55 min_turns=2; all with `protect_system_prompt=True,
      shadow_mode=True`
    - `get_config(strategy: CompressionStrategy) -> CompressionConfig`
      — returns `STRATEGY_DEFAULTS[strategy]`
    - `validate_config(config: CompressionConfig) -> None` — raises
      `AxonConfigError` if `target_reduction_pct` not in `(0.0, 1.0)`;
      raises `AxonConfigError` if `min_turns_protected < 0`; raises
      `AxonConfigError` if `protect_system_prompt is False`; exact
      error messages from design §2.10
    - _Requirements: R9.1–9.3, R17.3_
  - [ ]* 7.2 Write unit tests for strategy configuration
    - File: `sdk/python/tests/unit/test_strategies.py`
    - Test `get_config` returns correct defaults for all 3 strategies
    - Test `validate_config` passes for all 3 default configs
    - Test `validate_config` raises `AxonConfigError` for
      `target_reduction_pct=0.0`, `target_reduction_pct=1.0`,
      `target_reduction_pct=-0.1`, `target_reduction_pct=1.1`
    - Test `validate_config` raises `AxonConfigError` for
      `min_turns_protected=-1`
    - Test `validate_config` raises `AxonConfigError` for
      `protect_system_prompt=False`
    - Test `CompressionConfig` is immutable (frozen dataclass)
    - _Requirements: R9.1–9.3, R17.3_
  - _Commit: `feat(compression): add strategy configuration and defaults`_
  - _Satisfies: R9.1–9.3, R17.3_

- [ ] 8. Implement framework adapters — base ABC and RawOpenAIAdapter
  - [~] 8.1 Implement `sdk/python/axon/compression/adapters/base.py`
    - Module docstring
    - `FrameworkAdapter(ABC)` with three abstract methods:
      `normalize(self, messages: Any) -> list[dict[str, Any]]`,
      `denormalize(self, messages: list[dict[str, Any]], original: Any) -> Any`,
      `accepts(cls, messages: Any) -> bool` (classmethod + abstractmethod)
    - Full type annotations; Google-style docstrings on each method
    - _Requirements: R6.4, R6.5, R6.6_
  - [~] 8.2 Implement `sdk/python/axon/compression/adapters/raw_openai.py`
    - Module docstring
    - `RawOpenAIAdapter(FrameworkAdapter)`:
      - `accepts(cls, messages)` — returns `True` iff `messages` is a
        non-empty `list` and `messages[0]` is a `dict` containing both
        `"role"` and `"content"` keys
      - `normalize(self, messages)` — identity: returns `messages` unchanged
        (raw OpenAI format is already canonical)
      - `denormalize(self, messages, original)` — identity: returns
        `messages` unchanged
    - _Requirements: R6.6_
  - [ ]* 8.3 Write partial unit tests for adapters (raw OpenAI format)
    - File: `sdk/python/tests/unit/test_segment_parser.py` (partial — raw
      OpenAI format tests only; completed in Task 9)
    - Test `RawOpenAIAdapter.accepts()` returns `True` for valid
      `list[dict]` with role/content keys
    - Test `RawOpenAIAdapter.accepts()` returns `False` for empty list,
      non-list, list of non-dicts, list of dicts missing `"role"` key
    - Test `RawOpenAIAdapter.normalize()` returns the same object (identity)
    - Test `RawOpenAIAdapter.denormalize()` returns the same object
    - _Requirements: R6.6_
  - _Commit: `feat(compression): implement framework adapters (base + raw_openai)`_
  - _Satisfies: R6.4, R6.5, R6.6_

- [ ] 9. Implement segment parser with tiktoken
  - [~] 9.1 Implement `sdk/python/axon/compression/segment_parser.py`
    - Module docstring
    - `parse(messages: list[dict[str, Any]], artifact_types: list[ArtifactType]) -> list[Segment]`
    - Raises `AxonCompressionError` with descriptive message if
      `len(messages) != len(artifact_types)`
    - Uses `tiktoken.get_encoding("cl100k_base")` (cached by tiktoken
      internally — do not re-create per call)
    - Turn index tracking: starts at 0; increments when transitioning
      from `last_role == "assistant"` to current `role == "user"`
    - Token counting: if `content` is `str`, encode directly; if `content`
      is `list`, sum tokens for all parts where `part.get("type") == "text"`;
      otherwise `token_count = 0`
    - `protected = True` for any segment where
      `artifact_type == ArtifactType.SYSTEM_PROMPT`; also set `protected = True`
      if `msg.get("axon_preserve") is True`
    - `content` field on `Segment`: use `str(content)` if content is not
      already a string
    - Returns list of `Segment` objects of length `len(messages)`
    - _Requirements: R6.2, R7.1, R7.3_
  - [ ]* 9.2 Complete unit tests for segment parser
    - File: `sdk/python/tests/unit/test_segment_parser.py` (complete —
      extends partial file from Task 8)
    - Test `parse` with a 3-message conversation (system, user, assistant):
      assert 3 segments returned, correct roles, token counts > 0
    - Test turn index increments correctly across a multi-turn conversation
    - Test system prompt segment has `protected=True`
    - Test non-system segment has `protected=False` by default
    - Test `axon_preserve: True` metadata sets `protected=True`
    - Test list-format content (multi-part) token counting
    - Test `parse` raises `AxonCompressionError` when
      `len(messages) != len(artifact_types)`
    - Test empty messages list with empty artifact_types returns `[]`
    - _Requirements: R6.2, R7.1, R7.3_
  - _Commit: `feat(compression): implement segment parser with tiktoken`_
  - _Satisfies: R6.2, R7.1, R7.3_

- [ ] 10. Implement relevance scorer with local embedding model
  - [~] 10.1 Implement `sdk/python/axon/compression/relevance_scorer.py`
    - Module docstring
    - Module-level singleton: `_model: SentenceTransformer = SentenceTransformer("all-MiniLM-L6-v2")`
      loaded at import time (ADR-003); never reloaded
    - Constants: `_DECAY_RATE = 0.3`, `_RECENCY_WEIGHT = 0.4`,
      `_SEMANTIC_WEIGHT = 0.4`, `_REFERENCE_WEIGHT = 0.2`
    - `_compute_reference_counts(segments: list[Segment]) -> list[int]`
      — for each segment `i`, count how many segments `j > i` contain
      any word from segment `i`'s content in their content (simple
      substring heuristic)
    - `score_segments(segments: list[Segment], task_hint: str | None = None) -> list[float]`
      — full algorithm from design §2.5:
      (1) return `[]` for empty input;
      (2) compute `max_turn`;
      (3) if `task_hint`, encode once with `_model.encode(..., normalize_embeddings=True)`;
      (4) batch encode non-protected segment content;
      (5) store embeddings back on segments via `model_copy`;
      (6) compute reference counts;
      (7) for each segment: protected → 1.0; else compute recency
          `exp(-0.3 * (max_turn - seg.turn_index))`, semantic (cosine
          via `np.dot` or 1.0 if no task_hint), reference
          `min(1.0, count/3.0)`, composite weighted sum;
      (8) clamp all scores to `[0.0, 1.0]`
    - _Requirements: R7.4, R8.1–8.4_
  - [ ]* 10.2 Write unit tests for relevance scorer
    - File: `sdk/python/tests/unit/test_relevance_scorer.py`
    - Test score ordering: a segment at `turn_index=5` scores higher
      recency than one at `turn_index=0` (all else equal)
    - Test protected segments always return `1.0` regardless of content
    - Test empty segments list returns `[]`
    - Test all returned scores are in `[0.0, 1.0]` for a 5-segment input
    - Test with `task_hint=None`: semantic component defaults to 1.0
      (scores are still valid floats)
    - Test determinism: same inputs return same scores on two calls
    - Test `score_segments` returns list of same length as input
    - _Requirements: R7.4, R8.1–8.4_
  - _Commit: `feat(compression): implement relevance scorer with local embedding model`_
  - _Satisfies: R7.4, R8.1–8.4_

- [ ] 11. Implement compression engine with shadow mode
  - [~] 11.1 Implement `sdk/python/axon/compression/engine.py`
    - Module docstring
    - `_detect_adapter(messages: Any) -> FrameworkAdapter` — tries
      `RawOpenAIAdapter`, then optionally `LangChainAdapter` and
      `AutoGenAdapter` (guarded imports catching `AxonDependencyError`);
      raises `AxonCompressionError` if no adapter accepts; exact error
      message from design §2.11
    - `_apply_strategy(segment: Segment, score: float, strategy: CompressionStrategy, max_turn: int) -> Literal["RETAIN", "SUMMARIZE", "DROP"]`
      — implements all three decision tables from design §2.6 exactly:
      CONSERVATIVE (TOOL_RESULT older>3 turns + score<0.30 → SUMMARIZE;
      REASONING_BLOCK score<0.40 → DROP); MODERATE (TOOL_RESULT older>2
      turns + score<0.40 → SUMMARIZE; REASONING_BLOCK score<0.50 → DROP;
      RAG_CHUNK score<0.35 → DROP); AGGRESSIVE (TOOL_RESULT older>1 turn
      + score<0.50 → SUMMARIZE; REASONING_BLOCK score<0.60 → DROP;
      RAG_CHUNK score<0.45 → DROP; FEW_SHOT_EXAMPLE score<0.40 → DROP)
    - `_validate_compression_result(original, compressed, artifact_types, config) -> None`
      — raises `AxonCompressionError` if: any system prompt from original
      is absent from compressed (content equality); any message from the
      last `config.min_turns_protected` turn pairs is absent; or
      `len(compressed) < 1`
    - `compress(messages, config, task_hint=None, adapter=None) -> CompressionResult`
      — full 8-step pipeline from design §2.6; summarization produces
      `seg.content[:100] + " [summarized by Axon]"`; validation failure
      falls back to original messages with `compression_ratio=0.0`,
      `tokens_saved=0`, and warning appended; shadow mode sets
      `final_messages = messages`, `compressed_tokens = original_tokens`,
      `tokens_saved = 0`
    - Coverage target: ≥ 90% on this file (R16.3)
    - _Requirements: R6.1–6.6, R7.1–7.3, R9.1–9.4, R10.1–10.4, R17.4, R17.5_
  - [ ]* 11.2 Write unit tests for compression engine
    - File: `sdk/python/tests/unit/test_compression_engine.py`
    - **Property P4 (shadow mode identity)**: `@given(valid_messages_strategy)` —
      assert `compress(msgs, shadow_config).messages == msgs`
    - **Property P5 (system prompt immutability)**: parametrize over 20
      message shapes containing at least one `role=="system"` message —
      assert all system messages present in `result.messages`
    - **Property P6 (segment count invariant)**: `@given(...)` — assert
      `retained + summarized + dropped == analyzed`
    - **Property P7 (ratio bounds)**: `@given(...)` — assert
      `0.0 <= result.compression_ratio <= 1.0`
    - **Property P8 (token savings consistency)**: `@given(...)` — assert
      `result.tokens_saved == result.original_tokens - result.compressed_tokens`
    - Test all 3 strategies with a 10-message conversation containing
      TOOL_RESULT, REASONING_BLOCK, RAG_CHUNK, FEW_SHOT_EXAMPLE segments
    - Test empty context (single system prompt only): assert no crash,
      result returned
    - Test single-message context: assert result returned
    - Test validation failure fallback: mock `_validate_compression_result`
      to raise `AxonCompressionError`; assert original messages returned
      and `warnings` list is non-empty
    - Test `_detect_adapter` raises `AxonCompressionError` for unsupported
      format (e.g., plain string)
    - _Requirements: R6.1–6.6, R7.1–7.3, R9.1–9.4, R10.1–10.4_
  - _Commit: `feat(compression): implement compression engine with shadow mode`_
  - _Satisfies: R6.1–6.6, R7.1–7.3, R9.1–9.4, R10.1–10.4, R17.4, R17.5_

- [ ] 12. Add LangChain and AutoGen adapters
  - [~] 12.1 Implement `sdk/python/axon/compression/adapters/langchain.py`
    - Module docstring
    - Top-level guarded import: `try: from langchain_core.messages import ...`
      `except ImportError as exc: raise AxonDependencyError("LangChain adapter
      requires langchain-core. Install it with: pip install axon-sdk[langchain]") from exc`
    - `LangChainAdapter(FrameworkAdapter)`:
      - `accepts(cls, messages)` — `True` iff `isinstance(messages, list)
        and len(messages) > 0 and isinstance(messages[0], BaseMessage)`
      - `normalize(self, messages)` — maps each `BaseMessage` to
        `{"role": role, "content": str(msg.content)}`; role mapping:
        `HumanMessage→"user"`, `AIMessage→"assistant"`,
        `SystemMessage→"system"`, `ToolMessage→"tool"`, others→`"user"`;
        include `"tool_calls"` key if `hasattr(msg, "tool_calls") and msg.tool_calls`
      - `denormalize(self, messages, original)` — reconstruct `BaseMessage`
        subclasses from normalized dicts using role mapping
    - _Requirements: R6.4_
  - [~] 12.2 Implement `sdk/python/axon/compression/adapters/autogen.py`
    - Module docstring
    - Top-level guarded import: `try: import autogen` `except ImportError as exc:
      raise AxonDependencyError("AutoGen adapter requires pyautogen. Install it
      with: pip install axon-sdk[autogen]") from exc`
    - `AutoGenAdapter(FrameworkAdapter)`:
      - `accepts(cls, messages)` — `True` iff `isinstance(messages, list)
        and len(messages) > 0 and isinstance(messages[0], dict)
        and "role" in messages[0] and "content" in messages[0]
        and "name" in messages[0]` (AutoGen dicts have a `"name"` field)
      - `normalize(self, messages)` — strips `"name"` field, returns
        `[{"role": m["role"], "content": m["content"]} for m in messages]`
      - `denormalize(self, messages, original)` — re-adds `"name"` field
        from corresponding original message where available
    - _Requirements: R6.5_
  - [ ]* 12.3 Write unit tests for LangChain and AutoGen adapters
    - File: `sdk/python/tests/unit/test_segment_parser.py` (additions)
    - Test `LangChainAdapter.accepts()` with mock `BaseMessage` objects
    - Test `LangChainAdapter.normalize()` produces correct role/content dicts
    - Test `LangChainAdapter.denormalize()` reconstructs correct types
    - Test `LangChainAdapter` raises `AxonDependencyError` when
      `langchain-core` not installed (mock `ImportError`)
    - Test `AutoGenAdapter.accepts()` with AutoGen-style dicts (with `"name"`)
    - Test `AutoGenAdapter.normalize()` strips `"name"` field
    - _Requirements: R6.4, R6.5, R17.2_
  - _Commit: `feat(compression): add LangChain and AutoGen adapters`_
  - _Satisfies: R6.4, R6.5, R17.2_

- [ ] 13. Implement provider adapters (OpenAI + Anthropic)
  - [~] 13.1 Implement `sdk/python/axon/core/provider_adapter.py`
    - Module docstring
    - `UsageData` as `@dataclass` with fields: `input_tokens: int`,
      `output_tokens: int`, `cached_tokens: int`,
      `token_count_method: Literal["exact", "estimated"]`
    - `ProviderAdapter(ABC)` with abstract methods: `extract_usage(self, response: Any) -> UsageData`,
      `extract_model(self, response: Any) -> str`,
      `is_streaming(self, response: Any) -> bool`
    - `OpenAIAdapter(ProviderAdapter)`:
      - `is_streaming(self, response)` — returns `True` if response lacks
        a `choices` attribute or `type(response).__name__` contains
        `"Stream"` or `"Chunk"`
      - `extract_usage(self, response)` — algorithm from design §2.7:
        streaming without usage → return estimated zeros; non-streaming →
        read `response.usage.prompt_tokens` / `response.usage.completion_tokens`;
        cached tokens from `response.usage.prompt_tokens_details.cached_tokens`
        if present
      - `extract_model(self, response)` — returns `getattr(response, "model", "unknown")`
    - `AnthropicAdapter(ProviderAdapter)`:
      - `is_streaming(self, response)` — returns `True` if
        `type(response).__name__` contains `"Stream"` or `"Event"`
      - `extract_usage(self, response)` — reads `response.usage.input_tokens`,
        `response.usage.output_tokens`, `getattr(response.usage, "cache_read_input_tokens", 0) or 0`
      - `extract_model(self, response)` — returns `getattr(response, "model", "unknown")`
    - `get_adapter(provider: str) -> ProviderAdapter` — returns
      `OpenAIAdapter()` for `"openai"`, `AnthropicAdapter()` for
      `"anthropic"`; raises `AxonProviderError` with message listing
      supported providers for any other string
    - _Requirements: R3.1–3.5, R17.1_
  - [ ]* 13.2 Write unit tests for provider adapters
    - File: `sdk/python/tests/unit/test_provider_adapter.py`
    - Test `OpenAIAdapter.extract_usage()` with a mock non-streaming
      response object having `usage.prompt_tokens=100`,
      `usage.completion_tokens=50` — assert `input_tokens=100`,
      `output_tokens=50`, `token_count_method="exact"`
    - Test `OpenAIAdapter.extract_usage()` with cached tokens in
      `usage.prompt_tokens_details.cached_tokens=30` — assert
      `cached_tokens=30`
    - Test `OpenAIAdapter.extract_usage()` with streaming response
      (no `usage`) — assert `token_count_method="estimated"`
    - Test `AnthropicAdapter.extract_usage()` with mock response having
      `usage.input_tokens=80`, `usage.output_tokens=40`,
      `usage.cache_read_input_tokens=20` — assert all fields correct
    - Test `get_adapter("openai")` returns `OpenAIAdapter` instance
    - Test `get_adapter("anthropic")` returns `AnthropicAdapter` instance
    - Test `get_adapter("unknown_provider")` raises `AxonProviderError`
    - _Requirements: R3.1–3.5, R17.1_
  - _Commit: `feat(core): implement provider adapters (OpenAI + Anthropic)`_
  - _Satisfies: R3.1–3.5, R17.1_

- [ ] 14. Implement OTEL span exporter
  - [~] 14.1 Implement `sdk/python/axon/telemetry/otel_exporter.py`
    - Module docstring
    - Module-level `_tracer_provider: TracerProvider | None = None`
    - `configure_exporter(otlp_endpoint: str | None = None, export_to_stdout: bool = True) -> None`
      — idempotent (returns immediately if `_tracer_provider is not None`);
      creates `TracerProvider` with `Resource.create({"service.name": "axon-sdk",
      "service.version": __version__})`; adds `SimpleSpanProcessor(ConsoleSpanExporter())`
      if `export_to_stdout=True`; reads `AXON_OTLP_ENDPOINT` env var if
      `otlp_endpoint` is `None`; adds `BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))`
      if endpoint is set; calls `trace.set_tracer_provider(provider)`
    - `emit_span(span_data: InferenceSpan) -> None` — calls
      `configure_exporter()` (no-op if already configured); gets tracer
      via `trace.get_tracer("axon-sdk", __version__)`; opens span with
      `span_data.span_name`; sets all 15 OTEL attributes per design §1.5.8
      and §2.9 mapping table; `cost_usd` serialized as `str(span_data.cost_usd)`
      or `""` if `None`; `tokens_saved` as `span_data.tokens_saved or 0`
    - Import `__version__` from `axon` package (or define locally as `"0.1.0"`)
    - _Requirements: R4.1, R11.1–11.5_
  - [ ]* 14.2 Write unit tests for OTEL exporter
    - File: `sdk/python/tests/unit/test_otel_exporter.py`
    - Test `configure_exporter()` is idempotent: call twice, assert
      `_tracer_provider` is the same object both times
    - Test `configure_exporter()` with no env var uses `ConsoleSpanExporter`
    - Test `configure_exporter(otlp_endpoint="localhost:4317")` adds OTLP
      exporter (use `InMemorySpanExporter` or mock)
    - Test `emit_span()` sets all required OTEL attributes correctly:
      construct a valid `InferenceSpan`, call `emit_span`, capture span
      via `InMemorySpanExporter`, assert each attribute value
    - Test `cost_usd=None` serializes as `""` in `axon.cost_usd` attribute
    - Test `tokens_saved=None` serializes as `0` in
      `axon.compression.tokens_saved` attribute
    - _Requirements: R11.1–11.5_
  - _Commit: `feat(telemetry): implement OTEL span exporter`_
  - _Satisfies: R4.1, R11.1–11.5_

- [ ] 15. Implement instrumentation decorator and patch function
  - [~] 15.1 Implement `sdk/python/axon/core/instrumentor.py`
    - Module docstring
    - `_hash_prompt(messages: list[dict[str, Any]]) -> str` — algorithm
      from design §2.1: concatenate all `content` string fields (strip +
      lowercase), handle list-format content (extract `"text"` parts),
      return `hashlib.sha256(normalized.encode("utf-8")).hexdigest()`
    - `_extract_messages(args: tuple[Any, ...], kwargs: dict[str, Any]) -> list[dict[str, Any]] | None`
      — best-effort: look for `"messages"` key in kwargs first; then check
      if first positional arg is a list of dicts; return `None` if not found
    - `_detect_provider(fn: Any, args: tuple[Any, ...]) -> str` — inspect
      function module name or first arg's class name for `"openai"` or
      `"anthropic"`; return `"unknown"` if not determinable
    - `_run_instrumented_sync(fn, args, kwargs, config, feature_tag, environment) -> Any`
      — full algorithm from design §2.1: record start time, extract
      messages, hash prompt, run `compress()` in try/except `AxonError`,
      call `fn(*args, **kwargs)`, compute duration, extract usage via
      `get_adapter`, calculate cost, classify first message, build
      `InferenceSpan`, call `emit_span()`, return original response;
      all Axon errors caught and logged; caller exceptions never suppressed
    - `_run_instrumented_async(fn, args, kwargs, config, feature_tag, environment) -> Any`
      — async equivalent using `await fn(*args, **kwargs)`
    - `instrument(feature_tag, shadow_mode, strategy, environment) -> Callable`
      — returns decorator; detects sync vs async via
      `asyncio.iscoroutinefunction(fn)`; wraps with `functools.wraps`
    - `patch(client, feature_tag, shadow_mode, strategy, environment) -> None`
      — monkey-patches `client.chat.completions.create` (OpenAI) or
      `client.messages.create` (Anthropic) with instrumented wrapper
    - `configure(otlp_endpoint, export_to_stdout, local_span_log) -> None`
      — delegates to `configure_exporter()`
    - _Requirements: R1.1–1.6, R2.1–2.6, R4.1, R14.1–14.4_
  - [ ]* 15.2 Write unit tests for instrumentor
    - File: `sdk/python/tests/unit/test_instrumentor.py`
    - Test sync decorator: wrap a function that returns a mock response;
      assert return value is unchanged
    - Test async decorator: wrap an async function; assert return value
      is unchanged using `pytest.mark.asyncio`
    - Test `patch()` on a mock client object: assert the patched method
      is called and returns original response
    - Test `AxonError` during pipeline does not suppress caller exception:
      mock `compress()` to raise `AxonCompressionError`; assert original
      response still returned
    - Test caller exception propagates: mock `fn` to raise `ValueError`;
      assert `ValueError` is re-raised unchanged
    - Test `_hash_prompt([])` returns SHA-256 of empty string:
      `"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"`
    - Test `_hash_prompt` with known messages returns expected 64-char hex
    - Test `_hash_prompt` with list-format content extracts text parts
    - _Requirements: R1.1–1.6, R2.3, R14.1–14.4_
  - _Commit: `feat(core): implement instrumentation decorator and patch function`_
  - _Satisfies: R1.1–1.6, R2.1–2.6, R4.1, R14.1–14.4_

- [ ] 16. Expose public SDK API surface
  - [~] 16.1 Implement `sdk/python/axon/__init__.py`
    - Module docstring from design §2.13: one-sentence summary + extended
      description
    - `__version__ = "0.1.0"`
    - Import `instrument`, `patch`, `configure` from
      `axon.core.instrumentor`
    - Import `CompressionStrategy` from `axon.compression.strategies`
    - Import `AxonError`, `AxonConfigError`, `AxonDependencyError`,
      `AxonCompressionError`, `AxonProviderError` from `axon.exceptions`
    - `__all__` list containing all 10 exported names plus `"__version__"`
    - Verify `py.typed` marker file exists at `sdk/python/axon/py.typed`
      (created in Task 1)
    - No logic in this file — imports only
    - _Requirements: R15.1, R15.8_
  - _Commit: `feat: expose public SDK API surface`_
  - _Satisfies: R15.1, R15.8_

- [ ] 17. Implement CLI — analyze, version, and doctor commands
  - [~] 17.1 Implement `sdk/python/axon/cli/main.py`
    - Module docstring
    - `app = typer.Typer(name="axon", help="Axon SDK developer tools.")`
    - `console = Console()` from `rich.console`
    - `analyze` command: `--input` (required `Path`), `--format` (default
      `"table"`); reads JSONL line by line; skips malformed lines with
      `structlog` warning (never crashes); parses each valid line as
      `InferenceSpan.model_validate_json(line)`; aggregates by
      `(model, feature_tag)` into dict accumulating `calls`, `input_tokens`,
      `output_tokens`, `cost_usd` (sum as `Decimal`), `tokens_saved` (sum),
      `cache_hits` (count where `cache_hit=True`); for `--format table`
      outputs `rich.table.Table` with columns: Model, Feature Tag, Calls,
      Input Tokens, Output Tokens, Cost USD, Shadow Savings, Cache Hits;
      for `--format json` outputs `json.dumps(aggregated, default=str)`;
      if file not found, print error and `raise typer.Exit(code=1)`
    - `version` command: `console.print(f"axon-sdk {__version__}")`
    - `doctor` command: algorithm from design §2.12; checks
      `sentence_transformers` (required), `opentelemetry.sdk` (required),
      `tiktoken` (required), `openai` (optional), `anthropic` (optional);
      `raise typer.Exit(code=0 if all_required_ok else 1)`
    - Also check `AXON_OTLP_ENDPOINT` env var in doctor output (display
      as set/not set)
    - No `print()` statements — use `console.print()` or `structlog`
    - _Requirements: R12.1–12.4, R13.1–13.5_
  - [ ]* 17.2 Write unit tests for CLI
    - File: `sdk/python/tests/unit/test_cli.py`
    - Use `typer.testing.CliRunner` for all tests
    - Test `axon version` exits 0 and stdout contains `"axon-sdk 0.1.0"`
    - Test `axon doctor` exits 0 when all required deps importable (mock
      `importlib.import_module` to succeed)
    - Test `axon doctor` exits 1 when a required dep is missing (mock
      `importlib.import_module` to raise `ImportError` for `tiktoken`)
    - Test `axon analyze --input <valid_jsonl>` exits 0 and outputs table
      with correct aggregated values (write temp JSONL file with 2 spans)
    - Test `axon analyze --input <nonexistent>` exits 1 with error message
    - Test `axon analyze` with malformed JSONL line: assert command still
      exits 0 and processes valid lines (malformed line skipped)
    - Test `axon analyze --format json` outputs valid JSON
    - _Requirements: R12.1–12.4, R13.1–13.5_
  - _Commit: `feat(cli): implement analyze, version, and doctor commands`_
  - _Satisfies: R12.1–12.4, R13.1–13.5_

- [ ] 18. Add pyproject.toml with full dependency specification
  - [~] 18.1 Create `sdk/python/pyproject.toml`
    - `[build-system]`: `requires = ["hatchling"]`,
      `build-backend = "hatchling.build"`
    - `[project]`: `name = "axon-sdk"`, `version = "0.1.0"`,
      `requires-python = ">=3.11"`, `license = {text = "MIT"}`
    - `[project.dependencies]` (runtime, minimum compatible versions):
      `opentelemetry-sdk>=1.24`, `opentelemetry-api>=1.24`,
      `opentelemetry-exporter-otlp-proto-grpc>=1.24`, `pydantic>=2.6`,
      `structlog>=24.1`, `sentence-transformers>=3.0`, `tiktoken>=0.7`,
      `typer>=0.12`, `rich>=13.0`
    - `[project.optional-dependencies]`:
      `openai = ["openai>=1.30"]`,
      `anthropic = ["anthropic>=0.28"]`,
      `langchain = ["langchain-core>=0.2"]`,
      `autogen = ["pyautogen>=0.2"]`,
      `dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-cov>=5.0",
      "respx>=0.21", "hypothesis>=6.0", "mypy>=1.10", "ruff>=0.4",
      "pre-commit>=3.7"]`
    - `[project.scripts]`: `axon = "axon.cli.main:app"`
    - `[tool.ruff]`: `line-length = 88`, `target-version = "py311"`
    - `[tool.ruff.lint]`: `select = ["E", "F", "I", "N", "UP", "ANN", "B", "SIM", "RUF"]`,
      `ignore = ["ANN101", "ANN102"]`
    - `[tool.mypy]`: `strict = true`, `python_version = "3.11"`
    - `[tool.pytest.ini_options]`: `testpaths = ["tests"]`,
      `asyncio_mode = "auto"`,
      `addopts = "--cov=axon --cov-report=term-missing --cov-fail-under=80"`
    - `[tool.coverage.run]`: `source = ["axon"]`,
      `omit = ["axon/cli/*"]`
    - `[tool.hatch.build.targets.wheel]`: `packages = ["axon"]`
    - _Requirements: R15.1–15.8, R16.1–16.3_
  - _Commit: `chore: add pyproject.toml with full dependency specification`_
  - _Satisfies: R15.1–15.8, R16.1–16.3_

- [ ] 19. Add GitHub Actions CI and publish workflows
  - [~] 19.1 Implement `.github/workflows/ci.yml`
    - Trigger: `on: [push, pull_request]` on all branches
    - `runs-on: ubuntu-latest`, `python-version: "3.11"` for all jobs
    - Job `lint`: `pip install ruff`; `ruff check axon tests`;
      `ruff format --check axon tests`
    - Job `type-check`: `pip install mypy pydantic`; `mypy axon --strict`
    - Job `test`: `pip install -e ".[dev,openai,anthropic,langchain]"`;
      `pytest --cov=axon --cov-report=xml --cov-fail-under=80`
    - Job `benchmark`: `pip install -e ".[dev,openai]"`;
      run `python tests/benchmarks/bench_sdk_overhead.py --assert-median-ms 5`;
      run `python tests/benchmarks/bench_compression_latency.py --assert-median-ms 50`;
      step fails if either script exits non-zero
    - _Requirements: R4.1, R16.1–16.3_
  - [~] 19.2 Implement `.github/workflows/publish.yml`
    - Trigger: `on: push: tags: ["v*"]`
    - Single job `publish`: `runs-on: ubuntu-latest`; uses PyPI trusted
      publisher (`id-token: write` permission); steps: checkout, setup
      Python 3.11, `pip install hatchling`, `python -m hatchling build`,
      `pypa/gh-action-pypi-publish@release/v1` with `skip-existing: true`
    - _Requirements: R15.1_
  - [~] 19.3 Create benchmark files
    - `sdk/python/tests/benchmarks/bench_sdk_overhead.py`: imports `axon`,
      creates mock OpenAI client (returns canned response in < 1ms), runs
      `@axon.instrument()` wrapped function 1000 times, collects wall-clock
      durations, prints min/p50/p95/p99/max table, asserts median < 5ms;
      accepts `--assert-median-ms` CLI arg (default 5); exits 1 if assertion
      fails
    - `sdk/python/tests/benchmarks/bench_compression_latency.py`: builds
      synthetic message arrays of 5, 10, 20, 50 segments, runs
      `compress(messages, config)` 100 times each, collects latencies,
      prints table, asserts p50 < 50ms for 20-segment context; accepts
      `--assert-median-ms` CLI arg (default 50); exits 1 if assertion fails
    - _Requirements: R4.1, R8.4_
  - _Commit: `ci: add GitHub Actions CI and publish workflows`_
  - _Satisfies: R4.1, R15.1, R16.1–16.3_

- [ ] 20. Add pre-commit configuration
  - [~] 20.1 Implement `.pre-commit-config.yaml`
    - `repos:` section with two entries:
    - `ruff-pre-commit` hook (from `https://github.com/astral-sh/ruff-pre-commit`):
      two hooks — `id: ruff` with `args: [--fix]` and `id: ruff-format`
    - `mypy` hook (from `https://github.com/pre-commit/mirrors-mypy`):
      `id: mypy`, `additional_dependencies: [pydantic>=2.6, types-all]`,
      `args: [--strict]`
    - Pin each repo to a specific `rev` tag (use latest stable at time of
      writing; document the version in a comment)
    - _Requirements: R16.1, R16.2_
  - _Commit: `chore: add pre-commit configuration`_
  - _Satisfies: R16.1, R16.2_

- [ ] 21. Add README, quickstart, compression guide, and examples
  - [~] 21.1 Write `README.md` at repo root
    - Sections: What Axon Is, What Axon Is Not (no backend, no data
      exfiltration), Quickstart (3-line install + decorator example),
      Architecture (module map from design §1.2), Contributing (link to
      CONTRIBUTING.md)
    - Include badges: PyPI version, CI status, license
    - _Requirements: R15.1_
  - [~] 21.2 Write `docs/quickstart.md`
    - 5-minute guide with 3 runnable code examples:
      (1) Raw OpenAI: `@axon.instrument(feature_tag="chat")` on a function
      calling `openai.OpenAI().chat.completions.create()`
      (2) LangChain: `axon.patch(chain)` on a LangChain chain
      (3) Async OpenAI: `@axon.instrument()` on an `async def` function
    - Each example shows the expected console output (OTEL span JSON)
    - _Requirements: R1.1, R1.5_
  - [~] 21.3 Write `docs/compression-guide.md`
    - Sections: Shadow Mode (what it is, why it's the default, how to
      read `CompressionResult`), Strategies (table of CONSERVATIVE /
      MODERATE / AGGRESSIVE with targets and decision rules), Enabling
      Live Compression (`shadow_mode=False` — document the risk),
      Interpreting `CompressionResult` fields
    - _Requirements: R6.1, R9.1–9.3_
  - [~] 21.4 Write runnable examples
    - `examples/openai-basic/main.py`: complete runnable script using
      `@axon.instrument(feature_tag="demo", shadow_mode=True)` on a
      function that calls `openai.OpenAI().chat.completions.create()`
      with a 3-message conversation; prints the response
    - `examples/langchain-agent/main.py`: complete runnable script using
      `axon.patch()` on a LangChain `ChatOpenAI` chain; runs a simple
      prompt; prints the response
    - Both examples include `if __name__ == "__main__":` guard
    - _Requirements: R1.1, R1.2_
  - [~] 21.5 Write integration test files
    - `sdk/python/tests/integration/test_openai_instrumentation.py`:
      mock HTTP via `respx`; set up a mock OpenAI endpoint returning a
      canned `ChatCompletion` response with `usage.prompt_tokens=100`,
      `usage.completion_tokens=50`; call an `@axon.instrument()` wrapped
      function; capture emitted span via `InMemorySpanExporter`; assert
      `gen_ai.usage.input_tokens=100`, `gen_ai.usage.output_tokens=50`,
      `axon.cost_usd` is non-empty string
    - `sdk/python/tests/integration/test_langchain_instrumentation.py`:
      mock a LangChain chain's `invoke` method; call via `axon.patch()`;
      assert `LangChainAdapter.normalize()` was invoked and span was emitted
      with correct `gen_ai.system` attribute
    - _Requirements: R1.1, R1.2, R11.1_
  - _Commit: `docs: add README, quickstart, compression guide, examples`_
  - _Satisfies: R1.1, R1.2, R6.1, R9.1–9.3, R15.1_

- [~] 22. Final validation — all checks passing
  - Verify `mypy axon --strict` passes with zero errors
  - Verify `ruff check axon tests` passes with zero issues
  - Verify `ruff format --check axon tests` passes with zero issues
  - Verify `pytest --cov=axon --cov-fail-under=80` passes (overall ≥ 80%)
  - Verify `pytest --cov=axon/compression/engine.py --cov-fail-under=90`
    passes (engine.py ≥ 90%)
  - Verify `pip install -e ".[langchain,autogen,dev]"` succeeds in a
    fresh Python 3.11 virtualenv
  - Verify `axon doctor` exits 0 with all required deps present
  - Verify `axon version` prints `"axon-sdk 0.1.0"`
  - Verify `python tests/benchmarks/bench_sdk_overhead.py --assert-median-ms 5`
    exits 0 (median overhead < 5ms)
  - Verify `python tests/benchmarks/bench_compression_latency.py --assert-median-ms 50`
    exits 0 (p50 < 50ms for 20-segment context)
  - No new files created in this task — verification only
  - _Commit: `chore: final validation — all checks passing`_
  - _Satisfies: R4.1, R16.1–16.3_

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP;
  all non-starred sub-tasks must be implemented
- Each task references specific requirements for traceability
- Checkpoints are embedded in the commit sequence — every commit must leave
  all existing tests passing
- Property tests (P1–P11) validate universal correctness properties from
  design Part 3; unit tests validate specific examples and edge cases
- The `hypothesis` library is used for all property-based tests
- Test files mirror source files: `axon/core/foo.py` → `tests/unit/test_foo.py`
- `axon/cli/*` is excluded from coverage measurement (see pyproject.toml)
- The embedding model (`all-MiniLM-L6-v2`) is loaded at module import in
  Task 10; tests that import `relevance_scorer` will pay the ~200ms load
  cost once per test session
- Tasks 8 and 9 share `tests/unit/test_segment_parser.py`; Task 8 creates
  the file with partial content, Task 9 completes it
- Tasks 12 adds to `tests/unit/test_segment_parser.py` for adapter tests

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1", "3.1"] },
    { "id": 1, "tasks": ["2.2", "3.2", "4.1"] },
    { "id": 2, "tasks": ["4.2", "5.1"] },
    { "id": 3, "tasks": ["5.2", "6.1"] },
    { "id": 4, "tasks": ["6.2", "7.1"] },
    { "id": 5, "tasks": ["7.2", "8.1", "8.2"] },
    { "id": 6, "tasks": ["8.3", "9.1"] },
    { "id": 7, "tasks": ["9.2", "10.1"] },
    { "id": 8, "tasks": ["10.2", "11.1"] },
    { "id": 9, "tasks": ["11.2", "12.1", "12.2"] },
    { "id": 10, "tasks": ["12.3", "13.1"] },
    { "id": 11, "tasks": ["13.2", "14.1"] },
    { "id": 12, "tasks": ["14.2", "15.1"] },
    { "id": 13, "tasks": ["15.2", "16.1"] },
    { "id": 14, "tasks": ["17.1"] },
    { "id": 15, "tasks": ["17.2", "18.1"] },
    { "id": 16, "tasks": ["19.1", "19.2", "19.3"] },
    { "id": 17, "tasks": ["20.1"] },
    { "id": 18, "tasks": ["21.1", "21.2", "21.3", "21.4", "21.5"] }
  ]
}
```
