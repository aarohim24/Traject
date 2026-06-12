# Axon Phase 3 — Implementation Tasks

## Task Dependency Graph

```
01 → 02 → 03 → 04 → 05 → 06
                          ↓
07 → 08 → 09
          ↓
10 → 11 → 12
           ↓
13 → 14 → 15 → 16 → 17
                     ↓
18 → 19 → 20 → 21
```

All tasks from commit 06 onward are sequential. Tasks 01–05, 07–08, 10–11, 13–16 within their groups have internal dependencies shown above.

---

## Task 1 — feat(router): add task type classifier with heuristic detection

**Commit:** `feat(router): add task type classifier with heuristic detection`

Create `sdk/python/axon/router/__init__.py` and `sdk/python/axon/router/task_classifier.py`.

- [x] Create `sdk/python/axon/router/__init__.py` — empty with module docstring
- [x] Implement `TaskType(str, Enum)` with all 10 values
- [x] Implement `classify_task(messages: list[dict[str, Any]]) -> TaskType` with all 11 priority-ordered detection signals (case-insensitive keyword matching)
- [x] Implement `estimate_complexity(messages: list[dict[str, Any]], task_type: TaskType) -> float` — returns [0.0, 1.0] always, never raises
- [ ] Full type annotations, mypy --strict clean
- [x] Module-level docstring + Google-style docstrings on all public functions
- [x] No print(), structlog for any logging

---

## Task 2 — feat(router): add routing table with default model tier mapping

**Commit:** `feat(router): add routing table with default model tier mapping`

Create `sdk/python/axon/router/routing_table.py`.

- [ ] Implement `ModelTier(str, Enum)` with TIER_1, TIER_2, TIER_3
- [x] Implement `ComplexityTier(str, Enum)` with LOW (0.0–0.39), MEDIUM (0.40–0.69), HIGH (0.70–1.0)
- [x] Implement `complexity_score_to_tier(score: float) -> ComplexityTier`
- [x] Implement `RoutingDecision` dataclass with all 9 fields (frozen=True)
- [x] Define `DEFAULT_ROUTING_TABLE` matching the spec exactly for all 10 TaskTypes
- [x] Define `DEFAULT_MODEL_MAP` for openai and anthropic providers
- [ ] Full type annotations, mypy --strict clean

---

## Task 3 — feat(router): add A/B test config with deterministic group assignment

**Commit:** `feat(router): add A/B test config with deterministic group assignment`

Create `sdk/python/axon/router/ab_test.py`.

- [x] Implement `ABTestConfig` dataclass with `treatment_model`, `treatment_pct`, `feature_tag`, `seed=42`
- [ ] Implement `assign_group(self, request_id: str) -> str` using SHA-256 hash of `f"{seed}:{request_id}"` for deterministic splitting
- [ ] Return `"treatment"` when hash-derived float < treatment_pct, else `"control"`
- [x] Validate `treatment_pct` in [0.0, 1.0] in `__post_init__`, raise `AxonConfigError` on violation
- [ ] Full type annotations, mypy --strict clean

---

## Task 4 — feat(router): implement RuleRouter with transparent model routing

**Commit:** `feat(router): implement RuleRouter with transparent model routing`

Create `sdk/python/axon/router/rule_router.py`.

- [x] Implement `RuleRouter.__init__` accepting provider, optional routing_table, model_map, ab_test
- [x] Implement `route(messages, requested_model, override_task_type)` — classify → estimate → tier lookup → A/B → return RoutingDecision; never raises
- [x] Implement `apply(decision, client, messages, **kwargs)` — calls client with decision.selected_model, returns response
- [x] Log structlog warning when selected_model differs from requested_model
- [x] Compute `cost_delta_pct` using `axon.core.pricing.PROVIDER_PRICING`
- [ ] Full type annotations, mypy --strict clean

---

## Task 5 — feat(router): integrate router with instrumentor configure()

**Commit:** `feat(router): integrate router with instrumentor configure()`

Modify `sdk/python/axon/core/instrumentor.py` (surgical change only).

- [x] Add module-level `_router: RuleRouter | None = None`
- [x] Add `router: RuleRouter | None = None` parameter to `configure()`
- [x] In `configure()`, set `global _router` when router is not None
- [x] In async and sync wrappers in `instrument()`, call `_router.route(messages, model)` before the LLM call when `_router` is set
- [x] Guard `RuleRouter` import with `TYPE_CHECKING` to prevent circular imports
- [x] Existing tests must still pass — verify no behaviour change when router=None

---

## Task 6 — test(router): add unit tests for classifier, routing table, router

**Commit:** `test(router): add unit tests for classifier, routing table, router`

Create test files under `sdk/python/tests/unit/`.

