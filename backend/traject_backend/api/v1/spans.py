"""Span ingestion and query API endpoints.

Provides ``POST /v1/spans`` for SDK batch ingestion and ``GET /v1/spans``
for querying persisted spans.  All routes require ``X-Traject-API-Key``
authentication.
"""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.core.auth import CurrentTenant
from traject_backend.core.config import settings
from traject_backend.core.database import get_db
from traject_backend.core.redis_client import get_redis
from traject_backend.models.span import InferenceSpanRecord
from traject_backend.services.span_ingestion import (
    InferenceSpanPayload,
    SpanIngestRequest,
    SpanIngestResponse,
    ingest_spans,
)

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["spans"])


async def verify_api_key(
    x_traject_api_key: Annotated[str | None, Header(alias="X-Traject-API-Key")] = None,
) -> None:
    """FastAPI dependency that enforces API key authentication.

    Args:
        x_traject_api_key: Value of the ``X-Traject-API-Key`` request header.

    Raises:
        HTTPException: 401 when the header is missing or the key is invalid.
    """
    if x_traject_api_key is None or not hmac.compare_digest(x_traject_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@router.post(
    "/spans",
    status_code=202,
    response_model=SpanIngestResponse,
)
async def create_spans(
    request: SpanIngestRequest,
    tenant_id: CurrentTenant,
    db: AsyncSession = Depends(get_db),
) -> SpanIngestResponse:
    """Ingest a batch of LLM inference spans.

    Validates each span, bulk-inserts accepted spans, and triggers budget
    checks.  Spans with a future timestamp (> 60 s ahead) are counted as
    rejected but do not cause the whole request to fail.

    Args:
        request: Batch of span payloads.  Maximum 1 000 per call.
        db: Injected async database session.

    Returns:
        SpanIngestResponse with accepted and rejected counts.
    """
    redis = get_redis()
    return await ingest_spans(request.spans, db, redis, tenant_id=tenant_id)


@router.get(
    "/spans",
    response_model=list[InferenceSpanPayload],
)
async def list_spans(
    tenant_id: CurrentTenant,
    db: AsyncSession = Depends(get_db),
    feature_tag: str | None = Query(default=None),
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    limit: int = Query(default=100, le=1000, ge=1),
) -> list[InferenceSpanPayload]:
    """Query persisted inference spans with optional filters.

    Args:
        db: Injected async database session.
        feature_tag: Filter by feature tag (optional).
        from_ts: Start of time window, inclusive (optional).
        to_ts: End of time window, exclusive (optional).
        limit: Maximum rows to return.  Capped at 1 000.

    Returns:
        List of matching span payloads.
    """
    stmt = (
        select(InferenceSpanRecord)
        .where(InferenceSpanRecord.tenant_id == tenant_id)
        .order_by(InferenceSpanRecord.timestamp.desc())
        .limit(limit)
    )

    if feature_tag is not None:
        stmt = stmt.where(InferenceSpanRecord.feature_tag == feature_tag)
    if from_ts is not None:
        stmt = stmt.where(InferenceSpanRecord.timestamp >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(InferenceSpanRecord.timestamp < to_ts)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        InferenceSpanPayload(
            id=r.id,
            trace_id=r.trace_id,
            parent_span_id=r.parent_span_id,
            span_name=r.span_name,
            timestamp=r.timestamp,
            duration_ms=r.duration_ms,
            provider=r.provider,
            model=r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            cached_tokens=r.cached_tokens,
            token_count_method=r.token_count_method,
            cost_usd=r.cost_usd,
            feature_tag=r.feature_tag,
            prompt_hash=r.prompt_hash,
            artifact_type=r.artifact_type,
            compression_applied=r.compression_applied,
            shadow_mode=r.shadow_mode,
            pre_compression_tokens=r.pre_compression_tokens,
            tokens_saved=r.tokens_saved,
            cache_hit=r.cache_hit,
            environment=r.environment,
        )
        for r in rows
    ]
