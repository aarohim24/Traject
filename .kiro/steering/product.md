# Axon — Product Context & Boundaries

## What Axon is

Axon is a Python SDK and self-hosted backend platform that makes
AI inference observable, controllable, and economically efficient
at the infrastructure layer. It instruments LLM calls in real
time, compresses agentic context trajectories before they hit the
provider, emits structured OpenTelemetry spans for cost
attribution, and provides a backend service for team-level
dashboards, semantic caching, and budget enforcement.

The primary artifact is a pip-installable Python package.
The entry point is a single decorator. The backend is optional
for individual use and required for team features.

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

## Repository structure

axon/
├── sdk/python/          ← Phase 1 complete. Do not modify
│                           unless a current phase requirement
│                           explicitly demands it.
├── backend/             ← Phase 2 active. FastAPI service.
├── dashboards/          ← Phase 2 active. Grafana templates.
├── deploy/              ← Phase 2 active. Docker Compose.
├── docs/                ← Maintained across all phases.
└── examples/            ← Updated per phase as needed.

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

Phase 1 code is frozen. No changes without explicit justification.

### Phase 2 — MVP · ACTIVE

Introducing the backend service and making Axon a complete
self-hosted platform. All work in this phase adds new files
or extends new modules. Existing SDK tests must continue
passing throughout.

In scope:
- FastAPI backend service (axon-backend)
- PostgreSQL 16 + pgvector (schema, Alembic migrations)
- Redis 7 (semantic cache hot layer, budget counters)
- Semantic caching (SDK client + backend service)
- Feature-level cost attribution (aggregation pipeline)
- Budget controls with webhook alerting
- Docker Compose self-hosted deployment
- Grafana dashboard templates (3 provisioned dashboards)
- SDK backend client (BackendClient, SemanticCacheClient)
- Live compression mode documentation and example
- Backend CI job added to existing workflow

### Phase 3 — Beta · NOT STARTED

Do not scaffold, reference, or build any of the following
until Phase 2 is fully validated:
- TypeScript SDK
- Adaptive model router
- Multi-agent cascade tracer
- Prompt cache optimization advisor
- Batch eligibility tagger
- Quality regression detector

### Phase 4 — Production · NOT STARTED

Do not scaffold, reference, or build any of the following
until Phase 3 is fully validated:
- Custom React dashboard (replaces Grafana)
- Cloud / Kubernetes deployment
- Enterprise SSO, RBAC, audit logs
- SOC2 groundwork
- Managed SaaS offering

### Phase 5 — Differentiation & Scale · NOT STARTED

- ML-based routing with conformal prediction guarantees
- Predictive cost modeling
- Plugin system
- AWS Bedrock, Google Vertex AI, Azure AI integrations

## Permanent exclusions

These will never be built regardless of phase:
- Gamification (XP, leaderboards, achievement badges)
- Community skills marketplace
- Natural language dashboard query interface
- VS Code extension (may be reconsidered in Phase 4 only
  as a cost-overlay sidebar, never as the primary interface)