- [x] Create `tests/unit/test_task_classifier.py`:
  - Parametrized test: one representative prompt per TaskType → correct classification
  - Test: empty list returns UNKNOWN, never raises
  - Test: malformed dicts (missing keys, None values) never raise
  - PBT: `estimate_complexity` always returns [0.0, 1.0] for hypothesis-generated inputs
- [x] Create `tests/unit/test_rule_router.py`:
  - Parametrized: every (TaskType, ComplexityTier) combination routes to correct ModelTier
  - Test: A/B determinism — same request_id always same group
  - Test: `route()` returns original_model when an internal exception would occur
  - Test: `cost_delta_pct` is negative for downgrade, 0.0 for same model
- [x] Create `tests/unit/test_routing_table.py`:
  - Test: DEFAULT_ROUTING_TABLE covers all TaskType × ComplexityTier combinations
  - Test: `complexity_score_to_tier` boundary values (0.0, 0.39, 0.40, 0.69, 0.70, 1.0)

---

## Task 7 — feat(tracer): add W3C TraceContext propagator

**Commit:** `feat(tracer): add W3C TraceContext propagator`

Create `sdk/python/axon/tracer/__init__.py` and `sdk/python/axon/tracer/context_propagator.py`.

- [ ] Create `sdk/python/axon/tracer/__init__.py` — empty with module docstring
- [ ] Define `TRACEPARENT_HEADER = "traceparent"` and `TRACESTATE_HEADER = "tracestate"`
- [ ] Implement `inject_trace_context(headers, trace_id, span_id) -> dict[str, str]` — sets traceparent in format `"00-{trace_id}-{span_id}-01"`
- [ ] Implement `extract_trace_context(headers) -> tuple[str, str] | None` — case-insensitive header lookup, regex validation, returns None on malformed input, never raises
- [ ] Define regex `_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")`
- [x] Full type annotations, mypy --strict clean, Google-style docstrings

---

## Task 8 — feat(tracer): implement CascadeTracer with orchestrator/sub-agent API

**Commit:** `feat(tracer): implement CascadeTracer with orchestrator/sub-agent API`

Create `sdk/python/axon/tracer/cascade_tracer.py`.

- [x] Implement `TraceContext` dataclass with `trace_id`, `span_id`, `feature_tag`, `metadata`; add `outbound_headers() -> dict[str, str]` method
- [x] Implement `CascadeCostSummary` dataclass with all 6 fields; use `Decimal` for all cost fields
- [x] Implement `CascadeTracer.start_orchestration(feature_tag, metadata)` — generates trace_id via `uuid.uuid4().hex`, span_id via `uuid.uuid4().hex[:16]`
- [x] Implement `CascadeTracer.join_trace(inbound_headers)` — calls `extract_trace_context`, returns None on failure (fail open)
- [x] Implement `CascadeTracer.get_cascade_cost(trace_id, backend_client)` — returns empty summary when backend_client is None; queries backend otherwise
- [ ] Full type annotations, mypy --strict clean

---

## Task 9 — test(tracer): add unit tests for context propagation and cascade cost

**Commit:** `test(tracer): add unit tests for context propagation and cascade cost`

Create `sdk/python/tests/unit/test_cascade_tracer.py`.

- [x] Test: `inject_trace_context` produces valid traceparent matching `^00-[0-9a-f]{32}-[0-9a-f]{16}-01$`
- [x] Test: inject → extract round-trip returns identical trace_id and span_id
- [x] Test: `extract_trace_context` returns None for missing, empty, and truncated traceparent headers — never raises
- [x] PBT: hypothesis arbitrary strings as traceparent value never cause `extract_trace_context` to raise
- [x] Test: `start_orchestration` produces valid 32-hex trace_id and 16-hex span_id
- [x] Test: `join_trace` with valid headers returns TraceContext with matching trace_id
- [x] Test: `join_trace` with empty dict returns None
- [x] Test: `get_cascade_cost` with no backend_client returns CascadeCostSummary with Decimal("0") totals

---

## Task 10 — feat(advisor): implement PromptCacheAdvisor with stable/volatile split

**Commit:** `feat(advisor): implement PromptCacheAdvisor with stable/volatile split`

Create `sdk/python/axon/advisor/__init__.py` and `sdk/python/axon/advisor/prompt_cache_advisor.py`.

