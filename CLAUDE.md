# Traject — Instructions for Claude Code

Traject is a self-hosted LLM cost observability and trajectory-compression
middleware: a Python SDK (`sdk/python/traject`), a TypeScript SDK
(`sdk/typescript`), and an optional FastAPI + Postgres + Redis backend
(`backend/`) with Grafana/React dashboards. Full product description: `README.md`.

## Source of truth, and a known drift

`.kiro/steering/{product,architecture,standards}.md` are the original
spec-driven design docs (Kiro format) for this project. Treat
`standards.md` and `architecture.md` (ADRs) as **binding** — they encode
real constraints, not aspirational ones. Treat `product.md`'s **phase
status as stale**: it marks the backend, dashboards, and Kubernetes deploy
as "Phase 2 complete" / "Phase 4 not started," but all of them already
exist in this repo (`backend/`, `dashboard/`, `deploy/kubernetes/`,
`docs/kubernetes-deployment.md`, `docs/enterprise-auth.md`). Don't use
`product.md`'s phase gate to argue a file shouldn't exist or shouldn't be
touched — check the actual repo state instead.

## Non-negotiable standards (from `.kiro/steering/standards.md`)

- `mypy --strict` passes with zero errors. Full type annotations
  everywhere. No `Any` without an inline comment justifying it.
- `ruff check` and `ruff format --check` pass clean. No `print()` in
  library code — `structlog.get_logger(__name__)` only. No bare `except`.
  No mutable default args. No star imports.
- `Decimal` for every monetary value, never `float`. Pydantic v2 models
  or `@dataclass` for anything crossing a module boundary — raw `dict`
  only as a local intermediate.
- Enums for categorical values (providers, artifact types, strategies).
  No magic strings.
- Custom exceptions in `traject/exceptions.py`; error messages must say
  what broke and what the caller can do about it.
- Prompt content is hashed (SHA-256) before any persistence or telemetry,
  never stored in plaintext unless the caller opts in explicitly.
  Traject never reads, stores, or logs provider API keys.
- Commits: Conventional Commits (`feat|fix|chore|docs|test|refactor|perf|ci(scope): ...`),
  atomic, no "wip"/"fix stuff", no mixing refactor with feature work.
- Tests mirror source (`traject/core/foo.py` → `tests/unit/test_foo.py`),
  edge cases explicit, no mocking the module under test (mock external
  APIs at the HTTP layer via `respx`), coverage ≥80% overall / ≥90% on
  the compression engine.

## Module dependency direction (strictly enforced, do not introduce cycles)

```
classifier  →  (nothing internal)
compression →  classifier
core        →  classifier, compression
router      →  core
tracer      →  core
advisor     →  (nothing internal beyond models)
telemetry   →  core
cli         →  core, telemetry, advisor
```

## Architecture decisions that change how you implement things

- **OTel-first** (ADR-001): all telemetry is OpenTelemetry spans. Never
  invent a proprietary telemetry format.
- **Token counts from provider responses** (ADR-002), never estimated —
  `tiktoken` is a fallback only for mid-stream estimates, and any
  estimated span must be marked `token_count_estimated: true`.
- **Local embedding model only** (ADR-003): `all-MiniLM-L6-v2` runs
  in-process for relevance scoring. No compression-path logic may make an
  external API call — that would add cost to the system being optimized.
- **Shadow mode is the trust mechanism, not a feature flag** (ADR-004):
  compression must default to `shadow_mode=True`. Never flip this default
  quietly.
- **Framework adapters are isolated** (ADR-009): each adapter
  (`traject/compression/adapters/`) is guarded with
  `try/except ImportError` → `TrajectDependencyError`. The compression
  engine depends only on the adapter base interface, never a specific
  framework.

## Lossless vs. lossy — the distinction that matters most in this codebase

`_compute_dedup()` in `sdk/python/traject/compression/engine.py` is
documented and marketed (README) as **lossless**: it only merges
byte-identical `TOOL_RESULT` segments, so nothing that ever differed is
discarded. If you extend dedup to catch near-duplicates (same command,
different timestamp/UUID/nondeterministic field), that is a **lossy**
operation by definition — normalized-away fields are gone from the
compressed output. Any such feature must:
1. Be a separate code path from `_compute_dedup()`, not a modification of it.
2. Be gated so it does not run at the `CONSERVATIVE` strategy (keep that
   tier's lossless guarantee intact).
3. Use its own stub message — never reuse the "identical tool output"
   stub for a near-duplicate match.
This came up as a real gap in community feedback; if you're asked to
work on it, don't blur this line for convenience.

## Commands

```bash
# Python SDK — from repo root
pip install -e "sdk/python[dev,openai,anthropic,langchain,ml]"
pytest sdk/python/tests/                                   # full suite
pytest sdk/python/tests/unit/ --no-cov                      # fast unit-only
pytest sdk/python/tests/ --cov=traject --cov-report=term-missing
mypy sdk/python/traject --strict --config-file sdk/python/pyproject.toml   # run from repo root; the --config-file flag is required here, or mypy silently misses every override in sdk/python/pyproject.toml
ruff check sdk/python/ && ruff format --check sdk/python/

# Backend
pytest backend/tests/

# Benchmarks (see docs/testing.md and README "Benchmark")
python examples/benchmark/swebench_eval.py --input trajectories.jsonl --strategy conservative
python examples/benchmark/quality_eval.py --input trajectories.jsonl --strategy conservative
```

All three of `pytest`, `mypy --strict`, and `ruff` must pass clean before
anything is considered done — this mirrors CI (`.github/workflows/ci.yml`)
and the pre-commit config (`.pre-commit-config.yaml`).

## Docs that must stay honest

`README.md` makes specific, falsifiable claims (43–45% token reduction,
64–70% fact preservation, "lossless dedup," "no external API calls").
If a change to the compression engine, router, or benchmarks would make
any of these numbers or claims inaccurate, update the README/`docs/`
in the same change — don't let them drift out of sync with the code
(see the Phase-status drift above for what that looks like left unchecked).
