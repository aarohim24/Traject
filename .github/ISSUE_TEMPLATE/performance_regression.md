---
name: Performance Regression
about: Token count, latency, or cost is worse than expected after using Axon
labels: performance
---

## Environment

| Field | Value |
|---|---|
| Axon SDK version | <!-- e.g. 0.2.0 --> |
| Python version | <!-- e.g. 3.11.9 --> |
| Agent framework | <!-- LangChain / AutoGen / raw OpenAI / raw Anthropic / other --> |
| OS | <!-- e.g. macOS 14, Ubuntu 22.04 --> |

## Benchmark Configuration

| Field | Value |
|---|---|
| Steps per run | <!-- Number of agent steps in your benchmark --> |
| Compression strategy | <!-- CONSERVATIVE / MODERATE / AGGRESSIVE / shadow mode --> |
| Shadow mode enabled | <!-- Yes / No --> |
| Runs averaged | <!-- How many runs did you average over? --> |

## Token Counts

| Metric | Baseline (no Axon) | With Axon |
|---|---|---|
| Prompt tokens (avg per run) | | |
| Completion tokens (avg per run) | | |
| Total tokens (avg per run) | | |
| Estimated cost per run | | |

## Latency

| Metric | Baseline (no Axon) | With Axon |
|---|---|---|
| End-to-end wall time (avg) | | |
| p99 wall time | | |

## Reproduction

<!-- Paste the smallest benchmark script that reproduces the regression.
     Remove any API keys or sensitive data before posting. -->

```python

```

## Expected Behaviour

<!-- What compression ratio or overhead did you expect based on the docs or prior runs? -->

## Actual Behaviour

<!-- What did you measure instead? -->

## Additional Context

<!-- Anything else: trajectory length distribution, segment types, related issues. -->
