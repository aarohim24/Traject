"""Cost attribution aggregation service for the Traject backend.

Materialises hourly aggregates from ``inference_spans`` into the
``cost_attribution`` table and provides query helpers used by the
attribution API endpoints.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

import sqlalchemy as sa
import structlog
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.models.attribution import CostAttributionRecord
from traject_backend.models.span import InferenceSpanRecord
from traject_backend.models.tenant import DEFAULT_TENANT_ID

_log = structlog.get_logger(__name__)

GroupByType = Literal["model", "provider", "feature_tag"]


class AttributionRow(BaseModel):
    """A single row in a cost attribution breakdown.

    Attributes:
        dimension: The value of the group-by column (model name, provider,
            or feature tag).
        total_cost_usd: Total USD spend for this dimension in the period.
        total_tokens: Sum of input + output tokens.
        total_tokens_saved: Tokens eliminated by compression.
        call_count: Number of LLM API calls.
        cache_hit_count: Calls served from the provider's prompt cache.
    """

    dimension: str
    total_cost_usd: Decimal
    total_tokens: int
    total_tokens_saved: int
    call_count: int
    cache_hit_count: int


class AttributionResponse(BaseModel):
    """Full attribution query result returned by ``GET /v1/attribution``.

    Attributes:
        total_cost_usd: Sum of all ``AttributionRow.total_cost_usd`` values.
        total_tokens: Sum of all ``AttributionRow.total_tokens`` values.
        total_savings_usd: Estimated USD value of compression savings.
        breakdown: Per-dimension breakdown rows.
    """

    total_cost_usd: Decimal
    total_tokens: int
    total_savings_usd: Decimal
    breakdown: list[AttributionRow]


async def materialize_hourly(db: AsyncSession, hour: datetime) -> int:
    """Aggregate inference spans for one hour and upsert into cost_attribution.

    Groups all spans with ``timestamp`` in ``[hour, hour + 1h)`` by
    ``(feature_tag, provider, model)`` and upserts the results.  Calling
    this function twice for the same hour is idempotent: the upsert
    overwrites existing rows rather than creating duplicates.

    Args:
        db: An active async SQLAlchemy session.
        hour: The start of the one-hour window to materialise.  Should be
            truncated to the hour (minutes=0, seconds=0, microseconds=0).

    Returns:
        The number of rows inserted or updated.
    """
    hour_start = hour.replace(minute=0, second=0, microsecond=0)
    if hour_start.tzinfo is None:
        hour_start = hour_start.replace(tzinfo=UTC)
    hour_end = hour_start + timedelta(hours=1)

    # Strip timezone for DB comparison (TIMESTAMP WITHOUT TIME ZONE columns).
    hour_start_naive = hour_start.replace(tzinfo=None)
    hour_end_naive = hour_end.replace(tzinfo=None)

    # Aggregate spans for the target hour
    agg = (
        select(
            InferenceSpanRecord.tenant_id,
            InferenceSpanRecord.feature_tag,
            InferenceSpanRecord.provider,
            InferenceSpanRecord.model,
            func.sum(InferenceSpanRecord.input_tokens).label("total_input_tokens"),
            func.sum(InferenceSpanRecord.output_tokens).label("total_output_tokens"),
            func.sum(InferenceSpanRecord.cached_tokens).label("total_cached_tokens"),
            func.coalesce(
                func.sum(InferenceSpanRecord.cost_usd), Decimal("0")
            ).label("total_cost_usd"),
            func.coalesce(
                func.sum(InferenceSpanRecord.tokens_saved), 0
            ).label("total_tokens_saved"),
            func.count().label("call_count"),
            func.sum(
                func.cast(InferenceSpanRecord.cache_hit, sa.Integer())
            ).label("cache_hit_count"),
            func.percentile_cont(0.5)
            .within_group(InferenceSpanRecord.duration_ms)
            .label("p50_latency_ms"),
            func.percentile_cont(0.95)
            .within_group(InferenceSpanRecord.duration_ms)
            .label("p95_latency_ms"),
        )
        .where(
            InferenceSpanRecord.timestamp >= hour_start_naive,
            InferenceSpanRecord.timestamp < hour_end_naive,
        )
        .group_by(
            InferenceSpanRecord.tenant_id,
            InferenceSpanRecord.feature_tag,
            InferenceSpanRecord.provider,
            InferenceSpanRecord.model,
        )
    )

    result = await db.execute(agg)
    rows = result.fetchall()

    if not rows:
        return 0

    upsert_rows = [
        {
            "tenant_id": r.tenant_id,
            "feature_tag": r.feature_tag,
            "hour_bucket": hour_start_naive,
            "provider": r.provider,
            "model": r.model,
            "total_input_tokens": int(r.total_input_tokens or 0),
            "total_output_tokens": int(r.total_output_tokens or 0),
            "total_cached_tokens": int(r.total_cached_tokens or 0),
            "total_cost_usd": Decimal(str(r.total_cost_usd or 0)),
            "total_tokens_saved": int(r.total_tokens_saved or 0),
            "cost_saved_compression_usd": Decimal("0"),
            "cost_saved_cache_usd": Decimal("0"),
            "call_count": int(r.call_count or 0),
            "cache_hit_count": int(r.cache_hit_count or 0),
            "p50_latency_ms": int(r.p50_latency_ms or 0),
            "p95_latency_ms": int(r.p95_latency_ms or 0),
        }
        for r in rows
    ]

    stmt = pg_insert(CostAttributionRecord).values(upsert_rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_attribution_feature_hour_provider_model",
        set_={
            "total_input_tokens": stmt.excluded.total_input_tokens,
            "total_output_tokens": stmt.excluded.total_output_tokens,
            "total_cached_tokens": stmt.excluded.total_cached_tokens,
            "total_cost_usd": stmt.excluded.total_cost_usd,
            "total_tokens_saved": stmt.excluded.total_tokens_saved,
            "call_count": stmt.excluded.call_count,
            "cache_hit_count": stmt.excluded.cache_hit_count,
            "p50_latency_ms": stmt.excluded.p50_latency_ms,
            "p95_latency_ms": stmt.excluded.p95_latency_ms,
        },
    )
    await db.execute(stmt)
    await db.commit()

    _log.info(
        "traject.attribution.materialized",
        hour=str(hour_start),
        rows=len(upsert_rows),
    )
    return len(upsert_rows)


async def get_attribution(
    db: AsyncSession,
    feature_tag: str | None,
    from_ts: datetime,
    to_ts: datetime,
    group_by: GroupByType,
    tenant_id: uuid.UUID = DEFAULT_TENANT_ID,
) -> AttributionResponse:
    """Query the cost_attribution table with optional filters.

    Args:
        db: An active async SQLAlchemy session.
        feature_tag: When provided, restricts results to this feature tag.
        from_ts: Start of the query window (inclusive).
        to_ts: End of the query window (exclusive).
        group_by: Column to aggregate by: ``"model"``, ``"provider"``, or
            ``"feature_tag"``.

    Returns:
        An ``AttributionResponse`` with a breakdown list and totals.
    """
    # Strip timezone info — the DB column is TIMESTAMP WITHOUT TIME ZONE.
    # All values are stored as UTC; we just drop the tzinfo marker.
    from_ts_naive = from_ts.replace(tzinfo=None)
    to_ts_naive = to_ts.replace(tzinfo=None)

    # Map group_by string to the correct ORM column
    group_col_map = {
        "model": CostAttributionRecord.model,
        "provider": CostAttributionRecord.provider,
        "feature_tag": CostAttributionRecord.feature_tag,
    }
    group_col = group_col_map[group_by]

    stmt = (
        select(
            group_col.label("dimension"),
            func.sum(CostAttributionRecord.total_cost_usd).label("total_cost_usd"),
            (
                func.sum(CostAttributionRecord.total_input_tokens)
                + func.sum(CostAttributionRecord.total_output_tokens)
            ).label("total_tokens"),
            func.sum(CostAttributionRecord.total_tokens_saved).label("total_tokens_saved"),
            func.sum(CostAttributionRecord.call_count).label("call_count"),
            func.sum(CostAttributionRecord.cache_hit_count).label("cache_hit_count"),
        )
        .where(
            CostAttributionRecord.tenant_id == tenant_id,
            CostAttributionRecord.hour_bucket >= from_ts_naive,
            CostAttributionRecord.hour_bucket < to_ts_naive,
        )
        .group_by(group_col)
        .order_by(func.sum(CostAttributionRecord.total_cost_usd).desc())
    )

    if feature_tag is not None:
        stmt = stmt.where(CostAttributionRecord.feature_tag == feature_tag)

    result = await db.execute(stmt)
    rows = result.fetchall()

    breakdown = [
        AttributionRow(
            dimension=str(r.dimension),
            total_cost_usd=Decimal(str(r.total_cost_usd or 0)),
            total_tokens=int(r.total_tokens or 0),
            total_tokens_saved=int(r.total_tokens_saved or 0),
            call_count=int(r.call_count or 0),
            cache_hit_count=int(r.cache_hit_count or 0),
        )
        for r in rows
    ]

    total_cost = sum((r.total_cost_usd for r in breakdown), Decimal("0"))
    total_tokens = sum(r.total_tokens for r in breakdown)
    # Estimate savings: assume $2.50/1M tokens for simplified calculation
    total_saved_tokens = sum(r.total_tokens_saved for r in breakdown)
    total_savings = Decimal(str(total_saved_tokens)) * Decimal("0.0000025")

    return AttributionResponse(
        total_cost_usd=total_cost,
        total_tokens=total_tokens,
        total_savings_usd=total_savings,
        breakdown=breakdown,
    )
