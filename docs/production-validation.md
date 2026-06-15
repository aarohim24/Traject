# Production Validation Guide

This document explains how to validate Axon's compression and routing
performance on your own production workloads, and how to optionally submit
aggregate benchmark data to the community registry.

---

## Why Validate in Production?

Synthetic benchmarks (like the one in `examples/benchmark/`) run on a fixed,
representative trajectory.  Real-world performance depends on your specific
agent topology, model choice, prompt structure, and context accumulation
patterns.  Production validation gives you ground truth.

---

## Step 1: Enable Shadow Mode

Shadow mode is Axon's default.  It runs the full compression pipeline and logs
what *would* be compressed, but returns the original uncompressed context to
the LLM.  This means you can measure compression potential with zero risk.

```python
import openai
import axon

axon.configure(export_to_stdout=True)
client = openai.OpenAI()

# shadow_mode=True is the default — explicit here for clarity
axon.patch(client, feature_tag="my_agent", shadow_mode=True)
```

Run your agent workload normally.  Each call emits an OTEL span with:

| Attribute | Description |
|---|---|
| `axon.compression.tokens_saved` | Tokens that would have been saved |
| `axon.compression.compression_ratio` | Ratio of compressed to original tokens |
| `axon.compression.strategy` | Compression strategy used |
| `axon.compression.shadow_mode` | `true` (shadow mode was active) |

---

## Step 2: Analyse Shadow Mode Results

Use the [compression analysis notebook](../research/notebooks/compression_analysis.ipynb)
or query spans directly:

```python
# Using the backend API (requires self-hosted backend)
import httpx

resp = httpx.get(
    "http://localhost:8000/v1/attribution",
    headers={"X-Axon-API-Key": "your-key"},
    params={"feature_tag": "my_agent", "days": 7},
)
print(resp.json())
```

Look for:
- Consistent `compression_ratio > 0.0` across calls (compression potential exists)
- `tokens_saved` that would translate to meaningful cost reduction at your volume
- No unexpected `circuit_breaker_triggered` events

---

## Step 3: Enable Live Compression

Once you're satisfied with the shadow mode results, flip the flag:

```python
axon.patch(client, feature_tag="my_agent", shadow_mode=False)
```

Monitor for at least 100 calls before drawing conclusions.  The OTEL spans
will now show actual token savings rather than estimated ones.

---

## Step 4: Submit to the Community Registry (Optional, Opt-In)

If you'd like to contribute your aggregate, anonymized benchmark results to
the community registry, use `TelemetryReporter`:

```python
from axon.core.telemetry_reporter import TelemetryReporter, TelemetryPayload
from datetime import datetime, timezone

# Disabled by default — explicit opt-in required
reporter = TelemetryReporter(enabled=True, backend_url="https://axon.example.com")

payload = TelemetryPayload(
    sdk_version="0.5.0",
    python_version="3.11.9",
    sample_count=1000,          # number of inference spans analyzed
    p50_cost_usd="0.00012345",  # median per-call cost (Decimal string)
    p95_cost_usd="0.00087654",  # 95th-percentile per-call cost
    p50_compression_ratio=0.18,
    p95_compression_ratio=0.42,
    avg_routing_accuracy=0.94,
    submitted_at=datetime.now(timezone.utc),
)

success = await reporter.submit(payload)
print("Submitted:", success)
```

### What is collected

The `TelemetryReporter` submits **only aggregate, non-personally-identifiable
metrics**.  The following are **never** collected or transmitted:

- Prompt content (any text you send to LLMs)
- User IDs or identifiers
- API keys or credentials
- Host names or IP addresses
- Request-level detail

### Disabling telemetry

Telemetry is **disabled by default**.  If you have not instantiated
`TelemetryReporter(enabled=True)` or set `AXON_TELEMETRY_ENABLED=true`,
no data is ever collected or transmitted.

---

## Viewing Community Benchmarks

Submitted benchmarks are publicly visible at:

- **Dashboard**: `http://your-axon-backend/benchmarks`
- **API**: `GET http://your-axon-backend/v1/benchmarks`

No authentication is required to read the registry.

---

## Interpreting Results

| Metric | Good signal | Investigate if |
|---|---|---|
| `p50_compression_ratio` | 0.10 – 0.40 | < 0.02 (little compressible content) or > 0.60 (very aggressive, check quality) |
| `avg_routing_accuracy` | > 0.85 | < 0.70 (router may need retraining or recalibration) |
| `p95_cost_usd` | Stable or decreasing over time | Sharp increase (check for context growth or model price changes) |

---

## See Also

- [ml-router-guide.md](ml-router-guide.md) — understanding routing accuracy
- [batch-routing.md](batch-routing.md) — additional cost reduction via batch APIs
- [research/notebooks/compression_analysis.ipynb](../research/notebooks/compression_analysis.ipynb) — analysis notebook
- [docs/research-paper.md](../docs/research-paper.md) — technical background
