"""SQLAlchemy ORM model for persisted LLM inference span records.

Maps the ``inference_spans`` PostgreSQL table.  Every column uses the
SQLAlchemy 2.0 ``Mapped`` / ``mapped_column`` API — no legacy ``Column``
usage anywhere in this module.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from axon_backend.models.base import Base


class InferenceSpanRecord(Base):
    """Persisted record of a single instrumented LLM API call.

    Populated by :func:`~axon_backend.services.span_ingestion.ingest_spans`
    from ``InferenceSpanPayload`` objects sent by the SDK's
    :class:`~axon.backend_client.BackendClient`.

    Attributes:
        id: UUID primary key, generated server-side by ``gen_random_uuid()``.
        trace_id: Trace identifier grouping related spans.
        parent_span_id: Parent span ID, or ``None`` for root spans.
        span_name: Human-readable label (``gen_ai.<provider>.<model>``).
        timestamp: UTC wall-clock time the instrumented call started.
        duration_ms: Elapsed time of the provider call in milliseconds.
        provider: Provider name (``"openai"``, ``"anthropic"``).
        model: Model identifier returned by the provider.
        input_tokens: Prompt tokens billed.
        output_tokens: Completion tokens billed.
        cached_tokens: Tokens served from the provider's prompt cache.
        token_count_method: ``"exact"`` or ``"estimated"``.
        cost_usd: Calculated USD cost, or ``None`` for unknown models.
        feature_tag: Cost-attribution grouping label.
        prompt_hash: SHA-256 hex digest of the normalised prompt.
        artifact_type: Classifier result for the first message.
        compression_applied: Whether live compression modified the context.
        shadow_mode: Whether compression ran in shadow (dry-run) mode.
        pre_compression_tokens: Token count before compression, if any.
        tokens_saved: Tokens eliminated by compression, if any.
        cache_hit: Whether the provider served tokens from its cache.
        environment: Deployment environment label (e.g. ``"production"``).
        created_at: Server-side insertion timestamp.
    """

    __tablename__ = "inference_spans"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String, nullable=True)
    span_name: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    duration_ms: Mapped[int] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(nullable=False)
    output_tokens: Mapped[int] = mapped_column(nullable=False)
    cached_tokens: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    token_count_method: Mapped[str] = mapped_column(String, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    feature_tag: Mapped[str] = mapped_column(String, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String, nullable=False)
    compression_applied: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    shadow_mode: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    pre_compression_tokens: Mapped[int | None] = mapped_column(nullable=True)
    tokens_saved: Mapped[int | None] = mapped_column(nullable=True)
    cache_hit: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    environment: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("ix_spans_trace_id", "trace_id"),
        Index("ix_spans_timestamp", "timestamp"),
        Index("ix_spans_provider", "provider"),
        Index("ix_spans_model", "model"),
        Index("ix_spans_feature_tag", "feature_tag"),
        Index("ix_spans_environment", "environment"),
        Index("ix_spans_feature_tag_timestamp", "feature_tag", "timestamp"),
        Index("ix_spans_environment_timestamp", "environment", "timestamp"),
    )
