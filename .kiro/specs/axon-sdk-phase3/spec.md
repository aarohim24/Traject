# Axon — Phase 3 Kickoff Prompt
# Adaptive Model Router · TypeScript SDK · Cascade Tracer · Prompt Cache Advisor
# ─────────────────────────────────────────────────────────────────

You are continuing work on the Axon project as the sole senior
engineer. Phases 1 and 2 are complete and validated:

Phase 1: Python SDK — 336 tests passing, 94% coverage, mypy
--strict clean, SDK overhead 0.166ms p50, compression latency
0.300ms p50.

Phase 2: Backend service — FastAPI + PostgreSQL + Redis +
Grafana, Docker Compose validated, all health endpoints passing,
3 dashboards live.

Do not modify any Phase 1 or Phase 2 code unless a Phase 3
requirement explicitly demands it. All existing tests must
continue passing throughout Phase 3.

Read this entire prompt before writing a single line of code.
State assumptions explicitly before proceeding.

─────────────────────────────────────────────────────────────────
PHASE 3 SCOPE
─────────────────────────────────────────────────────────────────

Phase 3 introduces three new capabilities:

  1. Adaptive Model Router — rule-based V1 with A/B test mode
  2. TypeScript SDK — thin instrumentation wrapper for Node.js
  3. Multi-Agent Cascade Tracer — W3C TraceContext propagation
  4. Prompt Cache Optimization Advisor — static analysis tool

Out of scope for Phase 3:
  - Custom React dashboard (Phase 4)
  - ML-based routing (Phase 5)
  - Conformal prediction guarantees (Phase 5)
  - Cloud deployment / Kubernetes (Phase 4)
  - Enterprise SSO / RBAC (Phase 4)

─────────────────────────────────────────────────────────────────
REPOSITORY ADDITIONS
─────────────────────────────────────────────────────────────────

Add the following to the existing structure.
Do not modify anything outside these paths except where
explicitly required.

axon/
├── sdk/
│   ├── python/
│   │   └── axon/
│   │       ├── router/              ← NEW
│   │       │   ├── __init__.py
│   │       │   ├── rule_router.py
│   │       │   ├── task_classifier.py
│   │       │   ├── routing_table.py
│   │       │   └── ab_test.py
│   │       ├── tracer/              ← NEW
│   │       │   ├── __init__.py
│   │       │   ├── cascade_tracer.py
│   │       │   └── context_propagator.py
│   │       └── advisor/             ← NEW
│   │           ├── __init__.py
│   │           └── prompt_cache_advisor.py
│   └── typescript/                  ← NEW
│       ├── src/
│       │   ├── index.ts
│       │   ├── instrumentor.ts
│       │   ├── span_emitter.ts
│       │   ├── cost_calculator.ts
│       │   ├── pricing.ts
│       │   └── types.ts
│       ├── tests/
│       │   ├── instrumentor.test.ts
│       │   ├── cost_calculator.test.ts
│       │   └── span_emitter.test.ts
│       ├── package.json
│       ├── tsconfig.json
│       └── README.md
└── docs/
    ├── router-guide.md              ← NEW
    ├── cascade-tracing.md           ← NEW
    └── prompt-cache-advisor.md      ← NEW

─────────────────────────────────────────────────────────────────
FEATURE 1: ADAPTIVE MODEL ROUTER
─────────────────────────────────────────────────────────────────

The router intercepts LLM calls and routes each request to the
cheapest model that can handle the task, based on detected task
type and configured quality requirements.

── axon/router/task_classifier.py ──────────────────────────────

Heuristic task type detection. No ML. No external API calls.
Must complete in < 1ms.

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

def classify_task(messages: list[dict[str, Any]]) -> TaskType:
    """
    Classify the task type from the message array using heuristics.

    Detection signals (in priority order):
    1. System prompt keywords: "code", "implement", "function",
       "class", "bug" → CODE_GENERATION
    2. System prompt keywords: "review", "analyze", "critique",
       "improve" with code blocks in context → CODE_REVIEW
    3. User message contains code blocks (```...```) → CODE_GENERATION
    4. Keywords: "summarize", "summary", "tldr", "key points",
       "brief" → SUMMARIZATION
    5. Keywords: "classify", "categorize", "label", "which of",
       "one of the following" → CLASSIFICATION
    6. Keywords: "extract", "find all", "list the", "identify",
       "what are the" → EXTRACTION
    7. Keywords: "translate", "in french", "in spanish",
       "in german" → TRANSLATION
    8. Keywords: "think", "reason", "step by step", "explain why",
       "analyze", "compare" → REASONING
    9. Keywords: "write a story", "poem", "creative", "imagine",
       "fictional" → CREATIVE_WRITING
    10. Has a "?" in last user message → QUESTION_ANSWERING
    11. → UNKNOWN

    Returns TaskType. Never raises.
    """

