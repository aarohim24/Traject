# Changelog

All notable changes to Traject are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Prose filler removal for ASSISTANT segments — strips hedging, pleasantries, and filler phrases before token counting
- Lossless JSON array columnarization for TOOL_RESULT segments — converts arrays ≥5 items to compact table form
- Command-aware tool-result classifier — sub-classifies by command type (GIT_DIFF, GIT_LOG, PYTEST, FILE_TREE, BUILD) with domain-specific mini-compressors
- CCR (Content-Compress-Retrieve) reversible compression — stores dropped segments in Redis; `traject_retrieve` MCP tool recovers them on demand
- Soft-protect gate split — distinguishes semantically-referenced segments from content-protected ones, enabling command-aware summarization of aged tool results
- `scripts/setup.sh` first-run bootstrap — generates `deploy/.env` with strong random secrets
- Dashboard Build CI job — typecheck, vitest, and Vite production build on every push
- Branch protection on `main` with required CI checks
- Benchmarked on 49 OpenHands-SFT trajectories: **43–45% aggregate token reduction**

### Changed
- `tokens_saved` and `compression_ratio` now measured against raw input — preprocessing savings are reflected, not hidden in the baseline
- `CompressionResult` gains `segments_ccr_stubbed` counter and `Segment` gains `semantically_referenced` flag
- Dashboard: react-router-dom v7, Tailwind v4 (CSS-first), TypeScript v6, Vite v8, plugin-react v6, zustand v5, ESLint v10, jest v30

---

## [0.2.0] — 2026-06-07

### Added
- FastAPI backend service with span ingestion and feature-level cost attribution pipeline
- Semantic caching layer backed by Redis and pgvector (similarity search)
- Budget controls with configurable thresholds and webhook alerting
- Docker Compose configuration for fully self-hosted deployment (PostgreSQL 16, Redis 7, backend, Grafana)
- Grafana dashboard templates: cost overview, compression efficiency, budget burn rate
- SDK `BackendClient` and `SemanticCacheClient`
- Alembic migration baseline for PostgreSQL schema
- Backend CI job in GitHub Actions

---

## [0.1.0] — 2026-06-02

### Added
- Python SDK (`traject-sdk`) with optional extras for OpenAI, Anthropic, and LangChain
- OpenAI and Anthropic instrumentation via `@traject.instrument` and `traject.patch()`
- Trajectory compression engine with CONSERVATIVE, MODERATE, and AGGRESSIVE strategies; shadow mode by default
- Artifact type classifier (9 types, zero false negatives on SYSTEM_PROMPT)
- OpenTelemetry span emission (stdout and OTLP/gRPC exporters)
- CLI: `traject analyze`, `traject version`, `traject doctor`
- Lossless dedup pass for repeated identical tool results
- SDK instrumentation overhead: 0.166 ms p50 — Compression latency: 0.300 ms p50

---

[Unreleased]: https://github.com/aarohim24/Traject/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/aarohim24/Traject/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aarohim24/Traject/releases/tag/v0.1.0
