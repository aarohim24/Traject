# Axon — Product Context & Boundaries

## What Axon is

Axon is a Python SDK and self-hosted backend platform that makes
AI inference observable, controllable, and economically efficient
at the infrastructure layer. It instruments LLM calls in real
time, compresses agentic context trajectories before they hit the
provider, routes requests to the cheapest qualifying model, emits
structured OpenTelemetry spans for cost attribution, and provides
a backend service for team-level dashboards, semantic caching,
and budget enforcement.

The primary artifact is a pip-installable Python package.
A TypeScript SDK provides equivalent instrumentation for Node.js.
The backend is optional for individual use and required for team
features.

## What Axon is not

- Not a prompt coaching tool. We do not score developer behavior.
- Not a VS Code extension. We do not read IDE session logs.
- Not a chatbot or conversational assistant.
- Not an LLM wrapper that adds a model on top of a model.
- Not a gamified productivity app.

## Primary users

Staff and senior engineers integrating LangChain, AutoGen,
LlamaIndex, or raw OpenAI/Anthropic clients into production
systems. Engineering leads responsible for AI infrastructure
spend. Platform teams operating multi-agent workloads at scale.
Node.js/TypeScript engineers building AI-native applications.

## Repository structure

axon/
├── sdk/python/          ← Phase 1 complete. Core SDK.
│                           Modify only for router integration
│                           in instrumentor.py and new
│                           subdirectories: router/, tracer/,
│                           advisor/
├── sdk/typescript/      ← Phase 3 active. New TypeScript SDK.
├── backend/             ← Phase 2 complete. Do not modify.
├── dashboards/          ← Phase 2 complete. Do not modify.
├── deploy/              ← Phase 2 complete. Do not modify.
├── docs/                ← Updated each phase.
└── examples/            ← Updated each phase.

## Phase status

### Phase 1 — Validation ✓ COMPLETE

All acceptance criteria met and verified:
- Python SDK published and installable (axon-sdk 0.1.0)
- OpenAI + Anthropic instrumentation
- Artifact type classifier (9 types, zero false negatives
  on SYSTEM_PROMPT)
- Trajectory compression engine (shadow mode, 3 strategies,
  engine.py at 100% coverage)
- OpenTelemetry span emission
- CLI: axon analyze / axon version / axon doctor
- 336 tests passing, 94% overall coverage
- mypy --strict: 0 errors across 25 source files
- SDK overhead: 0.166ms p50 (threshold: 5ms)
- Compression latency: 0.300ms p50 on 20 segments (threshold: 50ms)
- Benchmark: 14% input token reduction on 10-step agent workload

Phase 1 code is frozen. No changes without explicit justification.

### Phase 2 — MVP ✓ COMPLETE

All acceptance criteria met and verified:
- FastAPI backend service (axon-backend 0.2.0)
- PostgreSQL 16 + pgvector schema with Alembic migrations
- Redis 7 semantic cache (hot layer) and budget counters
- Feature-level cost attribution (hourly aggregation pipeline)
- Budget controls with webhook alerting
- Docker Compose self-hosted deployment (one-command startup)
- Grafana dashboard templates (3 provisioned dashboards)
- SDK backend client (BackendClient, SemanticCacheClient)
- Backend tests: 50 passing, 79.78% coverage
- All health endpoints passing: /health, /health/db, /health/redis
- All API endpoints validated: spans, attribution, budgets, cache

Phase 2 code is frozen. No changes without explicit justification.

### Phase 3 — Beta · ACTIVE

Introducing intelligent routing, TypeScript support, multi-agent
visibility, and prompt cache analysis. All work in this phase
adds new files or extends permitted modules only.

In scope:
- Adaptive model router (rule-based V1)
  axon/router/: rule_router.py, task_classifier.py,
  routing_table.py, ab_test.py
- Router integration: update axon/core/instrumentor.py
  configure() to accept router parameter (only permitted
  change to Phase 1 files)
- TypeScript SDK: sdk/typescript/
  Instrumentation + span emission + cost calculation only.
  No compression logic in TypeScript.
- Multi-agent cascade tracer: axon/tracer/
  W3C TraceContext propagation, CascadeTracer class
- Prompt cache optimization advisor: axon/advisor/
  Static analysis, CLI command axon cache-advisor
- Documentation: docs/router-guide.md,
  docs/cascade-tracing.md, docs/prompt-cache-advisor.md
- CI: TypeScript test job added to ci.yml

### Phase 4 — Production · NOT STARTED

Do not scaffold, reference, or build any of the following
until Phase 3 is fully validated:

- Custom React dashboard (replaces Grafana)
- Cloud / Kubernetes deployment
- Enterprise SSO, RBAC, audit logs
- SOC2 groundwork
- Managed SaaS offering

### Phase 5 — Differentiation & Scale · NOT STARTED

Do not scaffold, reference, or build any of the following
until Phase 4 is fully validated:
- ML-based routing with conformal prediction guarantees
- Predictive cost modeling
- Plugin system for custom compression strategies
- AWS Bedrock, Google Vertex AI, Azure AI integrations

## Permanent exclusions

These will never be built regardless of phase:
- Gamification (XP, leaderboards, achievement badges)
- Community skills marketplace
- Natural language dashboard query interface
- VS Code extension (may be reconsidered in Phase 4 only
  as a cost-overlay sidebar, never as the primary interface)

## Dependency direction (strictly enforced)

Python SDK (no exceptions):
  classifier  →  (nothing internal)
  compression →  classifier
  core        →  classifier, compression
  router      →  core
  tracer      →  core
  advisor     →  (nothing internal beyond models)
  telemetry   →  core
  cli         →  core, telemetry, advisor

TypeScript SDK:
  pricing     →  (nothing)
  types       →  (nothing)
  cost_calculator → pricing, types
  span_emitter    → types
  instrumentor    → cost_calculator, span_emitter, types

## Non-negotiable standards

Every file in this repository:
- Python: full type annotations, mypy --strict passes,
  structlog not print(), Decimal for currency, Pydantic v2
  for cross-boundary data, specific exceptions only
- TypeScript: strict: true, no any without comment,
  string for monetary values, JSDoc on public functions
- Commits: conventional format, atomic, tests pass at
  every commit
- Coverage: 80% minimum Python overall, 80% TypeScript