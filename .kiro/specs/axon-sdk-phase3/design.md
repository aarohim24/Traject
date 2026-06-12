# Axon Phase 3 — Technical Design

## Overview

Phase 3 adds four new capabilities on top of the frozen Phase 1 SDK and Phase 2 backend: an Adaptive Model Router, a Multi-Agent Cascade Tracer, a Prompt Cache Optimization Advisor, and a TypeScript SDK. All new Python code lives in three new subdirectories (`router/`, `tracer/`, `advisor/`) plus minimal surgical additions to `cli/main.py` and `core/instrumentor.py`. No Phase 1 or Phase 2 source is modified beyond those two files.

---

## 1. System Architecture

```
Your application
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│  Axon Python SDK                                                │
│                                                                 │
│  core/instrumentor.py  ←─── router/rule_router.py              │
│         │                          │                           │
│         │               router/task_classifier.py              │
│         │               router/routing_table.py                │
│         │               router/ab_test.py                      │
│         │                                                       │
│  tracer/cascade_tracer.py ──→ tracer/context_propagator.py     │
│  advisor/prompt_cache_advisor.py  (no internal deps)           │
│  cli/main.py  (cache-advisor command)                          │
└─────────────────────────────────────────────────────────────────┘
      │                              │
      ▼                              ▼
LLM Provider                 Axon Backend (optional)
(OpenAI, Anthropic)          FastAPI · PostgreSQL · Redis

sdk/typescript/              (separate package, Node.js)
  types · pricing · cost_calculator · span_emitter · instrumentor
```

### Module Dependency Chain (Python, strict one-way)

```
advisor   →  (no internal axon imports beyond axon.models)
classifier → (no internal deps)
compression → classifier
core      →  classifier, compression
router    →  core  (for structlog, AxonError)
tracer    →  core  (for structlog, AxonError)
telemetry →  core
cli       →  core, telemetry, advisor
```

---

## 2. Feature 1: Adaptive Model Router

### 2.1 `router/task_classifier.py`

**Purpose:** Heuristic-only task type detection in < 1 ms. No ML, no network calls.

```python
class TaskType(str, Enum):
    CODE_GENERATION    = "code_generation"
    CODE_REVIEW        = "code_review"
    SUMMARIZATION      = "summarization"
    CLASSIFICATION     = "classification"
    EXTRACTION         = "extraction"
    QUESTION_ANSWERING = "question_answering"
    REASONING          = "reasoning"
    TRANSLATION        = "translation"
    CREATIVE_WRITING   = "creative_writing"
    UNKNOWN            = "unknown"

def classify_task(messages: list[dict[str, Any]]) -> TaskType: ...
def estimate_complexity(messages: list[dict[str, Any]], task_type: TaskType) -> float: ...
```

**`classify_task` algorithm** (priority order, case-insensitive matching):

1. Extract system message content (role == "system")
2. Extract all user message content (role == "user")
3. Concatenate all content to `full_text`
4. Signal checks (first match wins):
   - System prompt contains any of `["code", "implement", "function", "class", "bug"]` → `CODE_GENERATION`
   - System prompt contains any of `["review", "analyze", "critique", "improve"]` AND any message contains triple-backtick block → `CODE_REVIEW`
   - Any user message contains triple-backtick block → `CODE_GENERATION`
   - `full_text` contains any of `["summarize", "summary", "tldr", "key points", "brief"]` → `SUMMARIZATION`
   - `full_text` contains any of `["classify", "categorize", "label", "which of", "one of the following"]` → `CLASSIFICATION`
   - `full_text` contains any of `["extract", "find all", "list the", "identify", "what are the"]` → `EXTRACTION`
   - `full_text` contains any of `["translate", "in french", "in spanish", "in german"]` → `TRANSLATION`
   - `full_text` contains any of `["think", "reason", "step by step", "explain why", "analyze", "compare"]` → `REASONING`
   - `full_text` contains any of `["write a story", "poem", "creative", "imagine", "fictional"]` → `CREATIVE_WRITING`
   - Last user message contains `"?"` → `QUESTION_ANSWERING`
   - → `UNKNOWN`
5. Never raises — wrap entire body in `try/except Exception` returning `UNKNOWN`

**`estimate_complexity` algorithm:**

