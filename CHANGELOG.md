# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — 2026-06-07

### Added

- FastAPI backend service (`axon-backend`) with span ingestion endpoint and feature-level cost attribution pipeline
- Semantic caching layer backed by Redis (hot layer) and pgvector (similarity search) — reduces redundant LLM calls for near-duplicate prompts
- Budget controls with configurable thresholds and webhook alerting when spend limits are approached or exceeded
- Docker Compose configuration for fully self-hosted deployment (PostgreSQL 16, Redis 7, backend service, Grafana)
- Grafana dashboard templates — three provisioned dashboards: cost overview, compression efficiency, and budget burn rate
- SDK `BackendClient` and `SemanticCacheClient` for connecting the Python SDK to the backend service
- Alembic migration baseline for PostgreSQL schema (spans, cache entries, budget rules)
- Backend CI job added to the existing GitHub Actions workflow

---

## [0.1.0] — 2026-06-02

### Added

- Python SDK (`axon-sdk`) installable via pip with optional extras for OpenAI, Anthropic, and LangChain
- OpenAI and Anthropic instrumentation via a single `@axon.instrument` decorator
- Trajectory compression engine with three strategies: `CONSERVATIVE`, `MODERATE`, and `AGGRESSIVE`; runs in shadow mode by default
- Artifact type classifier supporting 9 types with zero false negatives on `SYSTEM_PROMPT`
- OpenTelemetry span emission with stdout (default) and OTLP/gRPC exporters
- CLI commands: `axon analyze`, `axon version`, `axon doctor`
- 336 tests passing, 94% overall coverage, 100% coverage on the compression engine
- `mypy --strict` clean across all 25 source files
- SDK instrumentation overhead: 0.166 ms p50 (threshold 5 ms)
- Compression latency: 0.300 ms p50 on 20 segments (threshold 50 ms)

---

[0.2.0]: https://github.com/aarohimathur/axon/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aarohimathur/axon/releases/tag/v0.1.0
