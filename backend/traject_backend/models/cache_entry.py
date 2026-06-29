"""SQLAlchemy ORM model for semantic cache entries.

Maps the ``cache_entries`` table which uses the ``pgvector`` extension to
store 384-dimensional sentence embeddings produced by the
``all-MiniLM-L6-v2`` model.  Cosine similarity search is performed via
the ``<=>`` operator provided by pgvector.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, Numeric, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from traject_backend.models.base import Base
from traject_backend.models.tenant import DEFAULT_TENANT_ID


class CacheEntryRecord(Base):
    """Semantic cache entry with a pgvector embedding column.

    Attributes:
        id: UUID primary key.
        prompt_hash: SHA-256 hex digest of the normalised prompt (unique).
        embedding: 384-dimensional sentence embedding for cosine similarity
            search via the pgvector ``<=>`` operator.
        response_preview: First 200 characters of the cached LLM response.
        model: Model identifier used for the original call.
        feature_tag: Cost-attribution label for the original call.
        similarity_threshold: Minimum similarity required for a cache hit
            (stored for reference; enforcement is in the service layer).
        created_at: Insertion timestamp.
        expires_at: Optional expiry timestamp; ``None`` means never expires.
        last_hit_at: Timestamp of the most recent cache hit.
        hit_count: Total number of times this entry has been served.
        cost_saved_usd: Cumulative USD cost saved by serving this entry.
    """

    __tablename__ = "cache_entries"

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
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)  # noqa: ANN401
    response_preview: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    feature_tag: Mapped[str] = mapped_column(String, nullable=False)
    similarity_threshold: Mapped[float] = mapped_column(
        nullable=False, server_default=text("0.92")
    )
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_hit_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=text("now()")
    )
    hit_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    cost_saved_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, server_default=text("0")
    )

    __table_args__ = (
        # Cache entries are unique per (tenant, prompt_hash).
        UniqueConstraint(
            "tenant_id", "prompt_hash", name="uq_cache_tenant_prompt_hash"
        ),
        Index("ix_cache_entries_prompt_hash", "prompt_hash"),
        Index("ix_cache_entries_feature_tag", "feature_tag"),
        Index("ix_cache_entries_expires_at", "expires_at"),
        Index("ix_cache_entries_tenant_id", "tenant_id"),
        # HNSW ANN index for cosine similarity — without this every lookup is a
        # full sequential scan (the audit's C4-backend finding). Scoped vector
        # search filters by tenant_id first, then ranks by distance.
        Index(
            "ix_cache_entries_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