def estimate_complexity(
    messages: list[dict[str, Any]],
    task_type: TaskType,
) -> float:
    """
    Estimate task complexity as a float 0.0–1.0.

    Signals:
    - Total context token count (more tokens = higher complexity)
    - Number of tool calls in context
    - Presence of multi-step reasoning requirements
    - Code block count and size

    Returns: 0.0 (trivial) to 1.0 (highly complex).
    """

── axon/router/routing_table.py ────────────────────────────────

The routing table maps (task_type, complexity_tier) → model.
Stored as a YAML-serializable dict so users can customize it.

ModelTier enum:
    TIER_1 = "tier_1"  # cheapest: gpt-4o-mini, claude-haiku
    TIER_2 = "tier_2"  # mid: gpt-4o, claude-sonnet
    TIER_3 = "tier_3"  # most capable: gpt-4o (latest), claude-opus

ComplexityTier enum (derived from float score):
    LOW    = "low"     # 0.0 – 0.39
    MEDIUM = "medium"  # 0.40 – 0.69
    HIGH   = "high"    # 0.70 – 1.0

DEFAULT_ROUTING_TABLE:
    Each TaskType maps to a dict of ComplexityTier → ModelTier:

    SUMMARIZATION, CLASSIFICATION, EXTRACTION, TRANSLATION:
        LOW    → TIER_1
        MEDIUM → TIER_1
        HIGH   → TIER_2

    QUESTION_ANSWERING, CODE_REVIEW:
        LOW    → TIER_1
        MEDIUM → TIER_2
        HIGH   → TIER_2

    CODE_GENERATION, REASONING, CREATIVE_WRITING:
        LOW    → TIER_1
        MEDIUM → TIER_2
        HIGH   → TIER_3

    UNKNOWN:
        ALL    → TIER_2  (safe default)

DEFAULT_MODEL_MAP (per provider):
    openai:
        TIER_1: "gpt-4o-mini"
        TIER_2: "gpt-4o"
        TIER_3: "gpt-4o"

    anthropic:
        TIER_1: "claude-3-5-haiku-20241022"
        TIER_2: "claude-3-5-sonnet-20241022"
        TIER_3: "claude-3-opus-20240229"

@dataclass
class RoutingDecision:
    original_model: str
    selected_model: str
    task_type: TaskType
    complexity_score: float
    complexity_tier: ComplexityTier
    model_tier: ModelTier
    routing_rule: str      # e.g. "summarization.low → tier_1"
    cost_delta_pct: float  # estimated % cost change vs original
    ab_test_group: str | None  # "control" | "treatment" | None

── axon/router/rule_router.py ──────────────────────────────────

