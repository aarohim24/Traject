"""Budget enforcement service for the Axon backend.

Checks feature-tag spend against configured budgets using Redis as a fast
read path, and fires HTTP webhook notifications when thresholds are crossed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.core.config import settings
from traject_backend.models.budget import BudgetControlRecord
from traject_backend.models.span import InferenceSpanRecord
from traject_backend.services.span_ingestion import BudgetStatus

_log = structlog.get_logger(__name__)

_PERIOD_DELTAS: dict[str, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}


class BudgetAlertPayload(BaseModel):
    """Payload sent to a budget-alert webhook endpoint.

    Attributes:
        feature_tag: The feature tag that triggered the alert.
        budget_usd: The configured budget limit.
        spent_usd: Current spend within the budget period.
        pct_used: Fraction of budget consumed (0.0–1.0+).
        status: ``"warning"`` or ``"exhausted"``.
        timestamp: ISO-8601 UTC timestamp of the alert.
    """

    feature_tag: str
    budget_usd: Decimal
    spent_usd: Decimal
    pct_used: float
    status: str
    timestamp: str


async def check_budget(
    feature_tag: str,
    db: AsyncSession,
    redis: Any,  # noqa: ANN401 — redis.asyncio.Redis avoids runtime circular import
) -> BudgetStatus:
    """Check current spend against the configured budget for a feature tag.

    Uses Redis as a fast read path (O(1) GET).  On a cache miss the spend
    is computed from the ``inference_spans`` DB table and stored in Redis.
    On any error the function returns :attr:`BudgetStatus.OK` (fail open).

    Args:
        feature_tag: The feature tag whose budget should be checked.
        db: An active async SQLAlchemy session.
        redis: The shared Redis client.

    Returns:
        :attr:`BudgetStatus.OK`, :attr:`BudgetStatus.WARNING`, or
        :attr:`BudgetStatus.EXHAUSTED`.
    """
    try:
        # ------------------------------------------------------------------
        # Fast path: cached spend counter in Redis
        # ------------------------------------------------------------------
        redis_key = f"axon:budget:{feature_tag}"
        cached_value = await redis.get(redis_key)
        if cached_value is not None:
            spent = Decimal(str(cached_value))
        else:
            # ------------------------------------------------------------------
            # Slow path: compute from DB, then cache
            # ------------------------------------------------------------------
            budget_row = await _load_budget(db, feature_tag)
            if budget_row is None:
                return BudgetStatus.OK

            period_start = _period_start(budget_row.period)
            result = await db.execute(
                select(func.coalesce(func.sum(InferenceSpanRecord.cost_usd), Decimal("0"))).where(
                    InferenceSpanRecord.feature_tag == feature_tag,
                    InferenceSpanRecord.timestamp >= period_start,
                )
            )
            spent = Decimal(str(result.scalar() or 0))

            await redis.set(
                redis_key,
                str(spent),
                ex=settings.redis_cache_ttl_seconds,
            )

        # ------------------------------------------------------------------
        # Evaluate against budget
        # ------------------------------------------------------------------
        budget_row = await _load_budget(db, feature_tag)
        if budget_row is None:
            return BudgetStatus.OK

        pct = float(spent) / float(budget_row.budget_usd) if budget_row.budget_usd else 0.0

        if pct >= 1.0:
            return BudgetStatus.EXHAUSTED
        if pct >= float(budget_row.alert_threshold_pct):
            return BudgetStatus.WARNING
        return BudgetStatus.OK

    except Exception as exc:  # noqa: BLE001
        _log.warning(""traject.budget.check.error", feature_tag=feature_tag, error=str(exc))
        return BudgetStatus.OK


async def _load_budget(
    db: AsyncSession, feature_tag: str
) -> BudgetControlRecord | None:
    """Load the budget record for a feature tag, or return None.

    Args:
        db: An active async SQLAlchemy session.
        feature_tag: The feature tag to look up.

    Returns:
        The ``BudgetControlRecord`` or ``None`` if not configured.
    """
    result = await db.execute(
        select(BudgetControlRecord).where(
            BudgetControlRecord.feature_tag == feature_tag
        )
    )
    return result.scalar_one_or_none()


def _period_start(period: str) -> datetime:
    """Return the naive UTC start of the current budget period.

    Returns a timezone-naive datetime suitable for comparison against
    TIMESTAMP WITHOUT TIME ZONE database columns.  All values are
    implicitly UTC.

    Args:
        period: ``"daily"``, ``"weekly"``, or ``"monthly"``.

    Returns:
        Naive UTC datetime at the start of the current period.
    """
    now = datetime.utcnow()
    delta = _PERIOD_DELTAS.get(period, timedelta(days=1))
    # Strip timezone — DB columns are TIMESTAMP WITHOUT TIME ZONE
    return (now - delta).replace(tzinfo=None)


async def fire_webhook(
    webhook_url: str,
    payload: BudgetAlertPayload,
) -> None:
    """POST a budget-alert notification to an external webhook endpoint.

    Never raises — all exceptions are caught and logged.  The timeout is
    taken from :attr:`~traject_backend.core.config.Settings.budget_alert_webhook_timeout_seconds`.

    Args:
        webhook_url: The HTTP(S) URL to POST to.
        payload: The alert payload to serialise as JSON.
    """
    try:
        timeout = float(settings.budget_alert_webhook_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                webhook_url,
                json=payload.model_dump(),
                headers={"Content-Type": "application/json"},
            )
            if response.is_success:
                _log.info(
                    ""traject.budget.webhook.sent",
                    feature_tag=payload.feature_tag,
                    status_code=response.status_code,
                )
            else:
                _log.warning(
                    ""traject.budget.webhook.error_response",
                    feature_tag=payload.feature_tag,
                    status_code=response.status_code,
                )
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            ""traject.budget.webhook.failed",
            feature_tag=payload.feature_tag,
            error=str(exc),
        )
