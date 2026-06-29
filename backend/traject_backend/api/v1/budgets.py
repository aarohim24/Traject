"""Budget control CRUD and status API endpoints.

Provides upsert, read, list, and delete operations for budget configurations,
plus live spend-status queries against the Redis/DB budget enforcer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import uuid as _uuid

from traject_backend.core.auth import CurrentTenant
from traject_backend.core.database import get_db
from traject_backend.core.redis_client import get_redis
from traject_backend.models.budget import BudgetControlRecord
from traject_backend.services.budget_enforcer import check_budget

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["budgets"])


class BudgetControlPayload(BaseModel):
    """Request body for creating or updating a budget.

    Attributes:
        period: Rolling period — ``"daily"``, ``"weekly"``, or ``"monthly"``.
        budget_usd: Maximum spend allowed within the period.
        alert_threshold_pct: Fraction at which a warning fires (default 0.8).
        hard_stop: Whether to block calls when exhausted (default False).
        alert_webhook_url: Optional HTTP endpoint for alert POSTs.
    """

    period: str = Field(pattern="^(daily|weekly|monthly)$")
    budget_usd: Decimal
    alert_threshold_pct: float = 0.8
    hard_stop: bool = False
    alert_webhook_url: str | None = None


class BudgetStatusResponse(BaseModel):
    """Live budget status for a feature tag.

    Attributes:
        feature_tag: The feature tag this budget applies to.
        period: The configured rolling period.
        budget_usd: The configured budget limit.
        spent_usd: Current spend within the active period.
        remaining_usd: Remaining budget (may be negative when exhausted).
        pct_used: Fraction of budget consumed (0.0–1.0+).
        status: ``"ok"``, ``"warning"``, or ``"exhausted"``.
    """

    feature_tag: str
    period: str
    budget_usd: Decimal
    spent_usd: Decimal
    remaining_usd: Decimal
    pct_used: float
    status: str


async def _build_status_response(
    db: AsyncSession, record: BudgetControlRecord, tenant_id: _uuid.UUID
) -> BudgetStatusResponse:
    """Build a live BudgetStatusResponse for a budget record.

    Args:
        db: An active async SQLAlchemy session.
        record: The BudgetControlRecord to build status for.
        tenant_id: The owning tenant (scopes the spend computation).

    Returns:
        A BudgetStatusResponse with live spend data.
    """
    redis = get_redis()
    status = await check_budget(record.feature_tag, db, redis, tenant_id=tenant_id)

    # Get actual spend from Redis cache or compute
    redis_key = f"traject:budget:{record.feature_tag}"
    cached = await redis.get(redis_key)
    spent = Decimal(str(cached)) if cached else Decimal("0")

    budget = record.budget_usd
    remaining = budget - spent
    pct_used = float(spent / budget) if budget else 0.0

    return BudgetStatusResponse(
        feature_tag=record.feature_tag,
        period=record.period,
        budget_usd=budget,
        spent_usd=spent,
        remaining_usd=remaining,
        pct_used=pct_used,
        status=status.value,
    )


@router.put(
    "/budgets/{feature_tag}",
    response_model=BudgetControlPayload,
)
async def upsert_budget(
    feature_tag: str,
    payload: BudgetControlPayload,
    tenant_id: CurrentTenant,
    db: AsyncSession = Depends(get_db),
) -> BudgetControlPayload:
    """Create or update a budget for a feature tag.

    Args:
        feature_tag: The feature tag to configure a budget for.
        payload: Budget configuration.
        db: Injected async database session.

    Returns:
        The upserted budget configuration.
    """
    now = datetime.utcnow()
    stmt = pg_insert(BudgetControlRecord).values(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        feature_tag=feature_tag,
        period=payload.period,
        budget_usd=payload.budget_usd,
        alert_threshold_pct=payload.alert_threshold_pct,
        hard_stop=payload.hard_stop,
        alert_webhook_url=payload.alert_webhook_url,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "feature_tag"],
        set_={
            "period": payload.period,
            "budget_usd": payload.budget_usd,
            "alert_threshold_pct": payload.alert_threshold_pct,
            "hard_stop": payload.hard_stop,
            "alert_webhook_url": payload.alert_webhook_url,
            "updated_at": now,
        },
    )
    await db.execute(stmt)
    await db.commit()
    return payload


@router.get(
    "/budgets/{feature_tag}",
    response_model=BudgetStatusResponse,
)
async def get_budget_status(
    feature_tag: str,
    tenant_id: CurrentTenant,
    db: AsyncSession = Depends(get_db),
) -> BudgetStatusResponse:
    """Return live budget status for a feature tag.

    Args:
        feature_tag: The feature tag to query.
        db: Injected async database session.

    Returns:
        BudgetStatusResponse with current spend and status.

    Raises:
        HTTPException: 404 when no budget is configured for the feature tag.
    """
    result = await db.execute(
        select(BudgetControlRecord).where(
            BudgetControlRecord.tenant_id == tenant_id,
            BudgetControlRecord.feature_tag == feature_tag,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No budget configured for feature_tag '{feature_tag}'",
        )
    return await _build_status_response(db, record, tenant_id)


@router.get(
    "/budgets",
    response_model=list[BudgetStatusResponse],
)
async def list_budgets(
    tenant_id: CurrentTenant,
    db: AsyncSession = Depends(get_db),
) -> list[BudgetStatusResponse]:
    """Return live status for all configured budgets.

    Args:
        tenant_id: The authenticated caller's tenant.
        db: Injected async database session.

    Returns:
        List of BudgetStatusResponse, one per configured feature tag.
    """
    result = await db.execute(
        select(BudgetControlRecord).where(
            BudgetControlRecord.tenant_id == tenant_id
        )
    )
    records = result.scalars().all()
    return [await _build_status_response(db, r, tenant_id) for r in records]


@router.delete(
    "/budgets/{feature_tag}",
    status_code=204,
)
async def delete_budget(
    feature_tag: str,
    tenant_id: CurrentTenant,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete the budget configuration for a feature tag.

    Also removes the Redis spend counter for this feature tag.

    Args:
        feature_tag: The feature tag whose budget should be removed.
        db: Injected async database session.

    Raises:
        HTTPException: 404 when no budget exists for this feature tag.
    """
    result = await db.execute(
        select(BudgetControlRecord).where(
            BudgetControlRecord.tenant_id == tenant_id,
            BudgetControlRecord.feature_tag == feature_tag,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No budget configured for feature_tag '{feature_tag}'",
        )
    await db.delete(record)
    await db.commit()

    # Invalidate Redis cache
    redis = get_redis()
    await redis.delete(f"traject:budget:{feature_tag}")
