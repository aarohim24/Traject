# Axon Phase 3 — Requirements

## Introduction

Phase 3 extends the Axon SDK with four production capabilities: an Adaptive Model Router, a Multi-Agent Cascade Tracer, a Prompt Cache Optimization Advisor, and a TypeScript SDK. All existing Phase 1 and Phase 2 behaviour is preserved. New modules are additive only.

## Glossary

| Term | Definition |
|---|---|
| TaskType | Enumerated category of an LLM task (CODE_GENERATION, SUMMARIZATION, etc.) |
| ComplexityTier | LOW / MEDIUM / HIGH bucket derived from a 0.0–1.0 complexity score |
| ModelTier | TIER_1 (cheapest) / TIER_2 (mid) / TIER_3 (most capable) |
| RoutingDecision | Dataclass recording the selected model and routing rationale |
| ABTestConfig | Configuration for deterministic traffic splitting between models |
| TraceContext | W3C TraceContext carrier (traceparent header) linking spans across agents |
| CascadeCostSummary | Aggregated cost across all spans sharing a trace_id |
| CacheOpportunity | Analysis result identifying a cacheable prompt prefix |
| AdvisorReport | Aggregated cache analysis across a set of recorded spans |
| InferenceSpan (TS) | TypeScript mirror of the Python InferenceSpan model |

---

## Requirement 1: Adaptive Model Router — Task Classification

**User Story:** As a platform engineer, I want Axon to automatically classify the task type of each LLM call, so that the router can select the cheapest capable model without any changes to my existing code.

### Acceptance Criteria

1. WHEN `classify_task(messages)` is called with a list of message dicts, THEN it SHALL return a `TaskType` enum value within 1 ms on any input.
2. WHEN the system prompt contains any of the keywords `["code", "implement", "function", "class", "bug"]`, THEN `classify_task` SHALL return `TaskType.CODE_GENERATION`.
3. WHEN the system prompt contains any of `["review", "analyze", "critique", "improve"]` AND any message contains a triple-backtick code block, THEN `classify_task` SHALL return `TaskType.CODE_REVIEW`.
4. WHEN any user message contains a triple-backtick code block and no higher-priority signal matches, THEN `classify_task` SHALL return `TaskType.CODE_GENERATION`.
5. WHEN the message text contains `"summarize"`, `"summary"`, `"tldr"`, `"key points"`, or `"brief"`, THEN `classify_task` SHALL return `TaskType.SUMMARIZATION`.
6. WHEN the message text contains `"classify"`, `"categorize"`, `"label"`, `"which of"`, or `"one of the following"`, THEN `classify_task` SHALL return `TaskType.CLASSIFICATION`.
7. WHEN the message text contains `"extract"`, `"find all"`, `"list the"`, `"identify"`, or `"what are the"`, THEN `classify_task` SHALL return `TaskType.EXTRACTION`.
8. WHEN the message text contains `"translate"`, `"in french"`, `"in spanish"`, or `"in german"`, THEN `classify_task` SHALL return `TaskType.TRANSLATION`.
9. WHEN the message text contains `"think"`, `"reason"`, `"step by step"`, `"explain why"`, `"analyze"`, or `"compare"`, THEN `classify_task` SHALL return `TaskType.REASONING`.
10. WHEN the message text contains `"write a story"`, `"poem"`, `"creative"`, `"imagine"`, or `"fictional"`, THEN `classify_task` SHALL return `TaskType.CREATIVE_WRITING`.
11. WHEN the last user message contains `"?"` and no higher-priority signal matches, THEN `classify_task` SHALL return `TaskType.QUESTION_ANSWERING`.
12. WHEN no signal matches, THEN `classify_task` SHALL return `TaskType.UNKNOWN`.
13. WHEN `classify_task` is called with any input including empty lists, None-valued fields, or malformed dicts, THEN it SHALL never raise an exception.
14. WHEN `estimate_complexity(messages, task_type)` is called, THEN it SHALL return a float in the closed interval [0.0, 1.0] and SHALL never raise.

---

## Requirement 2: Adaptive Model Router — Routing Table and Decision

**User Story:** As a platform engineer, I want the router to map each (task type, complexity) pair to the cheapest appropriate model tier, so that low-complexity tasks are automatically downgraded to cheaper models.

### Acceptance Criteria