class RuleRouter:
    """
    Routes LLM calls to the appropriate model tier based on
    task classification and complexity estimation.

    The router is transparent: every routing decision is logged
    as an OTEL span attribute and can be overridden per-call.
    """

    def __init__(
        self,
        provider: str,
        routing_table: dict | None = None,  # uses DEFAULT if None
        model_map: dict | None = None,       # uses DEFAULT if None
        ab_test: ABTestConfig | None = None,
    ) -> None: ...

    def route(
        self,
        messages: list[dict[str, Any]],
        requested_model: str,
        override_task_type: TaskType | None = None,
    ) -> RoutingDecision:
        """
        Classify the task, estimate complexity, look up routing table.
        Return a RoutingDecision with the selected model.

        If override_task_type is set, skip classification and use it.
        If the routing decision would change the model, log a warning
        with structlog including the reason.
        Never raises — return a decision with original_model on error.
        """

    def apply(
        self,
        decision: RoutingDecision,
        client: Any,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """
        Execute the LLM call with the routed model.
        Replaces the 'model' parameter transparently.
        Records cost_delta_pct in the OTEL span.
        """

Integration with instrumentor:
    Update axon/core/instrumentor.py configure() to accept:
        router: RuleRouter | None = None
    If router is set, route() is called before each LLM call.
    The routing decision is attached to the InferenceSpan.

── axon/router/ab_test.py ──────────────────────────────────────

@dataclass
class ABTestConfig:
    """
    Routes a percentage of traffic to a cheaper model (treatment)
    while keeping the rest on the original model (control).
    Used to validate quality before committing to a routing policy.
    """
    treatment_model: str
    treatment_pct: float       # 0.0–1.0, e.g. 0.10 for 10%
    feature_tag: str | None    # limit A/B test to one feature
    seed: int = 42             # for reproducible splitting

    def assign_group(self, request_id: str) -> str:
        """Return 'treatment' or 'control' deterministically."""

─────────────────────────────────────────────────────────────────
FEATURE 2: MULTI-AGENT CASCADE TRACER
─────────────────────────────────────────────────────────────────

Propagates W3C TraceContext headers across agent boundaries so
the full cascade cost of an orchestrator + sub-agents is visible
in a single trace.

── axon/tracer/context_propagator.py ───────────────────────────

W3C TraceContext (traceparent / tracestate) header injection
and extraction. Follows the W3C Trace Context spec exactly.

TRACEPARENT_HEADER = "traceparent"
TRACESTATE_HEADER  = "tracestate"

def inject_trace_context(
    headers: dict[str, str],
    trace_id: str,
    span_id: str,
) -> dict[str, str]:
    """
    Inject W3C traceparent header into a headers dict.
    Format: 00-{trace_id}-{span_id}-01
    Returns the headers dict with traceparent added.
    """

def extract_trace_context(
    headers: dict[str, str],
) -> tuple[str, str] | None:
    """
    Extract trace_id and parent_span_id from W3C traceparent.
    Returns (trace_id, parent_span_id) or None if not present
    or malformed.
    """

── axon/tracer/cascade_tracer.py ───────────────────────────────

class CascadeTracer:
    """
    Enables multi-agent cost attribution by propagating trace
    context across agent boundaries.

    Usage in orchestrator:
        tracer = CascadeTracer()
        ctx = tracer.start_orchestration(feature_tag="pipeline")

        # Pass ctx to sub-agents via headers or direct injection
        sub_agent_headers = ctx.outbound_headers()

    Usage in sub-agent:
        tracer = CascadeTracer()
        tracer.join_trace(inbound_headers)
        axon.patch(client, cascade_tracer=tracer)
    """

    def start_orchestration(
        self,
        feature_tag: str,
        metadata: dict[str, str] | None = None,
    ) -> "TraceContext": ...

    def join_trace(
        self,
        inbound_headers: dict[str, str],
    ) -> "TraceContext | None":
        """
        Join an existing trace from inbound headers.
        Returns None if no valid traceparent found (fail open).
        """

    def get_cascade_cost(
        self,
        trace_id: str,
        backend_client: Any | None = None,
    ) -> CascadeCostSummary:
        """
        Query the backend for total cost across all spans
        sharing this trace_id. Returns a summary with:
        - orchestrator_cost_usd
        - sub_agent_costs: dict[str, Decimal]
        - total_cost_usd
        - span_count
        """

@dataclass
class CascadeCostSummary:
    trace_id: str
    orchestrator_cost_usd: Decimal
    sub_agent_costs: dict[str, Decimal]
    total_cost_usd: Decimal
    span_count: int
    feature_tag: str

─────────────────────────────────────────────────────────────────
FEATURE 3: PROMPT CACHE OPTIMIZATION ADVISOR
─────────────────────────────────────────────────────────────────

Analyzes system prompts and conversation patterns to identify
cache-eligible prefixes and suggest restructuring.

── axon/advisor/prompt_cache_advisor.py ────────────────────────

Provider cache thresholds (tokens required for cache eligibility):
    Anthropic: 1024 input tokens minimum for cache_control
    OpenAI:    1024 tokens minimum for cached prefix

@dataclass
class CacheOpportunity:
    segment: str               # the cacheable prefix text
    token_count: int
    provider: str
    estimated_savings_pct: float  # % of input tokens saveable
    recommendation: str           # human-readable action

@dataclass
class AdvisorReport:
    analyzed_prompts: int
    cache_eligible_count: int
    opportunities: list[CacheOpportunity]
    total_estimated_savings_pct: float
    restructuring_suggestions: list[str]

class PromptCacheAdvisor:
    """
    Analyzes system prompts and message patterns from recorded
    InferenceSpan data (or a provided list of prompts) to
    identify cache optimization opportunities.
    """

    def analyze_prompt(
        self,
        system_prompt: str,
        provider: str,
    ) -> CacheOpportunity | None:
        """
        Analyze a single system prompt for cache eligibility.

        Algorithm:
        1. Count tokens using tiktoken
        2. If token_count >= provider threshold → eligible
        3. Identify stable prefix vs volatile suffix:
           - Stable: text that doesn't contain {variables},
             today's date, user names, or session-specific data
           - Volatile: lines containing format strings,
             timestamps, or user-specific content
        4. Calculate estimated_savings_pct:
           stable_tokens / total_tokens * 0.9
           (Anthropic charges 10% of normal rate for cache hits)
        5. Generate restructuring suggestion:
           "Move stable prefix (N tokens) before volatile
            suffix. Apply cache_control to prefix block."

        Returns None if not eligible.
        """

    def analyze_spans(
        self,
        spans: list[Any],  # list[InferenceSpan]
    ) -> AdvisorReport:
        """
        Analyze a list of recorded InferenceSpan objects.
        Groups by prompt_hash, identifies frequently reused
        prompts, checks each for cache eligibility.
        """

    def analyze_directory(
        self,
        jsonl_path: str,
    ) -> AdvisorReport:
        """
        Read a JSONL file of InferenceSpan records (from
        axon analyze output) and run analysis.
        CLI-callable.
        """

CLI addition to axon/cli/main.py:

    axon cache-advisor --input <spans.jsonl> [--provider anthropic|openai]

    Reads spans from JSONL, runs PromptCacheAdvisor.analyze_directory(),
    prints a rich table of opportunities and recommendations.

─────────────────────────────────────────────────────────────────
FEATURE 4: TYPESCRIPT SDK
─────────────────────────────────────────────────────────────────

A thin instrumentation wrapper for Node.js applications.
Core optimization logic (compression, routing) stays in the
Python backend. TypeScript handles: span emission, cost
calculation, and backend client.

── sdk/typescript/src/types.ts ─────────────────────────────────

All shared types. Mirrors the Python SDK models exactly.

export interface InferenceSpan {
  id: string;                    // UUID v4
  traceId: string;
  parentSpanId?: string;
  spanName: string;
  timestamp: string;             // ISO 8601
  durationMs: number;
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number;
  tokenCountMethod: 'exact' | 'estimated';
  costUsd?: string;              // Decimal as string
  featureTag: string;
  promptHash: string;            // SHA-256
  artifactType: ArtifactType;
  compressionApplied: boolean;
  shadowMode: boolean;
  cacheHit: boolean;
  environment: string;
}

export type ArtifactType =
  | 'system_prompt' | 'user_message' | 'assistant_message'
  | 'tool_result'   | 'tool_call'    | 'rag_chunk'
  | 'few_shot_example' | 'reasoning_block' | 'unknown';

export interface AxonConfig {
  featureTag?: string;
  environment?: string;
  backendUrl?: string;
  backendApiKey?: string;
  exportToConsole?: boolean;
}

export interface UsageData {
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number;
  tokenCountMethod: 'exact' | 'estimated';
}

── sdk/typescript/src/pricing.ts ───────────────────────────────

Static pricing table. Same models as Python SDK.
All values as strings (avoid floating point).

export interface ModelPricing {
  provider: string;
  inputCostPer1MTokens: string;   // USD, string Decimal
  outputCostPer1MTokens: string;
  cacheReadCostPer1MTokens?: string;
}

export const PRICING: Record<string, ModelPricing> = {
  'gpt-4o':                     { provider: 'openai',    inputCostPer1MTokens: '2.50',  outputCostPer1MTokens: '10.00' },
  'gpt-4o-mini':                { provider: 'openai',    inputCostPer1MTokens: '0.15',  outputCostPer1MTokens: '0.60'  },
  'gpt-4-turbo':                { provider: 'openai',    inputCostPer1MTokens: '10.00', outputCostPer1MTokens: '30.00' },
  'gpt-3.5-turbo':              { provider: 'openai',    inputCostPer1MTokens: '0.50',  outputCostPer1MTokens: '1.50'  },
  'claude-3-5-sonnet-20241022': { provider: 'anthropic', inputCostPer1MTokens: '3.00',  outputCostPer1MTokens: '15.00', cacheReadCostPer1MTokens: '0.30' },
  'claude-3-5-haiku-20241022':  { provider: 'anthropic', inputCostPer1MTokens: '0.80',  outputCostPer1MTokens: '4.00',  cacheReadCostPer1MTokens: '0.08' },
  'claude-3-opus-20240229':     { provider: 'anthropic', inputCostPer1MTokens: '15.00', outputCostPer1MTokens: '75.00', cacheReadCostPer1MTokens: '1.50' },
};

export function calculateCost(
  model: string,
  inputTokens: number,
  outputTokens: number,
  cachedTokens = 0,
): string | null

── sdk/typescript/src/span_emitter.ts ──────────────────────────

Emits InferenceSpan to console (default) and/or HTTP backend.

export class SpanEmitter {
  constructor(config: AxonConfig) {}

  emit(span: InferenceSpan): void {
    // Console export: JSON.stringify with 2-space indent
    // Backend export: POST to {backendUrl}/v1/spans
    //   with X-Axon-API-Key header
    //   fire-and-forget, never throws
  }
}

── sdk/typescript/src/instrumentor.ts ──────────────────────────

export function instrument(config?: AxonConfig) {
  // Returns a decorator factory for async functions
  // Wraps the function, records start time, calls it,
  // extracts usage from response, emits span.
  // Never suppresses the original function's errors.
}

export function patch(client: any, config?: AxonConfig): void {
  // Monkey-patches OpenAI or Anthropic Node.js client.
  // Detects client type by checking for:
  //   client.chat?.completions?.create → OpenAI
  //   client.messages?.create → Anthropic
  // Wraps the create method in place.
}

── sdk/typescript/src/index.ts ─────────────────────────────────

Re-export everything from the above modules.
Export configure() function that sets global AxonConfig.

── sdk/typescript/package.json ─────────────────────────────────

{
  "name": "axon-sdk",
  "version": "0.3.0",
  "description": "AI inference optimization middleware — TypeScript SDK",
  "main": "dist/index.js",
  "types": "dist/index.d.ts",
  "scripts": {
    "build":    "tsc",
    "test":     "jest",
    "lint":     "eslint src tests",
    "typecheck": "tsc --noEmit"
  },
  "peerDependencies": {
    "openai": ">=4.0.0",
    "@anthropic-ai/sdk": ">=0.20.0"
  },
  "devDependencies": {
    "typescript": "^5.4.0",
    "@types/node": "^20.0.0",
    "jest": "^29.0.0",
    "ts-jest": "^29.0.0",
    "@typescript-eslint/eslint-plugin": "^7.0.0",
    "@typescript-eslint/parser": "^7.0.0",
    "eslint": "^8.0.0"
  }
}

── sdk/typescript/tsconfig.json ────────────────────────────────

{
  "compilerOptions": {
    "target": "ES2020",
    "module": "CommonJS",
    "lib": ["ES2020"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist", "tests"]
}

─────────────────────────────────────────────────────────────────
CODE STANDARDS (APPLY TO ALL NEW CODE)
─────────────────────────────────────────────────────────────────

Python:
  - Full type annotations, mypy --strict passes
  - No print(), use structlog
  - Decimal for all monetary values
  - Pydantic v2 or @dataclass for cross-boundary structures
  - No bare except, specific exception types only
  - All new modules follow dependency direction:
    router → core (for span emission)
    tracer → core
    advisor → (no internal deps beyond models)
  - 80% coverage minimum on new modules

TypeScript:
  - strict: true in tsconfig
  - No any without comment justification
  - All monetary values as string (no float arithmetic)
  - All public functions documented with JSDoc
  - Tests via Jest with ts-jest

─────────────────────────────────────────────────────────────────
TESTING REQUIREMENTS
─────────────────────────────────────────────────────────────────

Python new modules:
  tests/unit/test_task_classifier.py
    - Every TaskType correctly identified from representative prompts
    - Complexity score in range [0.0, 1.0] always
    - Never raises on malformed input

  tests/unit/test_rule_router.py
    - Every (TaskType, ComplexityTier) combination routes correctly
    - A/B test determinism: same request_id always same group
    - Router falls back to original_model on any error
    - Routing decision includes correct cost_delta_pct

  tests/unit/test_cascade_tracer.py
    - W3C traceparent format correct (regex validate)
    - inject → extract round-trips cleanly
    - Malformed traceparent returns None, never raises
    - start_orchestration produces valid trace_id

  tests/unit/test_prompt_cache_advisor.py
    - Prompt below threshold returns None
    - Prompt above threshold returns CacheOpportunity
    - Volatile segment detection: {variable}, timestamps
    - Stable vs volatile split is correct
    - analyze_spans groups by prompt_hash correctly

TypeScript:
  tests/cost_calculator.test.ts
    - Known model returns correct cost (string comparison)
    - Unknown model returns null
    - Zero tokens returns "0"
    - Cached tokens reduce cost correctly

  tests/instrumentor.test.ts
    - patch() detects OpenAI and Anthropic clients correctly
    - Wrapped function still returns original response
    - Errors in wrapped function propagate unchanged
    - Span is emitted on success

  tests/span_emitter.test.ts
    - Console output is valid JSON
    - Backend POST fires with correct headers
    - Backend failure does not throw

Phase 1 regression:
  After all Phase 3 code is written, run:
  pytest sdk/python/tests --cov=axon --cov-fail-under=80
  This must pass before Phase 3 is considered complete.

─────────────────────────────────────────────────────────────────
CI ADDITIONS
─────────────────────────────────────────────────────────────────

Add to .github/workflows/ci.yml:

typescript-test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/setup-node@v4
      with: { node-version: '20' }
    - cd sdk/typescript
    - npm install
    - npm run typecheck
    - npm run lint
    - npm test -- --coverage

─────────────────────────────────────────────────────────────────
DOCUMENTATION
─────────────────────────────────────────────────────────────────

docs/router-guide.md:
  - What the router does (2 paragraphs)
  - Default routing table (full table: TaskType × ComplexityTier → ModelTier)
  - How to customize the routing table (code example)
  - A/B test mode setup and interpretation
  - Cost savings estimation

docs/cascade-tracing.md:
  - What cascade tracing solves (the invisible sub-agent cost problem)
  - Orchestrator setup (code example)
  - Sub-agent setup (code example)
  - Reading cascade cost in Grafana
  - W3C TraceContext compliance note

docs/prompt-cache-advisor.md:
  - How provider-level prompt caching works (Anthropic + OpenAI)
  - Running the advisor CLI
  - Interpreting the report
  - Applying cache_control to Anthropic prompts (code example)
  - Structuring prompts for OpenAI cached prefix (code example)

─────────────────────────────────────────────────────────────────
COMMIT SEQUENCE
─────────────────────────────────────────────────────────────────

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

─────────────────────────────────────────────────────────────────
VALIDATION CHECKLIST
─────────────────────────────────────────────────────────────────

Run these after all 21 commits. All must pass.

[ ] mypy sdk/python/axon --strict → 0 errors
[ ] ruff check sdk/python/axon sdk/python/tests → clean
[ ] pytest sdk/python/tests --cov=axon --cov-fail-under=80
    → passes (Phase 1 regression clean)
[ ] cd sdk/typescript && npm run typecheck → 0 errors
[ ] cd sdk/typescript && npm run lint → clean
[ ] cd sdk/typescript && npm test -- --coverage → all pass
[ ] axon --help → shows cache-advisor command
[ ] Router correctly classifies "summarize this document"
    as SUMMARIZATION → TIER_1 on default table
[ ] Router correctly classifies a prompt with code blocks
    and "implement" keyword as CODE_GENERATION
[ ] W3C traceparent round-trip: inject → extract → same IDs
[ ] PromptCacheAdvisor returns None for 500-token prompt
[ ] PromptCacheAdvisor returns CacheOpportunity for 1500-token prompt
[ ] git log --oneline → exactly 21 new commits since Phase 2