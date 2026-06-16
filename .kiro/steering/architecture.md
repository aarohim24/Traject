# Traject — Architecture Decisions (Locked)

These decisions are locked for Phase 1. Do not revisit, redesign,
or work around them. If a situation arises that appears to conflict
with a decision below, stop and raise it explicitly rather than
silently deviating.

## ADR-001: OTel-first telemetry

All telemetry is emitted as OpenTelemetry spans using the
`opentelemetry-sdk` and `opentelemetry-api` packages.
No proprietary telemetry format is invented.
Exporters supported in Phase 1: stdout (default), OTLP/gRPC.

Rationale: every observability stack (DataDog, Grafana,
Honeycomb, Jaeger) is OTEL-compatible. Proprietary formats
create vendor lock-in and require custom integrations.

## ADR-002: Token counts from provider response headers

Token counts are read from provider API response objects
(`usage.prompt_tokens`, `usage.completion_tokens`,
`usage.cache_read_input_tokens`, etc.).
They are never estimated using a tokenizer.

Exception: streaming responses do not expose token counts
mid-stream. For streaming, use the `usage` block in the
final chunk if available (OpenAI) or the `message_stop`
event (Anthropic). If unavailable, mark the span with
`token_count_estimated: true` and use `tiktoken` for
the estimate. Never silently drop the data.

## ADR-003: Local embedding model only

Trajectory compression relevance scoring uses
`sentence-transformers/all-MiniLM-L6-v2` running in-process.
No external API calls are made for any optimization logic.

Rationale: making an API call to decide whether to compress
adds cost to the system being optimized. This is self-defeating.
The local model is 22MB, produces 384-dimension embeddings,
and runs in ~5ms on CPU.

## ADR-004: Shadow mode default for compression

Trajectory compression is never applied to live context
until the user explicitly sets `shadow_mode=False`.
In shadow mode, the compression pipeline runs fully —
segments are scored, compression decisions are logged —
but the original uncompressed context is returned to the caller.

This is a trust-building mechanism, not a feature flag.
Enabling live compression without shadow validation
is a documented user decision, not a default.

## ADR-005: Prompt content never stored

The SDK hashes prompt content with SHA-256 (normalized:
stripped whitespace, lowercased) before any telemetry
emission or local persistence. Raw prompt text is never
written to disk, logs, or spans.

Raw content storage is an explicit opt-in: `store_prompts=True`
on the instrumentor. Even with opt-in, content is encrypted
at rest in Phase 2+ (out of scope for Phase 1 CLI/local mode).

## ADR-006: Decimal for all monetary values

All cost values are `decimal.Decimal` with precision=10, scale=8.
IEEE 754 float arithmetic is never used for currency.
Provider pricing tables store values as strings in source
and are parsed to Decimal at load time.

## ADR-007: Pydantic v2 for all cross-boundary data

Any data structure that crosses a module boundary is a
Pydantic v2 model or a `@dataclass`. Raw dicts are
acceptable only as intermediate local variables within
a single function body.

## ADR-008: No backend in Phase 1

Phase 1 is SDK + CLI only. The CLI uses SQLite (via
`aiosqlite`) for local session persistence when the user
runs `traject analyze`. There is no FastAPI service,
no PostgreSQL, no Redis, no Docker Compose requirement
in Phase 1. Any code that imports or references backend
infrastructure is out of scope for Phase 1.

## ADR-009: Framework adapters are isolated

Each framework adapter (LangChain, AutoGen, raw OpenAI)
is a separate module in `traject/compression/adapters/`.
The compression engine depends only on the `base.py`
adapter interface, never on a specific framework directly.
Framework imports inside adapters are guarded with
`try/except ImportError` and raise a descriptive
`TrajectDependencyError` if the framework is not installed.

## ADR-010: Provider pricing table is versioned and auditable

Provider pricing lives in `traject/core/pricing.py` as a
Python dict of Decimal values. It is not fetched from
a network endpoint. A GitHub Actions workflow runs weekly
to open a PR if prices have changed (Phase 2).
Every pricing change is a commit with a clear message:
`chore(pricing): update gpt-4o input cost to $X.XX/1M tokens`