1. WHEN `RuleRouter` is constructed without a `routing_table`, THEN it SHALL use `DEFAULT_ROUTING_TABLE` which maps SUMMARIZATION/CLASSIFICATION/EXTRACTION/TRANSLATION at all tiers to TIER_1 or TIER_2, and CODE_GENERATION/REASONING/CREATIVE_WRITING at HIGH to TIER_3.
2. WHEN `RuleRouter` is constructed without a `model_map`, THEN it SHALL use `DEFAULT_MODEL_MAP` where openai TIER_1=gpt-4o-mini, TIER_2=gpt-4o, TIER_3=gpt-4o and anthropic TIER_1=claude-3-5-haiku-20241022, TIER_2=claude-3-5-sonnet-20241022, TIER_3=claude-3-opus-20240229.
3. WHEN `route(messages, requested_model)` is called, THEN it SHALL return a `RoutingDecision` containing `selected_model`, `task_type`, `complexity_score`, `complexity_tier`, `model_tier`, `routing_rule`, and `cost_delta_pct`.
4. WHEN `route()` selects a different model than `requested_model`, THEN it SHALL log a structlog warning with the task type, complexity tier, and reason.
5. WHEN any exception occurs inside `route()`, THEN it SHALL return a `RoutingDecision` with `selected_model == original_model` and SHALL NOT propagate the exception.
6. WHEN `override_task_type` is provided to `route()`, THEN it SHALL skip `classify_task` and use the override value directly.
7. WHEN `cost_delta_pct` is computed, THEN it SHALL use `axon.core.pricing.PROVIDER_PRICING` and SHALL return 0.0 when either model is absent from the table.
8. WHEN `configure(router=router_instance)` is called on the instrumentor, THEN `route()` SHALL be invoked before each subsequent LLM call and the routing decision SHALL be recorded in structlog output.

---

## Requirement 3: Adaptive Model Router — A/B Testing

**User Story:** As a platform engineer, I want to route a configurable percentage of traffic to a cheaper treatment model while keeping the rest on the control model, so that I can validate quality before committing to a routing policy.

### Acceptance Criteria

1. WHEN `ABTestConfig(treatment_model, treatment_pct, feature_tag, seed)` is constructed, THEN `assign_group(request_id)` SHALL return either `"treatment"` or `"control"`.
2. WHEN `assign_group` is called with the same `request_id` multiple times, THEN it SHALL return the same group each time (deterministic).
3. WHEN `assign_group` is called with `treatment_pct=0.0`, THEN it SHALL always return `"control"`.
4. WHEN `assign_group` is called with `treatment_pct=1.0`, THEN it SHALL always return `"treatment"`.
5. WHEN `ABTestConfig` has a `feature_tag` set and the LLM call's feature tag does not match, THEN the A/B assignment SHALL NOT apply and the router SHALL use the standard routing decision.
6. WHEN the treatment group is assigned, THEN `RoutingDecision.selected_model` SHALL be `treatment_model` and `ab_test_group` SHALL be `"treatment"`.

---

## Requirement 4: Multi-Agent Cascade Tracer — W3C TraceContext Propagation

**User Story:** As a platform engineer running multi-agent pipelines, I want trace context to propagate across agent boundaries using W3C TraceContext headers, so that all spans from an orchestrator and its sub-agents appear in the same trace.

### Acceptance Criteria

1. WHEN `inject_trace_context(headers, trace_id, span_id)` is called, THEN it SHALL set `headers["traceparent"]` to `"00-{trace_id}-{span_id}-01"` and return the headers dict.
2. WHEN `inject_trace_context` is called with a 32-character hex `trace_id` and 16-character hex `span_id`, THEN the resulting `traceparent` value SHALL match the regex `^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$`.
3. WHEN `extract_trace_context(headers)` is called with a valid `traceparent` header, THEN it SHALL return `(trace_id, parent_span_id)` as a tuple of strings.
4. WHEN `extract_trace_context` is called with a missing or malformed `traceparent`, THEN it SHALL return `None` and SHALL NOT raise.
5. WHEN `inject_trace_context` followed by `extract_trace_context` is called on the same headers dict, THEN the extracted `trace_id` and `span_id` SHALL be identical to the injected values.

---

## Requirement 5: Multi-Agent Cascade Tracer — CascadeTracer API

**User Story:** As a platform engineer, I want a `CascadeTracer` class that handles trace context for both orchestrators and sub-agents, so that I don't need to manage W3C header formatting manually.

### Acceptance Criteria

1. WHEN `CascadeTracer().start_orchestration(feature_tag)` is called, THEN it SHALL return a `TraceContext` with a valid `trace_id` (32 lowercase hex chars) and `span_id` (16 lowercase hex chars).
2. WHEN `TraceContext.outbound_headers()` is called, THEN it SHALL return a dict containing a valid `traceparent` header.
3. WHEN `CascadeTracer().join_trace(inbound_headers)` is called with valid W3C headers, THEN it SHALL return a `TraceContext` whose `trace_id` matches the inbound `trace_id`.
4. WHEN `join_trace` is called with headers that contain no valid `traceparent`, THEN it SHALL return `None` and SHALL NOT raise (fail open).
5. WHEN `get_cascade_cost(trace_id)` is called without a `backend_client`, THEN it SHALL return a `CascadeCostSummary` with all cost fields set to `Decimal("0")`.

---

## Requirement 6: Prompt Cache Optimization Advisor

**User Story:** As a platform engineer, I want Axon to analyze my system prompts and identify cache-eligible prefixes, so that I can restructure prompts to reduce inference cost using provider-level caching.

