# Batch Routing Guide

Axon's `BatchRouter` integrates with provider batch APIs to reduce costs on
non-latency-sensitive workloads.

---

## Expected Cost Reduction

> **Important:** The ~50% cost reduction figure below is the **expected**
> reduction based on published provider pricing for their batch APIs, not a
> measured production result.  Actual savings depend on your workload, model,
> and provider.  Measured production results will be added to this document
> once sufficient data is collected from opted-in deployments.

Both OpenAI and Anthropic publish ~50% price reductions for requests submitted
via their batch APIs compared to real-time API pricing:

- **OpenAI Batch API**: [OpenAI pricing docs](https://platform.openai.com/docs/guides/batch) — 50% discount on input and output tokens for eligible models.
- **Anthropic Message Batches**: [Anthropic pricing docs](https://docs.anthropic.com/en/docs/build-with-claude/message-batches) — 50% discount on both input and output tokens.

These discounts apply in exchange for accepting up to 24-hour completion
latency.  Batch routing is therefore appropriate only for workloads where
latency is not a constraint.

---

## How It Works

`BatchRouter` inspects each incoming `InferenceSpan`.  When `batch_eligible=True`,
it submits the request to the provider's batch API instead of the real-time API.
When `batch_eligible=False`, the span is passed through to the real-time API
unchanged.

```
InferenceSpan
│
├── batch_eligible=True  → Provider Batch API → BatchJobRecord persisted
│                                                by JobTracker
└── batch_eligible=False → Real-time API (unchanged)
```

Completed batch jobs are collected by a background `poll_and_collect` coroutine.

---

## Quick Start

### Marking spans as batch-eligible

```python
import axon

axon.configure()

# Mark this feature's spans as eligible for batch submission
client = openai.OpenAI()
axon.patch(client, feature_tag="nightly_analysis", batch_eligible=True)
```

### Directly using BatchRouter

```python
from axon.batch.batch_router import BatchRouter
from axon.batch.job_tracker import JobTracker

router = BatchRouter(
    openai_client=openai_client,
    anthropic_client=anthropic_client,
)

# Submit a batch of eligible spans
job = await router.submit_batch(spans=eligible_spans, provider="openai")
print(f"Batch job {job.job_id} submitted, status: {job.status}")
```

---

## BatchJobRecord

```python
from axon.batch.batch_router import BatchJobRecord
from datetime import datetime

# Fields:
# job_id: str
# provider: str              — "openai" or "anthropic"
# status: str                — one of BatchJobStatus enum values
# submitted_at: datetime
# span_count: int
# estimated_completion_at: datetime | None
```

---

## Job Status Lifecycle

Jobs progress through the `BatchJobStatus` enum:

```
PENDING → IN_PROGRESS → COMPLETED
                      ↘ FAILED
                      ↘ EXPIRED
```

---

## Polling for Completed Jobs

The `poll_and_collect` method checks all pending and in-progress jobs and
updates their status:

```python
async with get_db() as db:
    completed_count = await router.poll_and_collect(db=db, provider_client=client)
    print(f"{completed_count} jobs newly completed")
```

This is registered as an APScheduler interval job in the backend and runs
automatically.

---

## Error Handling

If a batch API call fails for any reason, `BatchRouter` logs the error via
structlog and falls back to the real-time API.  It never raises an exception
to the caller.

```
{"event": "batch_router.fallback_to_realtime", "job_id": "...", "reason": "..."}
```

---

## Supported Providers

| Provider | Batch API | Model support |
|---|---|---|
| OpenAI | `POST /v1/batches` | All batch-eligible models |
| Anthropic | Message Batches API | All Claude models |

---

## When to Use Batch Routing

**Good fits:**
- Nightly data processing pipelines
- Bulk document classification or summarization
- Offline evaluation workloads
- Generating embeddings or structured data at scale

**Not suitable for:**
- User-facing features requiring < 5 s latency
- Real-time agent loops
- Interactive applications

---

## See Also

- [ml-router-guide.md](ml-router-guide.md) — ML-based routing
- [provider-expansion.md](provider-expansion.md) — Bedrock and Vertex providers
- [production-validation.md](production-validation.md) — how to submit production data
