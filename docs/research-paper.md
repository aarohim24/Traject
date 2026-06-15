# Axon: Production-Grade Context Trajectory Compression and Intelligent Routing for Multi-Step LLM Agents

**Authors:** [Author names redacted for blind review]

**arXiv preprint** · Subject: cs.AI, cs.SE

---

## Abstract

Large language model (LLM) agents accumulate context over multi-step
trajectories, causing each inference call to re-transmit all prior tool
outputs, reasoning traces, and message history.  This quadratic growth in
input tokens constitutes the dominant cost driver in agentic AI systems.
We present **Axon**, an open-source Python middleware library that addresses
this problem at the infrastructure layer through typed artifact classification,
selective trajectory compression, ML-based model routing with conformal
prediction quality guarantees, and feature-level cost attribution via
OpenTelemetry.  Axon operates as a drop-in patch over existing provider
clients (OpenAI, Anthropic, AWS Bedrock, Google Vertex AI), requiring no
changes to application code.  A shadow mode enables safe production validation
before live compression is activated.  Evaluation results are reported in
Section 5; production data from opted-in deployments will be inserted prior to
final submission — see the `[TBD]` markers below.

---

## 1. Introduction

Multi-step AI agents — systems that iteratively call LLMs to plan, use tools,
and reason toward a goal — have become a primary deployment pattern for LLMs in
production software.  A defining characteristic of these systems is *context
accumulation*: each round trip to the provider includes the entire history of
prior interactions.  For a k-step agent, the total input token cost scales as
O(k²) in the worst case.

Existing approaches to managing LLM cost focus primarily on model selection
(choosing cheaper models), prompt engineering (manually shortening prompts), or
caching (avoiding repeated calls).  None of these addresses the structural cost
growth inherent in agentic trajectories.

We make the following contributions:

1. **Typed artifact classification**: A nine-type taxonomy of context segments
   (system prompts, user messages, tool results, reasoning blocks, RAG chunks,
   etc.) enabling per-type optimization policies that respect the semantics of
   each segment type.

2. **Selective trajectory compression**: A compression pipeline that protects
   high-value segments (system prompt, recent turns) while compressing or
   discarding low-relevance historical segments using local semantic similarity
   scoring (sentence-transformers, no external API calls).

3. **Shadow mode**: A production-safe default where compression is computed but
   not applied, enabling operators to validate cost savings before committing.

4. **Conformal prediction routing**: An ML-based router augmented with
   split conformal prediction (Angelopoulos & Bates, 2021) that provides a
   mathematically verified coverage guarantee P(quality ≥ threshold) ≥ 1−α.

5. **Open-source implementation**: A pip-installable Python package with full
   type annotations, OpenTelemetry integration, and a self-hosted backend for
   team-level cost attribution and budget enforcement.

---

## 2. Related Work

**Context window management.**  AgentDiet (FSE 2026) proposes systematic
pruning of agentic context by categorizing segments and applying
compression policies.  Axon extends this direction with a production
middleware implementation that is framework-agnostic and operates on live
inference traffic without requiring changes to agent code.

**LLM cost optimization.**  FrugalGPT (Chen et al., 2023) demonstrates that
cascade routing — trying cheaper models first and escalating on failure — can
achieve significant cost reduction with quality bounds.  Axon's ML router
incorporates a related idea, adding conformal prediction to provide
finite-sample coverage guarantees rather than empirical estimates.

**Conformal prediction.**  Angelopoulos & Bates (2021) provide a comprehensive
treatment of split conformal prediction for machine learning.  We adopt their
quantile-based calibration method to calibrate the routing quality threshold.

**Observability.**  OpenTelemetry (CNCF, 2023) provides a vendor-neutral
telemetry API.  Axon emits all instrumentation as OTEL spans, ensuring
compatibility with the full observability ecosystem.

---

## 3. System Design

### 3.1 Architecture Overview

```
Application Code
      │  axon.patch(client)
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Axon Instrumentation Layer                                  │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Artifact    │  │  Compression │  │  ML Router /     │  │
│  │  Classifier  │→ │  Engine      │  │  Conformal       │  │
│  └──────────────┘  └──────────────┘  │  Predictor       │  │
│                                       └──────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  OTel Span Emitter → Cost Attribution → Budget ctrl  │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
LLM Provider (OpenAI / Anthropic / Bedrock / Vertex)
```

### 3.2 Artifact Classification

Each segment in a context window is assigned one of nine artifact types:
`SYSTEM_PROMPT`, `USER_MESSAGE`, `ASSISTANT_MESSAGE`, `TOOL_RESULT`,
`TOOL_CALL`, `REASONING_BLOCK`, `RAG_CHUNK`, `CODE_BLOCK`, `UNKNOWN`.
Classification uses heuristic rules (header patterns, role fields) augmented
by a lightweight local model.  System prompts achieve zero false negatives in
our test suite — they are never classified as a compressible type.

### 3.3 Compression Pipeline

The pipeline operates in six stages:

1. **Parse**: Segment the context window into typed artifacts.
2. **Protect**: Mark system prompts and the last N turns as inviolable.
3. **Score**: Assign each remaining segment a relevance score ∈ [0, 1] using
   recency decay, semantic similarity to the current query (all-MiniLM-L6-v2,
   384-dim, ~5 ms inference on CPU), and reference count.