### Acceptance Criteria

1. WHEN `PromptCacheAdvisor().analyze_prompt(system_prompt, provider)` is called with a prompt containing fewer tokens than the provider threshold (1024), THEN it SHALL return `None`.
2. WHEN `analyze_prompt` is called with a prompt containing 1024 or more tokens, THEN it SHALL return a `CacheOpportunity` with `token_count >= 1024`, `provider` matching the input, `estimated_savings_pct` in (0.0, 1.0], and a non-empty `recommendation` string.
3. WHEN a prompt line contains a `{variable}` format placeholder, an ISO date (`YYYY-MM-DD`), or the words `today`/`now`/`current date`, THEN `analyze_prompt` SHALL classify that line and all subsequent lines as volatile and SHALL NOT include them in the stable prefix.
4. WHEN `estimated_savings_pct` is calculated, THEN it SHALL equal `stable_tokens / total_tokens * 0.9`.
5. WHEN `analyze_spans(spans)` is called, THEN it SHALL return an `AdvisorReport` with `analyzed_prompts` equal to the number of unique `prompt_hash` values in the span list.
6. WHEN `analyze_directory(jsonl_path)` is called with a valid JSONL file of InferenceSpan records, THEN it SHALL return an `AdvisorReport` without raising.
7. WHEN the `axon cache-advisor --input <file>` CLI command is run, THEN it SHALL print a rich table of cache opportunities to stdout and exit 0.

---

## Requirement 7: TypeScript SDK — Cost Calculation

**User Story:** As a Node.js developer, I want the TypeScript SDK to calculate inference cost from token counts using the same pricing table as the Python SDK, so that I get consistent cost attribution across both SDKs.

### Acceptance Criteria

1. WHEN `calculateCost(model, inputTokens, outputTokens)` is called with a known model, THEN it SHALL return a string representation of the cost with exactly 8 decimal places (e.g. `"0.00250000"`).
2. WHEN `calculateCost` is called with an unknown model, THEN it SHALL return `null`.
3. WHEN `calculateCost` is called with `inputTokens=0` and `outputTokens=0`, THEN it SHALL return `"0.00000000"` (not null).
4. WHEN `calculateCost` is called with `cachedTokens > 0` and the model has a `cacheReadCostPer1MTokens`, THEN the cached tokens SHALL be billed at the cache-read rate instead of the standard input rate.
5. WHEN cost arithmetic is performed, THEN it SHALL use string-based fixed-point arithmetic and SHALL NOT use JavaScript floating-point for monetary calculations.

---

## Requirement 8: TypeScript SDK — Instrumentation

**User Story:** As a Node.js developer, I want to instrument my OpenAI or Anthropic client with a single `patch()` call, so that every LLM call emits an InferenceSpan without modifying my existing code.

### Acceptance Criteria

1. WHEN `patch(client)` is called with an OpenAI client (has `client.chat.completions.create`), THEN it SHALL wrap that method in place and the wrapped method SHALL return the original response unchanged.
2. WHEN `patch(client)` is called with an Anthropic client (has `client.messages.create`), THEN it SHALL wrap that method in place and the wrapped method SHALL return the original response unchanged.
3. WHEN the wrapped LLM method raises an error, THEN the error SHALL propagate to the caller unchanged and an InferenceSpan SHALL NOT be emitted (or MAY be emitted with error metadata).
4. WHEN a wrapped LLM call completes successfully, THEN `SpanEmitter.emit` SHALL be called with a valid `InferenceSpan`.
5. WHEN `SpanEmitter.emit` is called and `exportToConsole` is `true`, THEN it SHALL write valid JSON to stdout.
6. WHEN `SpanEmitter.emit` is called and `backendUrl` is configured, THEN it SHALL POST the span to `{backendUrl}/v1/spans` with header `X-Axon-API-Key` set.
7. WHEN the backend POST fails for any reason, THEN `SpanEmitter.emit` SHALL NOT throw and SHALL NOT affect the calling code.

---

## Requirement 9: Backward Compatibility and Phase 1/2 Preservation

**User Story:** As a user of the existing Axon SDK, I want all Phase 1 and Phase 2 behaviour to remain unchanged after Phase 3 is installed, so that no existing integrations break.

### Acceptance Criteria

1. WHEN the Phase 3 package is installed, THEN `pytest sdk/python/tests --cov=axon --cov-fail-under=80` SHALL pass with all Phase 1 tests green.
2. WHEN `axon.configure()` is called without the `router` parameter, THEN behaviour SHALL be identical to Phase 1/2.
3. WHEN `axon.patch(client)` is called without a router configured, THEN no routing logic SHALL execute and call overhead SHALL remain at Phase 1 levels.
4. WHEN `mypy sdk/python/axon --strict` is run, THEN it SHALL report 0 errors across all modules including the three new subdirectories.
5. WHEN `ruff check sdk/python/axon sdk/python/tests` is run, THEN it SHALL report 0 violations.
