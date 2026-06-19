# Traject
AI inference optimization middleware for production agent systems.

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

> **Note:** PyPI publication is in progress. Until then, install from source:
> ```bash
> git clone https://github.com/aarohim24/Traject
> cd Traject/sdk/python
> pip install -e ".[dev]"
> ```

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
3. **Soft-protect** — each remaining segment is embedded (in-process, `all-MiniLM-L6-v2`) and compared against the next 5 segments via cosine similarity. Segments with max similarity ≥ 0.6 to any later message are marked soft-protected: they require a score < 0.15 to be compressed rather than the normal threshold. This catches paraphrase references — the agent restating a tool result in different words — which substring matching misses.
4. **Score** — remaining segments are scored by recency (0.4 weight), semantic relevance to the current task (0.4 weight), and reference count in recent turns (0.2 weight). The semantic component is cached within a call by content hash and task-similarity bucket, avoiding redundant embedding lookups for repeated segments.
5. **Compress** — low-scoring segments are summarized or dropped per strategy thresholds. Tool results older than 3 turns with score < 0.3 are summarized to one sentence. Completed reasoning blocks with score < 0.4 are dropped. Soft-protected segments use a tighter threshold (< 0.15) across all strategies.
6. **Validate** — circuit breaker: if system prompts or recent turns are absent from the compressed output, compression is aborted and the original context is returned unchanged.
7. **Emit** — an OpenTelemetry span records tokens saved, compression ratio, strategy applied, cache hit rate, and count of soft-protected segments.

### Shadow mode

Shadow mode computes the full compression pipeline and logs what would have been saved, without modifying the context passed to the provider. It is the default. Enable live compression (`shadow_mode=False`) after validating savings on your workload.

### OTel span attributes

Each `traject.compression.complete` span carries:

| Attribute | Type | Description |
|---|---|---|
| `tokens_saved` | int | Tokens eliminated by compression |
| `compression_ratio` | float | Fraction of tokens eliminated, 0–1 |
| `strategy` | str | `conservative`, `moderate`, or `aggressive` |
| `shadow_mode` | bool | Whether original messages were returned |
| `cache_hits` | int | Semantic scores served from call-scoped cache |
| `cache_hit_rate` | float | Cache hit fraction, 0–1 |
| `segments_soft_protected` | int | Segments elevated to the soft-protect tier |

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

Workload: 49 real SWE-bench agent trajectories (OpenHands-SFT, SWE-Gym). Strategy: CONSERVATIVE. Avg 29 turns/trajectory. Publicly reproducible.

Dataset: [SWE-Gym/OpenHands-SFT-Trajectories](https://huggingface.co/datasets/SWE-Gym/SWE-Gym) (HuggingFace, public)

| Metric | Result |
|---|---|
| Aggregate token reduction | 24.0% |
| Mean reduction | 25.3% |
| p50 reduction | 25.0% |
| Information retention | 94.7% |
| p10 retention (worst 10%) | 96.0% |
| Instances evaluated | 49 SWE-bench trajectories |

Token reduction and information retention are measured independently. 24% of tokens are removed; 94.7% of compressed content remains semantically recoverable in the compressed context. p10 retention is 96.0% — even the worst-case instances retain their critical information.

Reproduce:
```bash
python examples/benchmark/swebench_eval.py --input trajectories.jsonl
```

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

## License

MIT — see [LICENSE](LICENSE).