- [ ] Create `sdk/python/axon/advisor/__init__.py` — empty with module docstring
- [ ] Define `CACHE_THRESHOLDS = {"anthropic": 1024, "openai": 1024}`
- [x] Define `_VOLATILE_PATTERNS` list: `{variable}` format strings, ISO dates, today/now/current date, username/session keywords
- [x] Implement `CacheOpportunity` dataclass with 5 fields
- [x] Implement `AdvisorReport` dataclass with 5 fields
- [x] Implement `PromptCacheAdvisor.analyze_prompt(system_prompt, provider) -> CacheOpportunity | None` using tiktoken cl100k_base, line-by-line volatile detection
- [x] Implement `PromptCacheAdvisor.analyze_spans(spans) -> AdvisorReport` grouping by prompt_hash
- [x] Implement `PromptCacheAdvisor.analyze_directory(jsonl_path) -> AdvisorReport` reading JSONL InferenceSpan records
- [x] No internal axon imports beyond `axon.models`; no circular dependencies
- [ ] Full type annotations, mypy --strict clean

---

## Task 11 — feat(advisor): add cache-advisor CLI command

**Commit:** `feat(advisor): add cache-advisor CLI command`

Modify `sdk/python/axon/cli/main.py`.

- [ ] Add `@app.command(name="cache-advisor")` function `cache_advisor(input, provider)`
- [ ] Accept `--input` / `-i` (Path, required) and `--provider` / `-p` (str, default "anthropic")
- [ ] Call `PromptCacheAdvisor().analyze_directory(str(input))`
- [ ] Print rich Table with columns: Provider, Token Count, Est. Savings %, Recommendation
- [ ] Exit 1 if input file not found
- [ ] `axon --help` must list `cache-advisor` as a subcommand

---

## Task 12 — test(advisor): add unit tests for advisor analysis

**Commit:** `test(advisor): add unit tests for advisor analysis`

Create `sdk/python/tests/unit/test_prompt_cache_advisor.py`.

- [ ] Test: `analyze_prompt` returns None for a prompt with < 1024 tokens
- [ ] Test: `analyze_prompt` returns CacheOpportunity for a prompt with >= 1024 tokens
- [ ] Test: volatile detection — prompt with `{user_name}` on line 3 splits stable prefix at line 2
- [ ] Test: volatile detection — prompt with ISO date `2026-06-10` triggers volatility
- [ ] Test: `estimated_savings_pct == stable_tokens / total_tokens * 0.9`
- [ ] Test: `analyze_spans([])` returns AdvisorReport with 0 analyzed_prompts
- [ ] Test: `analyze_spans(spans)` groups by prompt_hash — 3 spans with 2 unique hashes → analyzed_prompts == 2
- [ ] Test: `analyze_directory` with a valid JSONL file returns AdvisorReport without raising
- [ ] Test: CLI command `cache_advisor` with a real JSONL file exits 0

---

## Task 13 — feat(sdk-ts): initialize TypeScript SDK package

**Commit:** `feat(sdk-ts): initialize TypeScript SDK package`

Create `sdk/typescript/` package skeleton.

- [x] Create `sdk/typescript/package.json` with exact contents from spec (name, version, scripts, peerDeps, devDeps)
- [x] Create `sdk/typescript/tsconfig.json` with exact contents from spec (strict: true, noImplicitAny, etc.)
- [x] Create `sdk/typescript/src/types.ts` — all interfaces and type aliases: `InferenceSpan`, `ArtifactType`, `AxonConfig`, `UsageData`
- [x] Create `sdk/typescript/README.md` — brief description, install, quickstart
- [x] Create empty `sdk/typescript/tests/` directory with `.gitkeep`

---

## Task 14 — feat(sdk-ts): implement pricing table and cost calculator

**Commit:** `feat(sdk-ts): implement pricing table and cost calculator`

Create `sdk/typescript/src/pricing.ts` and `sdk/typescript/src/cost_calculator.ts`.

- [x] Implement `ModelPricing` interface in `pricing.ts`
- [x] Implement `PRICING` constant with all 7 models matching the Python pricing table values exactly
- [x] Implement `calculateCost(model, inputTokens, outputTokens, cachedTokens?)` using string-based fixed-point arithmetic (no float for money)
- [x] Return `null` for unknown model, `"0.00000000"` for zero tokens, 8 decimal places always
- [x] JSDoc on all exported functions and constants
- [ ] Passes `tsc --noEmit` with zero errors

---

## Task 15 — feat(sdk-ts): implement span emitter (console + backend)

**Commit:** `feat(sdk-ts): implement span emitter (console + backend)`

Create `sdk/typescript/src/span_emitter.ts`.

- [x] Implement `SpanEmitter` class with constructor accepting `AxonConfig`
- [x] Implement `emit(span: InferenceSpan): void` — console output via `console.log(JSON.stringify(span, null, 2))` when `exportToConsole` is true
- [x] Implement backend POST to `{backendUrl}/v1/spans` with `X-Axon-API-Key` header using `fetch()` — fire-and-forget
- [x] Wrap fetch in try/catch that calls `console.error` on failure but never throws
- [x] JSDoc on class and method
- [ ] Passes `tsc --noEmit` with zero errors

