"""Public benchmark registry API endpoints.

Provides ``POST /v1/benchmarks/submit`` (unauthenticated, HTTP 201) for
community telemetry submissions, and ``GET /v1/benchmarks`` (unauthenticated)
for retrieving the public leaderboard of submitted benchmark records ordered
by ``submitted_at`` descending.

No API key is required for either endpoint — the benchmark registry is a
public resource.  Submissions are validated against the ``BenchmarkSubmitRequest``
schema and persisted as :class:`~axon_backend.models.benchmark.BenchmarkSubmissionRecord`
rows.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_backend.core.database import get_db
from axon_backend.models.benchmark import BenchmarkSubmissionRecord

_log = structlog.get_logger(__name__)

benchmarks_router = APIRouter(tags=["benchmarks"])


class BenchmarkSubmitRequest(BaseModel):
    """Request body for ``POST /v1/benchmarks/submit``.

    Contains only aggregate, non-personally-identifiable metrics collected
    from an opted-in :class:`~axon.core.telemetry_reporter.TelemetryReporter`
    instance.  No prompt content, user IDs, API keys, or host identifiers
    are accepted or stored.

    Attributes:
        sdk_version: Axon SDK version string that produced the submission.
        python_version: CPython version string on the submitting host.
        sample_count: Number of inference spans included in the benchmark run.
        p50_cost_usd: Median per-call cost in USD (Decimal-serialised string).
        p95_cost_usd: 95th-percentile per-call cost in USD (Decimal-serialised
            string).
        p50_compression_ratio: Median compression ratio across the sample set.
        p95_compression_ratio: 95th-percentile compression ratio.
        avg_routing_accuracy: Mean routing accuracy across the sample set.
    """

    sdk_version: str
    python_version: str
    sample_count: int
    p50_cost_usd: str
    p95_cost_usd: str
    p50_compression_ratio: float
    p95_compression_ratio: float
    avg_routing_accuracy: float


class BenchmarkRecord(BaseModel):
    """Response model representing a persisted benchmark submission.

    Returned by both ``POST /v1/benchmarks/submit`` and entries in the
    ``GET /v1/benchmarks`` list.

    Attributes:
        id: UUID primary key assigned server-side.
        sdk_version: Axon SDK version string.
        python_version: CPython version string.
        sample_count: Number of inference spans in the run.
        p50_cost_usd: Median per-call cost in USD as a string.
        p95_cost_usd: 95th-percentile cost in USD as a string.
        p50_compression_ratio: Median compression ratio.
        p95_compression_ratio: 95th-percentile compression ratio.
        avg_routing_accuracy: Mean routing accuracy.
        submitted_at: UTC timestamp when the record was persisted.
    """

    id: uuid.UUID
    sdk_version: str
    python_version: str
    sample_count: int
    p50_cost_usd: str
    p95_cost_usd: str
    p50_compression_ratio: float
    p95_compression_ratio: float
    avg_routing_accuracy: float
    submitted_at: datetime

    model_config = {"from_attributes": True}


@benchmarks_router.post(
    "/submit",
    response_model=BenchmarkRecord,
    status_code=201,
)
async def submit_benchmark(
    request: BenchmarkSubmitRequest,
    db: AsyncSession = Depends(get_db),
) -> BenchmarkRecord:
    """Persist a community benchmark submission.

    This endpoint requires no authentication.  The submitted payload is
    validated and stored as a :class:`~axon_backend.models.benchmark.BenchmarkSubmissionRecord`.
    The server assigns the ``id`` (UUID) and ``submitted_at`` (UTC timestamp).

    Args:
        request: Validated benchmark metrics payload.
        db: Injected async database session.

    Returns:
        The persisted :class:`BenchmarkRecord` including server-assigned fields.
    """
    record = BenchmarkSubmissionRecord(
        sdk_version=request.sdk_version,
        python_version=request.python_version,
        sample_count=request.sample_count,
        p50_cost_usd=request.p50_cost_usd,
        p95_cost_usd=request.p95_cost_usd,
        p50_compression_ratio=request.p50_compression_ratio,
        p95_compression_ratio=request.p95_compression_ratio,
        avg_routing_accuracy=request.avg_routing_accuracy,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    _log.info(
        "axon.benchmarks.submitted",
        id=str(record.id),
        sdk_version=record.sdk_version,
        sample_count=record.sample_count,
    )

    return BenchmarkRecord.model_validate(record)


@benchmarks_router.get(
    "",
    response_model=list[BenchmarkRecord],
)
async def list_benchmarks(
    limit: int = Query(50, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[BenchmarkRecord]:
    """Return benchmark submissions ordered by submission time, newest first.

    This endpoint requires no authentication.

    Args:
        limit: Maximum number of records to return (default 50, max 500).
        db: Injected async database session.

    Returns:
        List of :class:`BenchmarkRecord` objects ordered by ``submitted_at``
        descending.
    """
    stmt = (
        select(BenchmarkSubmissionRecord)
        .order_by(BenchmarkSubmissionRecord.submitted_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [BenchmarkRecord.model_validate(row) for row in rows]
