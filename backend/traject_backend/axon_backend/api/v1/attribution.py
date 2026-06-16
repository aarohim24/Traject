"""Cost attribution query API endpoints.

Provides ``GET /v1/attribution`` for flexible cost breakdown queries and
``GET /v1/attribution/summary`` for period-based top-N summaries.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_backend.api.v1.spans import verify_api_key
from axon_backend.core.database import get_db
from axon_backend.models.attribution import CostAttributionRecord
from axon_backend.services.cost_attribution import (
    AttributionResponse,
    get_attribution,
)

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["attribution"])

_PERIOD_SECONDS: dict[str, int] = {
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2592000,
}


def _now_naive() -> datetime:
    """Return current UTC time as a naive datetime (no tzinfo).

    The database columns are TIMESTAMP WITHOUT TIME ZONE.  Passing a
    timezone-aware datetime causes a "can't subtract offset-naive and
    offset-aware datetimes" error in asyncpg.  All comparisons against
    these columns must use naive datetimes.
    """
    return datetime.utcnow()


@router.get(
    "/attribution",
    response_model=AttributionResponse,
    dependencies=[Depends(verify_api_key)],
)
async def query_attribution(
    db: AsyncSession = Depends(get_db),
    feature_tag: str | None = Query(default=None),
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    group_by: Literal["model", "provider", "feature_tag"] = Query(default="feature_tag"),
) -> AttributionResponse:
    """Return aggregated cost attribution data.

    Args:
        db: Injected async database session.
        feature_tag: Restrict results to a single feature tag (optional).
        from_ts: Start of time window (defaults to 30 days ago).
        to_ts: End of time window (defaults to now).
        group_by: Aggregation dimension: ``model``, ``provider``, or
            ``feature_tag``.

    Returns:
        AttributionResponse with totals and a per-dimension breakdown.
    """
    now = _now_naive()
    # Strip tzinfo from user-supplied timestamps too (FastAPI may parse them
    # as timezone-aware from ISO-8601 strings with a Z suffix).
    effective_from = (
        from_ts.replace(tzinfo=None) if from_ts is not None else now - timedelta(days=30)
    )
    effective_to = to_ts.replace(tzinfo=None) if to_ts is not None else now

    return await get_attribution(db, feature_tag, effective_from, effective_to, group_by)


@router.get(
    "/attribution/summary",
    dependencies=[Depends(verify_api_key)],
)
async def attribution_summary(
    db: AsyncSession = Depends(get_db),
    period: Literal["daily", "weekly", "monthly"] = Query(default="daily"),
) -> dict[str, object]:
    """Return the top-10 feature tags by cost for the given period.

    Args:
        db: Injected async database session.
        period: Rolling time window: ``daily``, ``weekly``, or ``monthly``.

    Returns:
        Dict with ``period``, ``from_ts``, ``to_ts``, and ``top_feature_tags``
        list, each entry containing ``feature_tag``, ``total_cost_usd``, and
        ``call_count``.
    """
    now = _now_naive()
    seconds = _PERIOD_SECONDS.get(period, 86400)
    from_ts_naive = now - timedelta(seconds=seconds)

    stmt = (
        select(
            CostAttributionRecord.feature_tag,
            func.sum(CostAttributionRecord.total_cost_usd).label("total_cost_usd"),
            func.sum(CostAttributionRecord.call_count).label("call_count"),
        )
        .where(
            CostAttributionRecord.hour_bucket >= from_ts_naive,
            CostAttributionRecord.hour_bucket < now,
        )
        .group_by(CostAttributionRecord.feature_tag)
        .order_by(func.sum(CostAttributionRecord.total_cost_usd).desc())
        .limit(10)
    )

    result = await db.execute(stmt)
    rows = result.fetchall()

    return {
        "period": period,
        "from_ts": from_ts_naive.isoformat(),
        "to_ts": now.isoformat(),
        "top_feature_tags": [
            {
                "feature_tag": r.feature_tag,
                "total_cost_usd": str(r.total_cost_usd or 0),
                "call_count": int(r.call_count or 0),
            }
            for r in rows
        ],
    }