---

## Task 16 — feat(sdk-ts): implement instrumentor with patch() and instrument()

**Commit:** `feat(sdk-ts): implement instrumentor with patch() and instrument()`

Create `sdk/typescript/src/instrumentor.ts` and `sdk/typescript/src/index.ts`.

- [x] Implement `instrument(config?: AxonConfig)` — returns decorator factory that wraps async functions, records timing, emits span on success, propagates errors unchanged
- [x] Implement `patch(client: unknown, config?: AxonConfig): void` — detects OpenAI (`client.chat?.completions?.create`) vs Anthropic (`client.messages?.create`), wraps create method in place
- [x] Create `sdk/typescript/src/index.ts` — re-exports everything from all modules; exports `configure(config: AxonConfig): void` that sets module-level global config
- [x] No silent suppression of LLM errors — original error always propagates
- [ ] `// eslint-disable-next-line @typescript-eslint/no-explicit-any` comments where `any` is used with justification
- [ ] Passes `tsc --noEmit` with zero errors

---

## Task 17 — test(sdk-ts): add Jest tests for all TypeScript modules

**Commit:** `test(sdk-ts): add Jest tests for all TypeScript modules`

Create test files in `sdk/typescript/tests/`.

- [x] Create `tests/cost_calculator.test.ts`:
  - Known model (gpt-4o, 1M+1M tokens) returns exact string "12.50000000"
  - Unknown model returns null
  - Zero tokens returns "0.00000000"
  - Cached tokens billed at cache-read rate for claude-3-5-sonnet-20241022
- [x] Create `tests/span_emitter.test.ts`:
  - Console output is valid JSON (JSON.parse does not throw)
  - Backend POST fires with correct `X-Axon-API-Key` header (mock fetch)
  - Backend fetch failure does not throw from emit()
- [x] Create `tests/instrumentor.test.ts`:
  - `patch()` detects OpenAI client and wraps `chat.completions.create`
  - `patch()` detects Anthropic client and wraps `messages.create`
  - Wrapped function returns original response unchanged
  - Error from wrapped function propagates unchanged
  - Span is emitted on successful call

---

## Task 18 — ci: add TypeScript test job to CI workflow

**Commit:** `ci: add TypeScript test job to CI workflow`

Modify `.github/workflows/ci.yml`.

- [x] Add `typescript-test` job with `runs-on: ubuntu-latest`
- [x] Set `defaults.run.working-directory: sdk/typescript`
- [x] Steps: `actions/checkout@v4`, `actions/setup-node@v4` (node 20), `npm install`, `npm run typecheck`, `npm run lint`, `npm test -- --coverage`
- [x] Job does not depend on Python jobs (runs in parallel)

---

## Task 19 — docs: add router guide, cascade tracing guide, prompt cache advisor guide

**Commit:** `docs: add router guide, cascade tracing guide, prompt cache advisor guide`

Create three documentation files.

- [x] Create `docs/router-guide.md` with: what the router does (2 paragraphs), full routing table (TaskType × ComplexityTier → ModelTier), customization code example, A/B test setup and interpretation, cost savings estimation
- [x] Create `docs/cascade-tracing.md` with: problem statement, orchestrator setup code example, sub-agent setup code example, reading cascade cost in Grafana, W3C TraceContext compliance note
- [x] Create `docs/prompt-cache-advisor.md` with: how provider caching works, CLI usage, report interpretation, Anthropic cache_control code example, OpenAI cached prefix code example

---

## Task 20 — docs: update README roadmap — Phase 3 complete

**Commit:** `docs: update README roadmap — Phase 3 complete`

Modify `README.md`.

- [x] Update roadmap table: Phase 3 status from "In progress" to "✓ Complete"
- [x] Update scope description for Phase 3 to reflect all 4 delivered features
- [x] No other README changes

---

## Task 21 — chore: Phase 3 complete — all checks passing

**Commit:** `chore: Phase 3 complete — all checks passing`

Final validation commit.

- [x] Run `mypy sdk/python/axon --strict` → 0 errors
- [x] Run `ruff check sdk/python/axon sdk/python/tests` → clean
- [x] Run `pytest sdk/python/tests --cov=axon --cov-fail-under=80` → passes
- [x] Run `cd sdk/typescript && npm run typecheck` → 0 errors
- [x] Run `cd sdk/typescript && npm run lint` → clean
- [x] Run `cd sdk/typescript && npm test -- --coverage` → all pass
- [x] Verify `axon --help` lists `cache-advisor` command
- [x] Verify `git log --oneline` shows exactly 21 new commits since Phase 2
- [x] Commit this task list update as the final commit