```
score = 0.0

token_score:
  total_chars = sum(len(msg.get("content","")) for msg in messages if isinstance)
  token_estimate = total_chars / 4   # rough tiktoken approximation
  token_score = min(1.0, token_estimate / 8000)  # 8k tokens = max complexity
  score += token_score * 0.5  # 50% weight

tool_call_score:
  tool_calls = count messages where role == "tool" or content has "tool_call"
  tool_score = min(1.0, tool_calls / 10)
  score += tool_score * 0.2  # 20% weight

reasoning_score:
  if task_type in (REASONING, CODE_GENERATION, CODE_REVIEW): score += 0.2

code_block_score:
  code_blocks = count triple-backtick occurrences in all content
  score += min(0.1, code_blocks * 0.02)

return min(1.0, max(0.0, score))
```

### 2.2 `router/routing_table.py`

```python
class ModelTier(str, Enum):
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"

class ComplexityTier(str, Enum):
    LOW    = "low"     # 0.0 – 0.39
    MEDIUM = "medium"  # 0.40 – 0.69
    HIGH   = "high"    # 0.70 – 1.0

@dataclass
class RoutingDecision:
    original_model: str
    selected_model: str
    task_type: TaskType
    complexity_score: float
    complexity_tier: ComplexityTier
    model_tier: ModelTier
    routing_rule: str           # "summarization.low → tier_1"
    cost_delta_pct: float       # negative = cheaper, positive = more expensive
    ab_test_group: str | None   # "control" | "treatment" | None

def complexity_score_to_tier(score: float) -> ComplexityTier: ...
    # 0.0–0.39 → LOW, 0.40–0.69 → MEDIUM, 0.70–1.0 → HIGH

DEFAULT_ROUTING_TABLE: dict[TaskType, dict[ComplexityTier, ModelTier]]
DEFAULT_MODEL_MAP: dict[str, dict[ModelTier, str]]
```

**Default routing table:**

| TaskType | LOW | MEDIUM | HIGH |
|---|---|---|---|
| SUMMARIZATION | TIER_1 | TIER_1 | TIER_2 |
| CLASSIFICATION | TIER_1 | TIER_1 | TIER_2 |
| EXTRACTION | TIER_1 | TIER_1 | TIER_2 |
| TRANSLATION | TIER_1 | TIER_1 | TIER_2 |
| QUESTION_ANSWERING | TIER_1 | TIER_2 | TIER_2 |
| CODE_REVIEW | TIER_1 | TIER_2 | TIER_2 |
| CODE_GENERATION | TIER_1 | TIER_2 | TIER_3 |
| REASONING | TIER_1 | TIER_2 | TIER_3 |
| CREATIVE_WRITING | TIER_1 | TIER_2 | TIER_3 |
| UNKNOWN | TIER_2 | TIER_2 | TIER_2 |

**Default model map:**

| Provider | TIER_1 | TIER_2 | TIER_3 |
|---|---|---|---|
| openai | gpt-4o-mini | gpt-4o | gpt-4o |
| anthropic | claude-3-5-haiku-20241022 | claude-3-5-sonnet-20241022 | claude-3-opus-20240229 |

**`cost_delta_pct` calculation:**
Uses `axon.core.pricing.PROVIDER_PRICING` to look up `input_cost_per_1m_tokens` for both models. `cost_delta_pct = (selected_cost - original_cost) / original_cost * 100`. Returns 0.0 if either model is unknown.

### 2.3 `router/ab_test.py`

```python
@dataclass
class ABTestConfig:
    treatment_model: str
    treatment_pct: float       # 0.0–1.0
    feature_tag: str | None
    seed: int = 42

    def assign_group(self, request_id: str) -> str:
        # Hash: hashlib.sha256(f"{self.seed}:{request_id}".encode()).digest()
        # Take first 4 bytes as uint32, divide by 2^32
        # If result < treatment_pct → "treatment", else → "control"
        ...
```

Deterministic: same `request_id` always returns same group. No randomness at call time.

### 2.4 `router/rule_router.py`

```python
class RuleRouter:
    def __init__(
        self,
        provider: str,
        routing_table: dict[TaskType, dict[ComplexityTier, ModelTier]] | None = None,
        model_map: dict[str, dict[ModelTier, str]] | None = None,
        ab_test: ABTestConfig | None = None,
    ) -> None: ...

    def route(
        self,
        messages: list[dict[str, Any]],
        requested_model: str,
        override_task_type: TaskType | None = None,
    ) -> RoutingDecision: ...

    def apply(
        self,
        decision: RoutingDecision,
        client: Any,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any: ...
```

