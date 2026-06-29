"""SQLAlchemy ORM model for budget control records.

Maps the ``budget_controls`` table.  Each row represents a spending budget
configured for a single ``feature_tag``, including the alert threshold,
hard-stop flag, and optional webhook URL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Index, Numeric, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from traject_backend.models.base import Base
from traject_backend.models.tenant import DEFAULT_TENANT_ID


class BudgetControlRecord(Base):
    """Budget configuration and enforcement settings for a feature tag.

    Attributes:
        id: UUID primary key.
        feature_tag: The feature tag this budget applies to (unique).
        period: Rolling time window: ``"daily"``, ``"weekly"``, or
            ``"monthly"``.
        budget_usd: Maximum allowed spend for the period.
        alert_threshold_pct: Fraction of ``budget_usd`` at which a
            ``WARNING`` alert fires (e.g. ``0.8`` = 80 %).
        hard_stop: When ``True``, callers should block LLM calls once
            ``EXHAUSTED`` status is reached.
        alert_webhook_url: Optional HTTP endpoint that receives a POST
            payload when the budget threshold is crossed.
        created_at: Record creation timestamp.
        updated_at: Record last-modification timestamp.
    """

    __tablename__ = "budget_controls"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        default=DEFAULT_TENANT_ID,
        server_default=text("'00000000-0000-0000-0000-000000000000'"),
    )
    feature_tag: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False)
    budget_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    alert_threshold_pct: Mapped[float] = mapped_column(nullable=False, server_default=text("0.8"))
    hard_stop: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    alert_webhook_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        # Budgets are unique per (tenant, feature_tag), not globally by tag.
        UniqueConstraint("tenant_id", "feature_tag", name="uq_budget_tenant_feature"),
        Index("ix_budget_tenant_id", "tenant_id"),
    )
