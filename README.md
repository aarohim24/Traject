# Axon

> AI inference optimization middleware for production agent systems.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![MIT License](https://img.shields.io/badge/license-MIT-green) ![PyPI](https://img.shields.io/badge/pypi-axon--sdk-orange) ![Tests](https://img.shields.io/badge/tests-336%20passing-brightgreen) ![Coverage](https://img.shields.io/badge/coverage-94%25-brightgreen)

---

## The Problem

In multi-step AI agents, each LLM call re-pays for all prior tool results and reasoning accumulated in the context window. Input tokens constitute approximately 99% of agentic inference cost. No production library addresses this.

---

## Benchmark

**Workload:** 10-step code review agent · **Strategy:** CONSERVATIVE · **10 iterations**

| Metric               | Without Axon | With Axon | Reduction |
|----------------------|-------------|-----------|-----------|
| Input tokens / run   | 11,845      | 10,183    | 14.0%     |
| Projected cost / run | $0.001777   | $0.001527 | 14.0%     |
| Tokens saved / run   | —           | 1,662     | —         |

Reproduce: `python examples/benchmark/run_benchmark.py` — no API key required.

> **Benchmark note:** This benchmark runs on a realistic but synthetic agent trajectory using tiktoken for exact token counting. Compression ratios vary by workload — we are actively collecting production validation data. Run it yourself: `python examples/benchmark/run_benchmark.py` — no API key required.

---

## What Axon Is Not

- Not a prompt coaching tool or developer behavior scorer
- Not a VS Code extension
- Not an LLM wrapper
- Not a cloud-only service — self-hosted first, no data leaves your infrastructure by default

---

## Quickstart

```bash
pip install axon-sdk
```

```python
import openai, axon

axon.configure(export_to_stdout=True)
client = openai.OpenAI()
axon.patch(client, feature_tag="my_agent", shadow_mode=True)

# Your existing agent code unchanged.
# Shadow mode logs compression savings without modifying context.
# Set shadow_mode=False to apply live after validating.
```

---

## How Trajectory Compression Works

The compression pipeline runs before each LLM call in an agent loop:

1. **Parse** context into typed segments (`SYSTEM_PROMPT`, `USER_MESSAGE`, `TOOL_RESULT`, `REASONING_BLOCK`, `RAG_CHUNK`, and more)
2. **Protect** system prompts and the last N turns — never touched
3. **Score** remaining segments by recency, semantic relevance, and reference count
4. **Compress** low-relevance segments: summarize tool results, drop completed reasoning
5. **Validate** — system prompts and recent turns must be present; circuit breaker reverts on failure
6. **Emit** an OpenTelemetry span recording tokens saved

Three strategies: `CONSERVATIVE` (20% target), `MODERATE` (35%), `AGGRESSIVE` (55%).

---

## Self-Hosted Backend

```bash
git clone https://github.com/aarohimathur/axon
cd axon
docker compose -f deploy/docker-compose.yml up -d
```

Adds: cost attribution dashboard (Grafana), semantic caching (Redis + pgvector), budget controls with webhook alerting. Dashboard at http://localhost:3000.

---

## Architecture

```
Your application
      │
      ▼
Axon SDK  ────────────────────────────────────────────────────────
│  Instrumentation wrapper  │  Semantic cache client             │
│  Trajectory compressor    │  Budget controller                 │
│  Artifact classifier      │  OTel span emitter                 │
───────────────────────────────────────────────────────────────────
      │                                │
      ▼                                ▼
LLM Provider                  Axon Backend (optional)
(OpenAI, Anthropic)           FastAPI · PostgreSQL · Redis · Grafana
```

---

## Research Basis

Trajectory compression is grounded in recent work on agentic context management (AgentDiet, FSE 2026 and related literature). Axon is the first production-ready, framework-agnostic middleware implementation of trajectory compression as a drop-in Python library.

Novel contributions: typed artifact model enabling per-type optimization, integrated compression + caching + routing in one middleware layer, and shadow mode for safe production validation.

---

## Roadmap

| Phase | Status | Scope |
|---|---|---|
| 1 — SDK | ✓ Complete | Python SDK, compression engine, OTel, CLI |
| 2 — Backend | ✓ Complete | FastAPI, PostgreSQL, Redis, Grafana |
| 3 — Router | ✓ Complete | Adaptive model router, TypeScript SDK, multi-agent cascade tracer, prompt cache advisor |
| 4 — Dashboard | Planned | Custom React dashboard, cloud hosting |
| 5 — Guarantees | Planned | Conformal prediction quality bounds, ML routing |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues labelled [`good-first-issue`](https://github.com/aarohimathur/axon/issues?q=is%3Aopen+is%3Aissue+label%3Agood-first-issue) are a good starting point.

---

## License

MIT — see [LICENSE](LICENSE).
