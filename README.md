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
- [Integration paths](#integration-paths)
- [Benchmark](#benchmark)
- [Supported providers](#supported-providers)
- [Requirements](#requirements)
- [Architecture](#architecture)
- [Contributing](#contributing)

---

## Installation

```bash
git clone https://github.com/aarohim24/Traject
cd Traject/sdk/python
pip install -e "."
```

Optional framework integrations:

```bash
pip install -e ".[langchain]"   # LangChain support
pip install -e ".[autogen]"     # AutoGen support
pip install -e ".[ccr]"         # reversible compression (Redis-backed)
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

1. **Preprocess (lossless)** — before any lossy decision, two reversible passes shrink the context without dropping information: prose filler (hedging, pleasantries, filler intros) is stripped from assistant turns, and JSON arrays of ≥5 homogeneous objects in tool results are columnarized into a compact table. Both are guarded so they never produce a longer result, and content with fenced code blocks is skipped.
2. **Parse** — the context window is segmented into typed artifacts: `SYSTEM_PROMPT`, `USER_MESSAGE`, `TOOL_RESULT`, `REASONING_BLOCK`, `RAG_CHUNK`, `TOOL_CALL`, `FEW_SHOT_EXAMPLE`, `ASSISTANT_MESSAGE`.
3. **Protect** — system prompts and the last N turns are marked immutable. They are never modified regardless of strategy.
4. **Soft-protect** — each remaining segment is embedded (in-process, `all-MiniLM-L6-v2`) and compared against the next 5 segments via cosine similarity. Two independent signals soft-protect a segment: (a) a later turn *semantically references* it — these stay verbatim; (b) it merely *contains high-information content* (errors, hashes, file paths). A tool result protected only by signal (b) stays eligible for command-aware summarization (below), which preserves exactly that load-bearing information.
5. **Score** — remaining segments are scored by recency (0.4 weight), semantic relevance to the current task (0.4 weight), and reference count in recent turns (0.2 weight). The semantic component is cached within a call by content hash and task-similarity bucket, avoiding redundant embedding lookups for repeated segments.
6. **Compress** — applied in order:
   - **Lossless dedup** — byte-identical tool results that recur (the agent re-reading the same file/command) are replaced with a short reference; the last occurrence is kept verbatim, so no information is lost.
   - **Command-aware summarization** — tool results are sub-classified by the command that produced them (`git diff`, `git log`, pytest, `ls`/`find`, build output) and summarized by a domain-specific compressor that preserves load-bearing facts (failed tests, error types, file:line refs, diff headers) while trimming bulk. Other low-scoring segments are summarized or dropped per strategy thresholds. An inflation guard ensures a replacement is only substituted when strictly smaller.
   - **CCR (optional)** — with a `CCRStore` configured, segments that would be dropped are instead stored in Redis and replaced with a `<<ccr:HASH>>` stub. The agent recovers the full content on demand via the `traject_retrieve` MCP tool — making compression reversible.
7. **Validate** — circuit breaker: if system prompts or recent turns are absent from the compressed output, compression is aborted and the original context is returned unchanged.
8. **Emit** — an OpenTelemetry span records tokens saved, compression ratio, strategy applied, cache hit rate, soft-protected count, and CCR-stubbed count.

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
| `segments_ccr_stubbed` | int | Segments stored in CCR and replaced with a stub |

`tokens_saved` and `compression_ratio` are measured against the **raw input** the caller sent — the lossless preprocessing savings (prose filter, JSON columnarization) are included in the reported reduction, not hidden by shrinking the baseline.

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
bash scripts/setup.sh                            # generates deploy/.env with strong random secrets
docker compose -f deploy/docker-compose.yml up -d
```

`scripts/setup.sh` generates a `deploy/.env` with cryptographically random passwords for Postgres, Redis, and the API key, then prints the API key so you can configure the SDK. The backend refuses to start with the placeholder key, so run this first.

Services started: PostgreSQL 16 + pgvector, Redis 7, Traject backend (port 8000), Grafana dashboards (port 3000), React dashboard (port 5173).

```python
traject.configure(
    backend_url="http://localhost:8000",
    backend_api_key="your-key",
)
```

Adds: cost attribution by feature tag, semantic caching, budget alerts, team dashboards. The backend is optional — the SDK operates independently without it.

---

## Integration paths

### Which integration is right for you?

```
Writing Python/TypeScript code?
  └─ Yes → SDK patch()  (3 lines, zero call-site changes)
  └─ No — I want zero code changes
       ├─ Using Copilot agent mode, Claude Desktop, or Cursor?
       │    └─ MCP server  →  traject mcp
       └─ Running any agent with an OpenAI-compatible client?
            └─ Proxy  →  traject proxy --port 8080 --backend https://api.openai.com
```

### MCP server

Works with GitHub Copilot agent mode, Claude Desktop, Cursor, M365 Copilot declarative agents — no API keys, no code changes.

```bash
pip install -e ".[mcp]"
traject mcp
```

**VS Code / Copilot** (`.vscode/mcp.json`):
```json
{
  "servers": {
    "traject": {
      "command": "traject",
      "args": ["mcp"]
    }
  }
}
```

**Claude Desktop** (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "traject": {
      "command": "traject",
      "args": ["mcp"]
    }
  }
}
```

Four tools are exposed:
- `traject_compress` — compress any text blob (tool output, file, log, RAG chunk), returns compressed text + token delta
- `traject_stats` — session aggregate reduction metrics
- `traject_budget` — set a token limit and check ok / warning / exceeded status
- `traject_retrieve` — recover the full content behind a `<<ccr:HASH>>` stub (requires `TRAJECT_REDIS_URL` and the `[ccr]` extra)

Shadow mode is the default — `traject_compress` returns the original text alongside metrics until you pass `shadow_mode=False`.

### OpenAI-compatible transparent proxy

Zero code changes. Point your agent at `localhost:8080` instead of `api.openai.com`. Works with OpenAI, Azure OpenAI, Ollama, LM Studio, or any OpenAI-compatible backend.

```bash
pip install -e ".[proxy]"

traject proxy --port 8080 --backend https://api.openai.com
# Azure OpenAI: --backend https://your-resource.openai.azure.com
# Ollama:       --backend http://localhost:11434
# Live compression: add --live flag (default is shadow mode)
```

Then in your agent or environment:
```bash
export OPENAI_BASE_URL=http://localhost:8080
```

Every response carries `X-Traject-Tokens-Saved` and `X-Traject-Shadow-Mode` headers.

---

## Benchmark

Workload: 49 real SWE-bench agent trajectories (OpenHands-SFT, SWE-Gym). Avg 29 turns/trajectory. Publicly reproducible.

Dataset: [SWE-Gym/OpenHands-SFT-Trajectories](https://huggingface.co/datasets/SWE-Gym/SWE-Gym) (HuggingFace, public)

49 OpenHands-SFT coding-agent trajectories from SWE-Gym. Token reduction and fact retention measured independently on the same instances.

| Metric | CONSERVATIVE | MODERATE |
|---|---|---|
| **Aggregate token reduction** | **43.1%** | **45.1%** |
| Mean reduction | 40.2% | 41.7% |
| p50 reduction | 41.5% | 46.6% |
| p95 reduction | 62.3% | 65.8% |
| Mean fact preservation | 64.0% | 63.6% |
| p50 fact preservation | 70.0% | 70.0% |
| Instances evaluated | 49 | 49 |

CONSERVATIVE is the safe default — validated for new deployments. Switch to MODERATE after confirming on your workload.

**Reduction** is measured against the raw input tokens the caller sends. **Fact preservation** is the fraction of concrete, non-reconstructable facts — file:line references, error/exception types, test names, git SHAs, URLs — that appear verbatim in the compressed output. This is a deliberately strict, non-circular metric independent of the embedding scorer.

The 64–70% verbatim fact preservation reflects that the pipeline aggressively compresses bulk tool output (large git diffs, full pytest collection, file listings) while preserving failure lines, error types, and function-level identifiers. Facts in actively-referenced segments are fully protected; facts in old, unreferenced bulk output may be summarized away.

Reproduce:
```bash
python examples/benchmark/swebench_eval.py --input trajectories.jsonl --strategy conservative
python examples/benchmark/quality_eval.py --input trajectories.jsonl --strategy conservative
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
