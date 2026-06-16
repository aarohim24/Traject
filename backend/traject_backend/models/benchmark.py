"""SQLAlchemy ORM model for benchmark submission records.

Maps the ``benchmark_submissions`` PostgreSQL table created in migration 0003.
Stores aggregate, anonymised performance metrics submitted by consenting users
via :class:`~"traject.core.telemetry_reporter.TelemetryReporter` and persisted by
the public ``POST /v1/benchmarks/submit`` endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from traject_backend.models.base import Base


class BenchmarkSubmissionRecord(Base):
    """Persisted record of a single community benchmark submission.

    Each row represents one call to ``POST /v1/benchmarks/submit`` and
    contains only aggregate, non-personally-identifiable metrics.  No prompt
    content, user IDs, API keys, or host identifiers are stored.

    Attributes:
        id: UUID primary key, generated server-side by ``gen_random_uuid()``.
        sdk_version: Axon SDK version string that produced the submission.
        python_version: CPython version string on the submitting host.
        sample_count: Number of inference spans included in the benchmark run.
        p50_cost_usd: Median per-call cost in USD (Decimal-serialised string).
        p95_cost_usd: 95th-percentile per-call cost in USD (Decimal-serialised
            string).
        p50_compression_ratio: Median compression ratio across the sample set.
        p95_compression_ratio: 95th-percentile compression ratio.
        avg_routing_accuracy: Mean routing accuracy across the sample set.
        submitted_at: UTC timestamp of submission, set server-side by
            ``now()``.
    """

    __tablename__ = "benchmark_submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    sdk_version: Mapped[str] = mapped_column(String, nullable=False)
    python_version: Mapped[str] = mapped_column(String, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    p50_cost_usd: Mapped[str] = mapped_column(String, nullable=False)
    p95_cost_usd: Mapped[str] = mapped_column(String, nullable=False)
    p50_compression_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    p95_compression_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    avg_routing_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_benchmarks_submitted_at", "submitted_at"),
    )