**`route` algorithm:**
1. Wrap entire body in `try/except Exception` — return fallback `RoutingDecision` with `original_model` on any error
2. `task_type = override_task_type or classify_task(messages)`
3. `complexity_score = estimate_complexity(messages, task_type)`
4. `complexity_tier = complexity_score_to_tier(complexity_score)`
5. `model_tier = self._routing_table[task_type][complexity_tier]`
6. `selected_model = self._model_map[self.provider][model_tier]`
7. If `ab_test` configured and (`ab_test.feature_tag is None` or matches): apply A/B assignment using `uuid4()` as `request_id`
8. Log with structlog if `selected_model != requested_model`
9. Return `RoutingDecision`

### 2.5 `core/instrumentor.py` update

Add `router: RuleRouter | None = None` parameter to `configure()`. Store as module-level `_router`. In `_run_pipeline` (and both sync/async wrappers), if `_router` is set, call `_router.route(messages, model)` before the LLM call and attach `routing_decision` to the span log.

---

## 3. Feature 2: Multi-Agent Cascade Tracer

### 3.1 `tracer/context_propagator.py`

**W3C TraceContext spec (https://www.w3.org/TR/trace-context/):**

```
traceparent = "00-" + trace_id + "-" + parent_id + "-" + trace_flags
trace_id    = 32 lowercase hex digits (128-bit)
parent_id   = 16 lowercase hex digits (64-bit)
trace_flags = "01" (sampled)
```

```python
TRACEPARENT_HEADER = "traceparent"
TRACESTATE_HEADER  = "tracestate"

_TRACEPARENT_RE = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$"
)

def inject_trace_context(
    headers: dict[str, str],
    trace_id: str,
    span_id: str,
) -> dict[str, str]:
    # Validates: trace_id is 32 hex chars, span_id is 16 hex chars
    # Sets headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
    # Returns headers (mutated in place, also returned for chaining)
    ...

def extract_trace_context(
    headers: dict[str, str],
) -> tuple[str, str] | None:
    # Looks up headers.get("traceparent") case-insensitively
    # Matches against _TRACEPARENT_RE
    # Returns (trace_id, parent_span_id) or None
    # Never raises
    ...
```

### 3.2 `tracer/cascade_tracer.py`

```python
@dataclass
class TraceContext:
    trace_id: str       # 32 lowercase hex chars
    span_id: str        # 16 lowercase hex chars
    feature_tag: str
    metadata: dict[str, str]

    def outbound_headers(self) -> dict[str, str]:
        # Returns {"traceparent": "00-{trace_id}-{span_id}-01"}
        ...

@dataclass
class CascadeCostSummary:
    trace_id: str
    orchestrator_cost_usd: Decimal
    sub_agent_costs: dict[str, Decimal]
    total_cost_usd: Decimal
    span_count: int
    feature_tag: str

class CascadeTracer:
    def start_orchestration(
        self,
        feature_tag: str,
        metadata: dict[str, str] | None = None,
    ) -> TraceContext:
        # Generate trace_id = uuid4().hex (32 hex chars)
        # Generate span_id  = uuid4().hex[:16] (16 hex chars)
        # Store internally for join_trace lookups
        ...

    def join_trace(
        self,
        inbound_headers: dict[str, str],
    ) -> TraceContext | None:
        # Calls extract_trace_context(inbound_headers)
        # If None → return None (fail open)
        # Generate new span_id for this agent's root span
        # Return TraceContext with extracted trace_id and new span_id
        ...

    def get_cascade_cost(
        self,
        trace_id: str,
        backend_client: Any | None = None,
    ) -> CascadeCostSummary:
        # If backend_client is None → return empty summary
        # Calls backend_client.get_spans_by_trace_id(trace_id)
        # Aggregates cost by feature_tag
        # Returns CascadeCostSummary
        ...
```

**trace_id generation:** `uuid.uuid4().hex` produces 32 lowercase hex chars directly. span_id: `uuid.uuid4().hex[:16]`.

---

## 4. Feature 3: Prompt Cache Optimization Advisor

### 4.1 `advisor/prompt_cache_advisor.py`

```python
CACHE_THRESHOLDS: dict[str, int] = {
    "anthropic": 1024,
    "openai":    1024,
}

_VOLATILE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\{[^}]+\}"),           # {variable} format strings
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO dates
    re.compile(r"\btoday\b|\bnow\b|\bcurrent date\b", re.IGNORECASE),
    re.compile(r"\buser(?:name)?\b|\bsession\b", re.IGNORECASE),
]

@dataclass
class CacheOpportunity:
    segment: str
    token_count: int
    provider: str
    estimated_savings_pct: float
    recommendation: str

@dataclass
class AdvisorReport:
    analyzed_prompts: int
    cache_eligible_count: int
    opportunities: list[CacheOpportunity]
    total_estimated_savings_pct: float
    restructuring_suggestions: list[str]

class PromptCacheAdvisor:
    def analyze_prompt(self, system_prompt: str, provider: str) -> CacheOpportunity | None: ...
    def analyze_spans(self, spans: list[Any]) -> AdvisorReport: ...
    def analyze_directory(self, jsonl_path: str) -> AdvisorReport: ...
```

**`analyze_prompt` algorithm:**
1. `encoding = tiktoken.get_encoding("cl100k_base")`
2. `total_tokens = len(encoding.encode(system_prompt))`
3. If `total_tokens < CACHE_THRESHOLDS.get(provider, 1024)` → return `None`
4. Split prompt into lines
5. For each line, check if any `_VOLATILE_PATTERNS` match → mark as volatile
6. `stable_lines = lines up to first volatile line`; `stable_text = "\n".join(stable_lines)`
7. `stable_tokens = len(encoding.encode(stable_text))`
8. `estimated_savings_pct = stable_tokens / total_tokens * 0.9`
9. `recommendation = f"Move stable prefix ({stable_tokens} tokens) before volatile suffix. Apply cache_control to prefix block."`
10. Return `CacheOpportunity(segment=stable_text, token_count=stable_tokens, provider=provider, estimated_savings_pct=estimated_savings_pct, recommendation=recommendation)`

**`analyze_spans` algorithm:**
- Group spans by `prompt_hash`
- For each unique hash, retrieve the `span_name` and call `analyze_prompt` using a reconstructed placeholder (spans don't store raw prompt — use the hash count as a proxy; report is advisory only)
- Return `AdvisorReport`

**`analyze_directory` algorithm:**
- Read JSONL line by line
- Parse each line as `InferenceSpan` via `model_validate_json`
- Call `analyze_spans` on the collected spans

### 4.2 CLI: `cache-advisor` command

```python
@app.command(name="cache-advisor")
def cache_advisor(
    input: Annotated[Path, typer.Option("--input", "-i", ...)],
    provider: Annotated[str, typer.Option("--provider", "-p", ...)] = "anthropic",
) -> None: ...
```

Outputs a `rich.Table` with columns: Provider, Token Count, Estimated Savings %, Recommendation.

---

## 5. Feature 4: TypeScript SDK

### 5.1 Module structure

```
sdk/typescript/src/
  types.ts          — interfaces, enums (no logic)
  pricing.ts        — PRICING constant + calculateCost()
  cost_calculator.ts — re-exports calculateCost (thin wrapper for testability)
  span_emitter.ts   — SpanEmitter class
  instrumentor.ts   — instrument() decorator factory + patch()
  index.ts          — re-exports + configure()
```

### 5.2 Key design decisions

**String Decimal arithmetic (no float):**
```typescript
// Use BigInt arithmetic scaled to 8 decimal places
function mulDecimalStr(a: string, b: string): string { ... }
// Or: parse to integer cents (units of 1e-8 USD), compute, format back
```

**`calculateCost` signature:**
```typescript
export function calculateCost(
  model: string,
  inputTokens: number,
  outputTokens: number,
  cachedTokens = 0,
): string | null
// Returns null for unknown model
// Returns "0" for all-zero tokens
// String result has exactly 8 decimal places: "0.00123456"
```

**`SpanEmitter.emit`:** Fire-and-forget `fetch()` to backend. Wrapped in `try/catch` that logs to console.error but never throws. Console export uses `console.log(JSON.stringify(span, null, 2))`.

**`patch` client detection:**
```typescript
if ('chat' in client && client.chat?.completions?.create) → OpenAI
if ('messages' in client && client.messages?.create) → Anthropic
```

**`instrument` decorator:**
```typescript
export function instrument(config?: AxonConfig) {
  return function<T extends (...args: unknown[]) => Promise<unknown>>(
    target: T,
  ): T { ... }
}
```

### 5.3 `tsconfig.json` key settings

- `strict: true`, `noImplicitAny: true`, `strictNullChecks: true`
- `target: ES2020`, `module: CommonJS`
- `skipLibCheck: true` (peer deps not installed in test env)

### 5.4 Jest configuration

Add to `package.json`:
```json
"jest": {
  "preset": "ts-jest",
  "testEnvironment": "node",
  "testMatch": ["**/tests/**/*.test.ts"]
}
```

---

## 6. `core/instrumentor.py` changes (surgical)

Only `configure()` is modified. Add one parameter and one module-level variable:

```python
# Module-level
_router: RuleRouter | None = None  # set by configure()

def configure(
    ...,
    router: "RuleRouter | None" = None,  # NEW — TYPE_CHECKING guard
) -> None:
    ...
    global _router
    if router is not None:
        _router = router
```

The router is invoked in the wrappers before the LLM call. Import is guarded with `TYPE_CHECKING` to avoid circular imports at module load time.

---

## 7. CI Addition

`.github/workflows/ci.yml` gets a new `typescript-test` job:

```yaml
typescript-test:
  runs-on: ubuntu-latest
  defaults:
    run:
      working-directory: sdk/typescript
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with:
        node-version: '20'
    - run: npm install
    - run: npm run typecheck
    - run: npm run lint
    - run: npm test -- --coverage
```

---

## 8. Documentation Files

| File | Key sections |
|---|---|
| `docs/router-guide.md` | What it does · routing table · customization · A/B mode · cost savings |
| `docs/cascade-tracing.md` | Problem · orchestrator setup · sub-agent setup · Grafana · W3C compliance |
| `docs/prompt-cache-advisor.md` | How caching works · CLI · report interpretation · Anthropic cache_control · OpenAI prefix |

---

## 9. 21-Commit Implementation Sequence

```
01  feat(router): add task type classifier with heuristic detection
02  feat(router): add routing table with default model tier mapping
03  feat(router): add A/B test config with deterministic group assignment
04  feat(router): implement RuleRouter with transparent model routing
05  feat(router): integrate router with instrumentor configure()
06  test(router): add unit tests for classifier, routing table, router
07  feat(tracer): add W3C TraceContext propagator
08  feat(tracer): implement CascadeTracer with orchestrator/sub-agent API
09  test(tracer): add unit tests for context propagation and cascade cost
10  feat(advisor): implement PromptCacheAdvisor with stable/volatile split
11  feat(advisor): add cache-advisor CLI command
12  test(advisor): add unit tests for advisor analysis
13  feat(sdk-ts): initialize TypeScript SDK package
14  feat(sdk-ts): implement pricing table and cost calculator
15  feat(sdk-ts): implement span emitter (console + backend)
16  feat(sdk-ts): implement instrumentor with patch() and instrument()
17  test(sdk-ts): add Jest tests for all TypeScript modules
18  ci: add TypeScript test job to CI workflow
19  docs: add router guide, cascade tracing guide, prompt cache advisor guide
20  docs: update README roadmap — Phase 3 complete
21  chore: Phase 3 complete — all checks passing
```

---

## 10. Correctness Properties

| ID | Property | Verification |
|---|---|---|
| P-R1 | `classify_task` never raises on any input | PBT: hypothesis arbitrary list[dict] |
| P-R2 | `estimate_complexity` always returns float in [0.0, 1.0] | PBT: hypothesis |
| P-R3 | `route()` never raises — falls back to original_model | PBT: hypothesis |
| P-R4 | A/B `assign_group` is deterministic for same request_id | PBT: same input → same output |
| P-T1 | inject→extract round-trip preserves trace_id and span_id | Unit test |
| P-T2 | Malformed traceparent returns None, never raises | PBT: hypothesis arbitrary strings |
| P-A1 | `analyze_prompt` returns None for tokens < threshold | Unit test with known prompts |
| P-A2 | `analyze_prompt` returns CacheOpportunity for tokens ≥ threshold | Unit test |
| P-TS1 | `calculateCost` returns null for unknown model | Unit test |
| P-TS2 | `calculateCost` returns "0" for zero tokens | Unit test |
