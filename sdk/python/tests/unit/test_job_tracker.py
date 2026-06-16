"""Unit tests for axon.batch.job_tracker.

Covers :class:`~axon.batch.job_tracker.JobTracker` status validation,
list_pending filtering, and the not-found path for ``get``.

Validates: Requirements 20.3
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from traject.batch.batch_router import BatchJobStatus
from traject.batch.job_tracker import BatchJobORM, JobTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_db_with_row(row: BatchJobORM | None) -> AsyncMock:
    """Build a mock :class:`~sqlalchemy.ext.asyncio.AsyncSession`.

    The mock's ``execute()`` returns a result whose
    ``scalars().first()`` yields ``row``.

    Args:
        row: The ORM row to return, or ``None`` to simulate not-found.

    Returns:
        An :class:`~unittest.mock.AsyncMock` that mimics ``AsyncSession``.
    """
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.first.return_value = row
    db.execute = AsyncMock(return_value=result_mock)
    db.flush = AsyncMock()
    return db


def _make_mock_db_with_rows(rows: list[BatchJobORM]) -> AsyncMock:
    """Build a mock ``AsyncSession`` whose ``scalars().all()`` returns ``rows``.

    Args:
        rows: List of ORM rows to return from the query result.

    Returns:
        An :class:`~unittest.mock.AsyncMock` that mimics ``AsyncSession``.
    """
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result_mock)
    return db


def _make_orm_row(
    job_id: str = "job-001",
    provider: str = "openai",
    status: str = "pending",
    span_count: int = 5,
) -> BatchJobORM:
    """Construct a minimal :class:`BatchJobORM` instance for testing.

    Args:
        job_id: Provider-assigned job identifier.
        provider: Provider name string.
        status: Status string value.
        span_count: Number of spans in the batch.

    Returns:
        A :class:`BatchJobORM` with the given field values.
    """
    row = BatchJobORM()
    row.job_id = job_id
    row.provider = provider
    row.status = status
    row.submitted_at = datetime.now(tz=UTC)
    row.span_count = span_count
    row.estimated_completion_at = None
    return row


# ---------------------------------------------------------------------------
# Task 20.3 — Unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_status_raises_value_error_for_invalid_status() -> None:
    """update_status() raises ValueError for an unrecognised status string.

    ``"invalid_status"`` is not a member of :class:`BatchJobStatus`, so a
    :class:`ValueError` with a descriptive message must be raised before any
    database query is executed.
    """
    tracker = JobTracker()
    db = AsyncMock()

    with pytest.raises(ValueError, match="Invalid batch job status"):
        await tracker.update_status(db, "job_123", "invalid_status")


@pytest.mark.asyncio
async def test_update_status_raises_value_error_for_empty_string() -> None:
    """update_status() raises ValueError for an empty string status.

    An empty string ``""`` is not a valid :class:`BatchJobStatus` value.
    """
    tracker = JobTracker()
    db = AsyncMock()

    with pytest.raises(ValueError, match="Invalid batch job status"):
        await tracker.update_status(db, "job_123", "")


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_status", [s.value for s in BatchJobStatus])
async def test_update_status_accepts_all_valid_statuses(valid_status: str) -> None:
    """update_status() does not raise for any valid BatchJobStatus value.

    All five recognised status strings — ``"pending"``, ``"in_progress"``,
    ``"completed"``, ``"failed"``, and ``"expired"`` — must be accepted
    without raising an exception.

    Args:
        valid_status: A valid :class:`BatchJobStatus` string value (parametrized).
    """
    tracker = JobTracker()
    row = _make_orm_row(job_id="job-valid", status="pending")
    db = _make_mock_db_with_row(row)

    # Must not raise for any valid status
    await tracker.update_status(db, "job-valid", valid_status)


@pytest.mark.asyncio
async def test_list_pending_returns_pending_and_in_progress() -> None:
    """list_pending() returns all PENDING and IN_PROGRESS records.

    Given a mocked database result containing one PENDING and one IN_PROGRESS
    row, both must appear in the returned list.
    """
    tracker = JobTracker()

    pending_row = _make_orm_row(job_id="job-p", status=BatchJobStatus.PENDING.value)
    in_progress_row = _make_orm_row(
        job_id="job-ip", status=BatchJobStatus.IN_PROGRESS.value
    )
    db = _make_mock_db_with_rows([pending_row, in_progress_row])

    results = await tracker.list_pending(db)

    assert len(results) == 2
    job_ids = {r.job_id for r in results}
    assert "job-p" in job_ids
    assert "job-ip" in job_ids


@pytest.mark.asyncio
async def test_get_returns_none_when_not_found() -> None:
    """get() returns None when no row matches the given job_id.

    When the database returns an empty result set (``scalars().first()``
    returns ``None``), :meth:`JobTracker.get` must return ``None`` without
    raising.
    """
    tracker = JobTracker()
    db = _make_mock_db_with_row(None)

    result = await tracker.get(db, "nonexistent-job")

    assert result is None
