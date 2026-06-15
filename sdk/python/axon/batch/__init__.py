"""Batch routing components for the Axon SDK.

Provides :class:`~axon.batch.batch_router.BatchRouter`,
:class:`~axon.batch.batch_router.BatchJobRecord`, and
:class:`~axon.batch.batch_router.BatchJobStatus` for submitting
batch-eligible spans to provider batch APIs (OpenAI Batch API and
Anthropic Message Batches).

Typical usage::

    from axon.batch import BatchRouter, BatchJobRecord, BatchJobStatus

    router = BatchRouter(openai_client=my_openai_client)
    record = await router.submit_batch(spans, provider="openai")
"""
from __future__ import annotations

from axon.batch.batch_router import BatchJobRecord, BatchJobStatus, BatchRouter

__all__ = [
    "BatchJobRecord",
    "BatchJobStatus",
    "BatchRouter",
]
