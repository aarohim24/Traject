# Draft: Introducing Axon — Open-Source LLM Cost Optimization Middleware

> **Draft status:** This post is not ready to publish. The benchmark results
> section contains placeholders that must be replaced with real production data
> before publication. Do not publish until the `[PLACEHOLDER]` sections are
> filled in with measured, validated numbers.

---

## Introduction

When you run a 10-step AI agent, you don't pay for each step independently.
You pay for *all prior context* on every single call. Step 1 might send 500
tokens. By step 10 you're sending 5,000 tokens — the same tool outputs, the
same intermediate reasoning, the same messages — on every round trip. At scale,
this isn't an efficiency issue. It's a structural cost problem.

We built Axon to address it at the infrastructure layer, not the application
layer. Axon is a Python middleware library that plugs in between your
application code and your LLM provider clients. It compresses context
trajectories, routes requests to the cheapest qualifying model, attributes cost
at the feature level, and emits structured telemetry — without changing how you
write agent code.

---

## The Problem in Numbers

[PLACEHOLDER: insert production data]

_(This section will show real compression ratios and cost reduction figures
measured on production workloads from opted-in deployments. Synthetic benchmark
results are available in the repository but will not be presented here as
production data.)_

---

## How Axon Works

### Trajectory Compression

Axon parses each context window into typed segments: `SYSTEM_PROMPT`,
`USER_MESSAGE`, `TOOL_RESULT`, `REASONING_BLOCK`, `RAG_CHUNK`, and more.
It protects the system prompt and the most recent turns (never touched), then
scores the remaining segments by recency, semantic relevance to the current
query, and reference count. Low-relevance segments are compressed: tool results
are summarized, completed reasoning blocks are dropped.

Three strategies are available:

| Strategy | Compression target | Typical use |
|---|---|---|
| `CONSERVATIVE` | ~20% | Production systems prioritizing reliability |
| `MODERATE` | ~35% | Balanced workloads |
| `AGGRESSIVE` | ~55% | Cost-sensitive batch processing |

**Shadow mode** (enabled by default) runs the full compression pipeline and
logs what *would* be compressed, but returns the original uncompressed context
to the LLM. This lets you validate compression savings before committing to
live compression.

### Model Routing

Axon's router inspects each request and assigns it to the cheapest model tier
that can handle it. In Phase 5, an ML-based router learns from historical
routing decisions, with conformal prediction guarantees ensuring that the
routing accuracy claim `P(quality >= threshold) >= 1 - alpha` is
mathematically verified, not just estimated.

### Cost Attribution

Every inference span is tagged with a `feature_tag` — a string you provide that
identifies which feature or agent produced the call. The backend aggregates these
into hourly cost totals per feature, giving engineering leads a clear view of
which parts of their system are spending what.

### Budget Controls

Budget limits can be set per feature tag. When a feature approaches or exceeds
its budget, Axon fires a webhook — before the provider invoice arrives.

---

## Getting Started

```bash
pip install axon-sdk
```

```python
import openai
import axon

axon.configure(export_to_stdout=True)
client = openai.OpenAI()
axon.patch(client, feature_tag="my_agent", shadow_mode=True)

# Your existing code unchanged.
```

For team features (cost dashboard, budget alerts, semantic caching):

```bash
git clone https://github.com/aarohimathur/axon
cd axon
docker compose -f deploy/docker-compose.yml up -d
```

---

## What We're Proud Of

**Honesty about uncertainty.** Shadow mode is on by default because we believe
production systems deserve to validate before trusting. Every benchmark in the
repository is reproducible (`python examples/benchmark/run_benchmark.py`) and
clearly labelled as synthetic until production data confirms it.

**No data leaves your infrastructure.** Axon wraps your existing provider
client. It never holds API keys. Prompt content is hashed with SHA-256 before
any telemetry emission. Telemetry collection is opt-in, disabled by default,
and collects only aggregate metrics.

**Framework-agnostic.** LangChain, AutoGen, LlamaIndex, raw OpenAI,
raw Anthropic — Axon works with all of them through a single `axon.patch()`
call.

---

## Community Benchmark Registry

We've added a public benchmark registry at `/v1/benchmarks` where opted-in
deployments can submit aggregate performance metrics. The dashboard page at
`/benchmarks` shows real-world compression ratios and cost figures from
production deployments.

If you'd like to contribute data, see [docs/production-validation.md](../production-validation.md).

---

## What's Next

[PLACEHOLDER: insert production data]

_(Once production validation data is collected, this section will summarize
what we've learned from real deployments and what the roadmap looks like based
on that evidence.)_

---

## Try It

- GitHub: https://github.com/aarohimathur/axon
- PyPI: `pip install axon-sdk`
- Research paper: [docs/research-paper.md](../../docs/research-paper.md)
- Docs: https://github.com/aarohimathur/axon/tree/main/docs
