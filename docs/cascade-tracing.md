# Multi-Agent Cascade Tracing Guide

## The Problem

When an orchestrator agent spawns sub-agents, each agent makes independent LLM calls. Without a shared trace identifier, those calls appear as unrelated spans in your observability stack — you can't aggregate cost, latency, or token usage across an entire multi-agent pipeline. The W3C TraceContext standard solves this: a single `traceparent` HTTP header propagates a 128-bit trace ID across all agents, linking every span into one distributed trace.

---

## Orchestrator Setup

The orchestrator generates the root trace and injects the `traceparent` header into every outbound HTTP request to sub-agents:

```python
from axon.tracer.cascade_tracer import CascadeTracer

tracer = CascadeTracer()
ctx = tracer.start_orchestration(
    feature_tag="document-pipeline",
    metadata={"env": "production", "user_id": "u-123"},
)

# ctx.trace_id is a 32-char lowercase hex string (128-bit)
# ctx.span_id is a 16-char lowercase hex string (64-bit)

# Inject into outbound request headers
import httpx
response = httpx.post(
    "https://sub-agent-service/run",
    headers=ctx.outbound_headers(),   # {"traceparent": "00-<trace_id>-<span_id>-01"}
    json={"task": "summarize", "document": doc},
)
```

---

## Sub-Agent Setup

Sub-agents extract the trace context from inbound headers and continue the same trace:

```python
from axon.tracer.cascade_tracer import CascadeTracer

# In a FastAPI or Flask handler:
def handle_task(request):
    tracer = CascadeTracer()
    ctx = tracer.join_trace(dict(request.headers))

    if ctx is None:
        # No valid traceparent — operate without tracing (fail open)
        ...
    else:
        # ctx.trace_id matches the orchestrator's trace_id
        # ctx.span_id is a new, unique ID for this sub-agent's root span
        outbound = ctx.outbound_headers()
        # Pass outbound headers to any further downstream agents
```

The `join_trace` method never raises — if the `traceparent` header is absent or malformed, it returns `None` and the agent continues without trace context.

---

## Reading Cascade Cost in Grafana

When the Axon backend is running, all spans share the same `trace_id`. Query them in Grafana using the provisioned **Cascade Cost** dashboard:

1. Open **Dashboards → Axon → Cascade Cost Summary**
2. Filter by `trace_id` or `feature_tag`
3. The **Per-Agent Cost Breakdown** panel shows orchestrator vs. sub-agent costs
4. The **Total Cascade Cost** stat shows the end-to-end USD cost for the full pipeline

From code, use `get_cascade_cost`:

```python
summary = tracer.get_cascade_cost(ctx.trace_id, backend_client=backend_client)
print(f"Total pipeline cost: ${summary.total_cost_usd}")
print(f"Span count: {summary.span_count}")
```

---

## W3C TraceContext Compliance

The `traceparent` header format follows the [W3C Trace Context Level 1](https://www.w3.org/TR/trace-context/) specification:

```
traceparent: 00-<trace_id>-<parent_id>-<trace_flags>
```

- `trace_id`: 32 lowercase hexadecimal digits (128-bit random UUID)
- `parent_id`: 16 lowercase hexadecimal digits (64-bit random UUID slice)
- `trace_flags`: `01` (sampled — Axon always samples)

This format is compatible with all W3C-compliant observability backends including Jaeger, Zipkin, Honeycomb, DataDog, and OpenTelemetry collectors. Axon does not implement the `tracestate` header beyond defining its constant name.
