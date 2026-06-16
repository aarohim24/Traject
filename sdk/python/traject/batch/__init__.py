"""Batch routing components for the Traject SDK.

Provides :class:`~traject.batch.batch_router.BatchRouter`,
:class:`~traject.batch.batch_router.BatchJobRecord`, and
:class:`~traject.batch.batch_router.BatchJobStatus` for submitting
batch-eligible spans to provider batch APIs (OpenAI Batch API and
Anthropic Message Batches).

Typical usage::

    from traject.batch import BatchRouter, BatchJobRecord, BatchJobStatus

    router = BatchRouter(openai_client=my_openai_client)
    record = await router.submit_batch(spans, provider="openai")
"""
from __future__ import annotations

from traject.batch.batch_router import BatchJobRecord, BatchJobStatus, BatchRouter

__all__ = [
    "BatchJobRecord",
    "BatchJobStatus",
    "BatchRouter",
]
