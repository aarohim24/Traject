"""Span ingestion service for the Traject backend.

Receives batches of ``InferenceSpanPayload`` objects from the SDK,
validates timestamps, bulk-inserts accepted spans, and triggers budget
checks for every unique feature tag in the accepted batch.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.models.span import InferenceSpanRecord

_log = structlog.get_logger(__name__)

# Spans with a timestamp more than this many seconds in the future are rejected.
_FUTURE_TOLERANCE_SECONDS = 60


class BudgetStatus(StrEnum):
    """Budget enforcement status for a feature tag.

    Attributes:
        OK: Spend is below the alert threshold.
        WARNING: Spend is between the alert threshold and the budget limit.
        EXHAUSTED: Spend has reached or exceeded the budget limit.
    """

    OK = "ok"
    WARNING = "warning"
    EXHAUSTED = "exhausted"


class InferenceSpanPayload(BaseModel):
    """Wire-format representation of a single LLM inference span.

    Mirrors the Phase 1 ``InferenceSpan`` Pydantic model but uses plain
    JSON-serialisable types so it can travel over HTTP without the SDK
    dependency.

    All fields are optional at the service boundary to allow graceful
    handling of partial payloads from older SDK versions.
    """

    id: uuid.UUID | None = None
    trace_id: str = ""
    parent_span_id: str | None = None
    span_name: str = ""
    timestamp: datetime
    duration_ms: int = 0
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    token_count_method: str = "exact"
    cost_usd: Decimal | None = None
    feature_tag: str = "default"
    prompt_hash: str = ""
    artifact_type: str = "unknown"
    compression_applied: bool = False
    shadow_mode: bool = True
    pre_compression_tokens: int | None = None
    tokens_saved: int | None = None
    cache_hit: bool = False
    environment: str = "production"


class SpanIngestRequest(BaseModel):
    """Request body for ``POST /v1/spans``.

    Attributes:
        spans: Batch of span payloads.  Maximum 1 000 per request.
    """

    spans: list[InferenceSpanPayload] = Field(max_length=1000)


class SpanIngestResponse(BaseModel):
    """Response body for ``POST /v1/spans``.

    Attributes:
        accepted: Number of spans successfully persisted.
        rejected: Number of spans rejected due to validation failures.
    """

    accepted: int
    rejected: int


async def ingest_spans(
    spans: list[InferenceSpanPayload],
    db: AsyncSession,
    redis: Any,  # noqa: ANN401 — redis.asyncio.Redis; Any avoids runtime import
) -> SpanIngestResponse:
    """Validate, persist, and post-process a batch of inference spans.

    Args:
        spans: Batch of span payloads received from the SDK client.
        db: An active async SQLAlchemy session.
        redis: The shared Redis client (used for budget checks).

    Returns:
        SpanIngestResponse with counts of accepted and rejected spans.

    Notes:
        Spans whose ``timestamp`` is more than 60 seconds in the future are
        rejected.  All remaining spans are bulk-inserted using
        ``ON CONFLICT DO NOTHING`` to avoid duplicate-key errors.
        Budget enforcement is triggered asynchronously for each unique
        ``feature_tag`` in the accepted batch.
    """
    now_utc = datetime.now(tz=timezone.utc)
    cutoff = now_utc + timedelta(seconds=_FUTURE_TOLERANCE_SECONDS)

    valid: list[InferenceSpanPayload] = []
    rejected_count = 0

    for span in spans:
        # Normalise to UTC-aware if naive
        ts = span.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts > cutoff:
            rejected_count += 1
            _log.debug(""traject.ingest.rejected_future_timestamp", timestamp=str(ts))
        else:
            valid.append(span)

    if valid:
        rows = [
            {
                "id": s.id or uuid.uuid4(),
                "trace_id": s.trace_id,
                "parent_span_id": s.parent_span_id,
                "span_name": s.span_name,
                # Strip timezone — DB column is TIMESTAMP WITHOUT TIME ZONE
                "timestamp": s.timestamp.replace(tzinfo=None)
                if s.timestamp.tzinfo is not None
                else s.timestamp,
                "duration_ms": s.duration_ms,
                "provider": s.provider,
                "model": s.model,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "cached_tokens": s.cached_tokens,
                "token_count_method": s.token_count_method,
                "cost_usd": s.cost_usd,
                "feature_tag": s.feature_tag,
                "prompt_hash": s.prompt_hash,
                "artifact_type": s.artifact_type,
                "compression_applied": s.compression_applied,
                "shadow_mode": s.shadow_mode,
                "pre_compression_tokens": s.pre_compression_tokens,
                "tokens_saved": s.tokens_saved,
                "cache_hit": s.cache_hit,
                "environment": s.environment,
            }
            for s in valid
        ]
        from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415

        stmt = pg_insert(InferenceSpanRecord).values(rows).on_conflict_do_nothing()
        await db.execute(stmt)
        await db.commit()

        # Trigger budget checks for unique feature tags
        unique_tags = {s.feature_tag for s in valid}
        for tag in unique_tags:
            try:
                # Lazy import to avoid circular dependency with budget_enforcer
                from traject_backend.services.budget_enforcer import check_budget  # noqa: PLC0415

                status = await check_budget(tag, db, redis)
                _log.debug(""traject.budget.check", feature_tag=tag, status=status)
            except Exception as exc:  # noqa: BLE001
                _log.warning(""traject.budget.check.failed", feature_tag=tag, error=str(exc))

    return SpanIngestResponse(accepted=len(valid), rejected=rejected_count)