4. **Compress**: Apply per-type compression policy to low-scoring segments.
   Tool results are summarized; completed reasoning blocks are dropped.
5. **Validate**: Verify system prompt and recent turns are present; activate
   circuit breaker and revert to original context on failure.
6. **Emit**: Record an OTEL span with `tokens_saved`, `compression_ratio`,
   `strategy`, and `shadow_mode`.

Three compression strategies are provided: `CONSERVATIVE` (targeting ~20%
reduction), `MODERATE` (~35%), and `AGGRESSIVE` (~55%).

### 3.4 ML Router with Conformal Prediction

The `MLRouter` uses logistic regression trained on historical routing decisions
(scikit-learn).  It falls back to the rule-based `RuleRouter` when fewer than
500 labeled examples are available.

Routing quality is guaranteed by the `ConformalRouter` wrapper, which
calibrates a split conformal predictor on a held-out calibration set.  For
miscoverage rate α, the guarantee is:

```
P(quality ≥ threshold) ≥ 1 − α
```

This guarantee holds in the marginal (average) sense over the calibration
distribution, following the finite-sample correctness result of Angelopoulos &
Bates (2021, Theorem 1).

### 3.5 Cost Attribution and Budget Controls

Axon emits structured OTEL spans with `feature_tag`, `model`, `input_tokens`,
`output_tokens`, and `cost_usd` (Decimal-precise).  The backend aggregates
these into hourly totals per feature tag, enabling per-feature budget limits
with webhook alerting.

---

## 4. Implementation

Axon is implemented in Python 3.11+ with full type annotations
(`mypy --strict`, zero errors).  Key implementation decisions:

- **Decimal arithmetic** for all monetary values (ADR-006).
- **Local embedding model** (all-MiniLM-L6-v2) — no external API calls for
  optimization logic (ADR-003).
- **Shadow mode default** — compression never applied without explicit opt-in
  (ADR-004).
- **No credential storage** — Axon wraps the user's existing provider client
  and never holds API keys (ADR-007).
- **Plugin system** — compression, routing, and artifact classification are
  extensible via registered entry-point plugins.

The self-hosted backend is a FastAPI service backed by PostgreSQL 16 +
pgvector and Redis 7.  One-command deployment via Docker Compose.

---

## 5. Evaluation

> **Note on evaluation data:** All `[TBD]` markers in this section will be
> replaced with measured results from production deployments collected via the
> community benchmark registry before final submission.  No numbers are
> fabricated or estimated; only verified production measurements will appear
> in this section.

### 5.1 Compression Effectiveness

| Strategy | Workload | Input token reduction | Cost reduction |
|---|---|---|---|
| CONSERVATIVE | 10-step code review agent | [TBD] | [TBD] |
| MODERATE | 10-step code review agent | [TBD] | [TBD] |
| AGGRESSIVE | 10-step code review agent | [TBD] | [TBD] |

*Synthetic benchmark (tiktoken exact counting):* 14.0% reduction with CONSERVATIVE
on our reference 10-step trajectory.  Production numbers pending.

### 5.2 Routing Accuracy

| Router | Accuracy | p95 latency |
|---|---|---|
| RuleRouter (baseline) | [TBD] | [TBD] |
| MLRouter (≥500 examples) | [TBD] | [TBD] |
| ConformalRouter (α=0.1) | Coverage ≥ 90% (guaranteed) | [TBD] |

### 5.3 Overhead

SDK instrumentation overhead measured in microseconds (no compression):

| Percentile | Measured overhead |
|---|---|
| p50 | [TBD] |
| p95 | [TBD] |
| p99 | [TBD] |

*Reference threshold:* < 5 ms p50 (designed SLO).

### 5.4 Community Benchmark Data

[TBD — to be populated from the public benchmark registry at `/v1/benchmarks`
once sufficient opted-in production submissions are available.]

---

## 6. Conclusion

Axon addresses the structural cost growth of multi-step LLM agents through
infrastructure-layer middleware rather than application-layer changes.  The
combination of typed artifact classification, selective trajectory compression,
conformal-prediction-guaranteed routing, and OpenTelemetry-native observability
provides a production-ready foundation for cost-efficient agentic AI systems.

Shadow mode ensures that operators can validate savings before committing to
live compression, addressing the trust gap that typically prevents compression
techniques from being deployed in production.

The community benchmark registry enables crowd-sourced production validation,
ensuring that published performance claims are grounded in real-world data
rather than synthetic benchmarks alone.

---

## References

- Angelopoulos, A. N., & Bates, S. (2021). *A gentle introduction to conformal
  prediction and distribution-free uncertainty quantification.*
  arXiv:2107.07511.

- Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large
  language models while reducing cost and improving performance.*
  arXiv:2305.05176.

- CNCF OpenTelemetry. (2023). *OpenTelemetry specification.*
  https://opentelemetry.io/docs/specs/otel/

- [AgentDiet citation — to be confirmed before submission]

---

## Appendix A: Reproducibility

All experiments can be reproduced using the open-source repository:

```bash
git clone https://github.com/aarohimathur/axon
cd axon
pip install -e "sdk/python[dev]"
python examples/benchmark/run_benchmark.py
```

No external API keys are required for the synthetic benchmark.  Production
validation requires access to a live LLM provider.
