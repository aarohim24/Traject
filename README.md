# Traject
AI inference optimization middleware for production agent systems.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![License: MIT](https://img.shields.io/badge/license-MIT-green) [![PyPI](https://img.shields.io/pypi/v/traject-sdk?label=traject-sdk)](https://pypi.org/project/traject-sdk) ![Tests](https://github.com/aarohim24/Traject/actions/workflows/ci.yml/badge.svg) ![Coverage](https://img.shields.io/badge/coverage-91%25-brightgreen)

In multi-step agents, each LLM call re-transmits the full accumulated context — tool results, reasoning traces, prior messages — compounding cost at every step. Traject intercepts calls to existing OpenAI and Anthropic clients, compresses redundant context before it reaches the provider, routes requests to the cheapest qualifying model, and emits structured OpenTelemetry spans for cost attribution. Three lines of code. Existing call sites unchanged.

```python
traject.configure(export_to_stdout=True)
traject.patch(client, feature_tag="my_agent", shadow_mode=True)
```

---

## Contents

- [Installation](#installation)
- [Quickstart](#quickstart)
- [How it works](#how-it-works)
- [Configuration](#configuration)
- [Compression strategies](#compression-strategies)
- [Model routing](#model-routing)
- [Self-hosted backend](#self-hosted-backend)
- [Benchmark](#benchmark)
- [Supported providers](#supported-providers)
- [Requirements](#requirements)
- [Architecture](#architecture)
- [Contributing](#contributing)

---

## Installation

```bash
pip install traject-sdk
```

Optional framework integrations:

```bash
pip install "traject-sdk[langchain]"   # LangChain support
pip install "traject-sdk[autogen]"     # AutoGen support
```

Requires Python 3.11+.

---

## Quickstart

```python
# OpenAI — instrument an existing client
import openai
import traject

traject.configure(export_to_stdout=True)
client = openai.OpenAI()
traject.patch(client, feature_tag="my_agent", shadow_mode=True)

# Your existing agent code — unchanged
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Summarize this report."}]
)
```

```python
# Anthropic — same pattern
import anthropic
import traject

traject.configure(export_to_stdout=True)
client = anthropic.Anthropic()
traject.patch(client, feature_tag="support_bot", shadow_mode=True)
```

```python
# LangChain — live compression at 35% reduction target
import traject
from traject import CompressionStrategy

traject.configure(export_to_stdout=True)
traject.patch(
    llm,
    feature_tag="research_agent",
    shadow_mode=False,                     # live compression
    strategy=CompressionStrategy.MODERATE, # 35% reduction target
)
```

`shadow_mode=True` (the default) runs compression silently and logs what would be saved. Set `shadow_mode=False` after validating.

---

## How it works

### The trajectory accumulation problem

In a multi-step agent loop, each call to the LLM includes all prior context — the system prompt, every user message, every tool call and its result, every reasoning trace. At step 10, the agent re-transmits 9 prior turns in full. Input tokens constitute the majority of agentic inference cost, and this overhead scales with the number of steps.

### Trajectory compression

The compression pipeline runs before each provider call:

1. **Parse** — the context window is segmented into typed artifacts: `SYSTEM_PROMPT`, `USER_MESSAGE`, `TOOL_RESULT`, `REASONING_BLOCK`, `RAG_CHUNK`, `TOOL_CALL`, `FEW_SHOT_EXAMPLE`, `ASSISTANT_MESSAGE`.
2. **Protect** — system prompts and the last N turns are marked immutable. They are never modified regardless of strategy.
3. **Score** — remaining segments are scored by recency (0.4 weight), semantic relevance to the current task (0.4 weight, local embedding model), and reference count in recent turns (0.2 weight).
4. **Compress** — low-scoring segments are summarized or dropped per strategy thresholds. Tool results older than 3 turns with score < 0.3 are summarized to one sentence. Completed reasoning blocks with score < 0.4 are dropped.
5. **Validate** — circuit breaker: if system prompts or recent turns are absent from the compressed output, compression is aborted and the original context is returned unchanged.
6. **Emit** — an OpenTelemetry span records tokens saved, cost delta, compression ratio, and strategy applied.

### Shadow mode

Shadow mode computes the full compression pipeline and logs what would have been saved, without modifying the context passed to the provider. It is the default. Enable live compression (`shadow_mode=False`) after validating savings on your workload.

---

## Configuration

```python
traject.configure(
    export_to_stdout=True,         # print OTEL spans to stdout
    otlp_endpoint="http://...",    # send spans to OTEL collector
    backend_url="http://...",      # send to Traject backend
    backend_api_key="...",         # API key for backend
    report_benchmarks=False,       # opt-in: submit to public registry
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `export_to_stdout` | `bool` | `True` | Print OTEL spans to stdout |
| `otlp_endpoint` | `str \| None` | `None` | OTEL collector endpoint |
| `backend_url` | `str \| None` | `None` | Traject backend URL |
| `backend_api_key` | `str \| None` | `None` | Backend API key |
| `router` | `RuleRouter \| None` | `None` | Adaptive model router |
| `report_benchmarks` | `bool` | `False` | Opt-in aggregate telemetry |

---

## Compression strategies

| Strategy | Target reduction | Use case |
|---|---|---|
| `CONSERVATIVE` | 20% | Default. New deployments, unknown workloads. |
| `MODERATE` | 35% | Validated workloads after shadow mode review. |
| `AGGRESSIVE` | 55% | High-volume, well-characterized workloads. |

```python
from traject import CompressionStrategy

traject.patch(client, strategy=CompressionStrategy.MODERATE)
```

---

## Model routing

```python
from traject.router import RuleRouter

router = RuleRouter(provider="openai")
traject.configure(router=router)
```

Tasks are classified by type and routed to the cheapest model tier that can handle them.

| Task type | Low complexity | Medium | High |
|---|---|---|---|
| Summarization, Classification, Extraction | gpt-4o-mini | gpt-4o-mini | gpt-4o |
| Q&A, Code review | gpt-4o-mini | gpt-4o | gpt-4o |
| Code generation, Reasoning | gpt-4o-mini | gpt-4o | gpt-4o |

Custom routing tables and A/B test mode are supported. See [docs/router-guide.md](docs/router-guide.md).

---

## Self-hosted backend

```bash
git clone https://github.com/aarohim24/Traject
cd Traject
cp deploy/.env.example deploy/.env
docker compose -f deploy/docker-compose.yml up -d
```

Services started: PostgreSQL 16, Redis 7, Traject backend (port 8000), Grafana dashboards (port 3000), React dashboard (port 5173).

```python
traject.configure(
    backend_url="http://localhost:8000",
    backend_api_key="your-key",
)
```

Adds: cost attribution by feature tag, semantic caching, budget alerts, team dashboards. The backend is optional — the SDK operates independently without it.

---

## Benchmark

Workload: 10-step code review agent. Strategy: CONSERVATIVE. Token counting: tiktoken (exact). Cost projected at gpt-4o-mini pricing.

| Metric | Without Traject | With Traject | Reduction |
|---|---|---|---|
| Input tokens / run | 11,845 | 10,183 | 14.0% |
| Projected cost / run | $0.001777 | $0.001527 | 14.0% |
| Tokens saved / run | — | 1,662 | — |

This benchmark uses a realistic but synthetic agent trajectory. Compression ratios vary by workload — longer agents with denser tool call histories see higher reduction. Reproduce with `python examples/benchmark/run_benchmark.py` — no API key required.

---

## Supported providers

| Provider | Instrumentation | Routing | Batch routing |
|---|---|---|---|
| OpenAI | ✓ | ✓ | ✓ |
| Anthropic | ✓ | ✓ | ✓ |
| AWS Bedrock | ✓ | — | — |
| Google Vertex AI | ✓ | — | — |
| LangChain (any provider) | ✓ | ✓ | — |
| AutoGen (any provider) | ✓ | ✓ | — |

---

## Requirements

- Python 3.11+
- No external API calls for optimization — the embedding model (`all-MiniLM-L6-v2`) runs in-process
- Docker and Docker Compose (self-hosted backend only, optional)

---

## Architecture

```
Your application
      │
      ▼
Traject SDK
      ├── Instrumentation wrapper
      ├── Artifact type classifier
      ├── Trajectory compression engine
      ├── Semantic cache client
      ├── Model router
      └── OTel span emitter
      │
      ├──────────────────────► LLM Provider
      │                        (OpenAI, Anthropic, Bedrock, Vertex)
      │
      └──────────────────────► Traject Backend (optional)
                               FastAPI · PostgreSQL · Redis
                               │
                               └── Grafana / React Dashboard
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and the PR process.

Issues labeled [`good-first-issue`](https://github.com/aarohim24/Traject/issues?q=is%3Aopen+is%3Aissue+label%3Agood-first-issue) are the recommended starting point.

---

## License

MIT — see [LICENSE](LICENSE).
