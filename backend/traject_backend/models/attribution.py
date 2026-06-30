"""SQLAlchemy ORM model for hourly cost attribution records.

Maps the ``cost_attribution`` table, which is populated by
:func:`~traject_backend.services.cost_attribution.materialize_hourly` by
aggregating ``inference_spans`` rows into hour-bucket summaries.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Index, Numeric, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from traject_backend.models.base import Base
from traject_backend.models.tenant import DEFAULT_TENANT_ID


class CostAttributionRecord(Base):
    """Hourly cost attribution record materialised from inference spans.

    Each row represents one ``(feature_tag, provider, model)`` combination
    for a single hour bucket.  The unique constraint prevents duplicate rows
    for the same combination.

    Attributes:
        id: UUID primary key.
        feature_tag: Cost-attribution grouping label.
        hour_bucket: Start of the one-hour window this row covers.
        provider: LLM provider name.
        model: Model identifier.
        total_input_tokens: Sum of input tokens across all spans in bucket.
        total_output_tokens: Sum of output tokens.
        total_cached_tokens: Sum of cached tokens.
        total_cost_usd: Total USD cost for this bucket.
        total_tokens_saved: Total tokens saved by compression.
        cost_saved_compression_usd: USD value of compression savings.
        cost_saved_cache_usd: USD value of cache hit savings.
        call_count: Number of spans in this bucket.
        cache_hit_count: Number of spans with ``cache_hit=True``.
        p50_latency_ms: Median duration_ms across spans.
        p95_latency_ms: 95th-percentile duration_ms across spans.
        created_at: Insertion timestamp.
    """

    __tablename__ = "cost_attribution"

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
    hour_bucket: Mapped[datetime] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    total_output_tokens: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    total_cached_tokens: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, server_default=text("0")
    )
    total_tokens_saved: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    cost_saved_compression_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, server_default=text("0")
    )
    cost_saved_cache_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 8), nullable=False, server_default=text("0")
    )
    call_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    cache_hit_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    p50_latency_ms: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    p95_latency_ms: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "feature_tag",
            "hour_bucket",
            "provider",
            "model",
            name="uq_attribution_feature_hour_provider_model",
        ),
        Index("ix_attribution_hour_bucket", "hour_bucket"),
        Index("ix_attribution_feature_tag", "feature_tag"),
        Index("ix_attribution_tenant_hour", "tenant_id", "hour_bucket"),
    )
