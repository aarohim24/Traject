"""PostgreSQL persistence layer for batch API job records.

Provides :class:`BatchJobORM` (the SQLAlchemy ORM model for the
``batch_jobs`` table created in migration 0003) and :class:`JobTracker`
(the async service that wraps CRUD operations on that table).

All public methods on :class:`JobTracker` operate on
:class:`~traject.batch.batch_router.BatchJobRecord` dataclasses and convert
internally to/from the ORM layer so that callers never depend on SQLAlchemy
objects directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import Index, String, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from traject.batch.batch_router import BatchJobRecord, BatchJobStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Declarative base — SDK-internal, batch sub-package only
# ---------------------------------------------------------------------------


class _BatchBase(DeclarativeBase):
    """Declarative base for the Traject SDK batch ORM models.

    Intentionally scoped to the ``traject.batch`` sub-package so that the SDK
    does not depend on the backend's ``axon_backend.models.base.Base``.
    """


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------


class BatchJobORM(_BatchBase):
    """SQLAlchemy ORM model for the ``batch_jobs`` table.

    Maps every column defined in migration 0003's ``batch_jobs`` table using
    the SQLAlchemy 2.x ``Mapped`` / ``mapped_column`` API.  No legacy
    ``Column`` usage.

    Attributes:
        id: UUID primary key, generated server-side by ``gen_random_uuid()``.
        job_id: Provider-assigned batch job identifier.  Unique, indexed.
        provider: Provider name — ``"openai"`` or ``"anthropic"``.
        status: Current :class:`~traject.batch.batch_router.BatchJobStatus`
            value stored as a string.
        submitted_at: UTC timestamp of batch submission.
        span_count: Number of spans included in this batch.
        estimated_completion_at: Provider's estimated completion time,
            ``None`` when the provider does not supply an estimate.
        created_at: Row-creation timestamp, set server-side by ``now()``.
    """

    __tablename__ = "batch_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    job_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(nullable=False)
    span_count: Mapped[int] = mapped_column(nullable=False)
    estimated_completion_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_batch_jobs_job_id", "job_id"),
        Index("ix_batch_jobs_status", "status"),
    )


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _orm_to_record(row: BatchJobORM) -> BatchJobRecord:
    """Convert a :class:`BatchJobORM` row to a :class:`BatchJobRecord`.

    Args:
        row: The ORM object to convert.

    Returns:
        A :class:`BatchJobRecord` dataclass populated from the ORM row.
    """
    return BatchJobRecord(
        job_id=row.job_id,
        provider=row.provider,
        status=row.status,
        submitted_at=row.submitted_at,
        span_count=row.span_count,
        estimated_completion_at=row.estimated_completion_at,
    )


def _record_to_orm(record: BatchJobRecord) -> BatchJobORM:
    """Convert a :class:`BatchJobRecord` to a :class:`BatchJobORM` object.

    The ``id`` and ``created_at`` columns are left unset so that PostgreSQL
    populates them via their server-side defaults on ``INSERT``.

    Args:
        record: The dataclass record to convert.

    Returns:
        A :class:`BatchJobORM` instance ready for ``db.add()``.
    """
    return BatchJobORM(
        job_id=record.job_id,
        provider=record.provider,
        status=record.status,
        submitted_at=record.submitted_at,
        span_count=record.span_count,
        estimated_completion_at=record.estimated_completion_at,
    )


# ---------------------------------------------------------------------------
# JobTracker
# ---------------------------------------------------------------------------


class JobTracker:
    """Async PostgreSQL persistence layer for batch API job records.

    All methods accept an :class:`sqlalchemy.ext.asyncio.AsyncSession` as
    their first positional argument (after ``self``) so that the session
    lifetime is managed by the caller — typically a FastAPI dependency or a
    background-job context manager.

    Converts between :class:`BatchJobORM` rows and
    :class:`~traject.batch.batch_router.BatchJobRecord` dataclasses, keeping
    the SQLAlchemy implementation detail fully encapsulated.
    """

    async def create(
        self,
        db: AsyncSession,
        record: BatchJobRecord,
    ) -> BatchJobRecord:
        """Persist a new batch job record to the database.

        Inserts a new row into ``batch_jobs`` and refreshes the ORM object so
        that server-side defaults (``id``, ``created_at``) are populated
        before conversion.

        Args:
            db: Active async SQLAlchemy session.
            record: The :class:`BatchJobRecord` to persist.

        Returns:
            A new :class:`BatchJobRecord` reflecting the persisted row (with
            any server-side default values applied).
        """
        orm_obj = _record_to_orm(record)
        db.add(orm_obj)
        await db.flush()
        await db.refresh(orm_obj)
        _log.info(
            "traject.job_tracker.created",
            job_id=orm_obj.job_id,
            provider=orm_obj.provider,
            status=orm_obj.status,
        )
        return _orm_to_record(orm_obj)

    async def get(
        self,
        db: AsyncSession,
        job_id: str,
    ) -> BatchJobRecord | None:
        """Fetch a batch job record by its provider job ID.

        Args:
            db: Active async SQLAlchemy session.
            job_id: Provider-assigned batch job identifier to look up.

        Returns:
            The :class:`BatchJobRecord` for the given ``job_id``, or
            ``None`` when no matching row exists.
        """
        stmt = select(BatchJobORM).where(BatchJobORM.job_id == job_id)
        result = await db.execute(stmt)
        row: BatchJobORM | None = result.scalars().first()
        if row is None:
            return None
        return _orm_to_record(row)

    async def update_status(
        self,
        db: AsyncSession,
        job_id: str,
        status: str,
    ) -> None:
        """Update the status of an existing batch job.

        Validates that ``status`` is a member of
        :class:`~traject.batch.batch_router.BatchJobStatus` before issuing the
        database update.

        Args:
            db: Active async SQLAlchemy session.
            job_id: Provider-assigned batch job identifier to update.
            status: New status value; must be one of the
                :class:`~traject.batch.batch_router.BatchJobStatus` enum values.

        Raises:
            ValueError: If ``status`` is not a valid
                :class:`~traject.batch.batch_router.BatchJobStatus` value.
        """
        valid_values = {s.value for s in BatchJobStatus}
        if status not in valid_values:
            raise ValueError(
                f"Invalid batch job status {status!r}. "
                f"Must be one of: {sorted(valid_values)}"
            )

        stmt = select(BatchJobORM).where(BatchJobORM.job_id == job_id)
        result = await db.execute(stmt)
        row: BatchJobORM | None = result.scalars().first()
        if row is None:
            _log.warning(
                "traject.job_tracker.update_status.not_found",
                job_id=job_id,
                requested_status=status,
            )
            return

        row.status = status
        await db.flush()
        _log.info(
            "traject.job_tracker.status_updated",
            job_id=job_id,
            new_status=status,
        )

    async def list_pending(
        self,
        db: AsyncSession,
    ) -> list[BatchJobRecord]:
        """Return all batch jobs that are still active (PENDING or IN_PROGRESS).

        Used by :meth:`~traject.batch.batch_router.BatchRouter.poll_and_collect`
        to determine which jobs to poll for status updates.

        Args:
            db: Active async SQLAlchemy session.

        Returns:
            A list of :class:`BatchJobRecord` objects whose ``status`` is
            :attr:`~traject.batch.batch_router.BatchJobStatus.PENDING` or
            :attr:`~traject.batch.batch_router.BatchJobStatus.IN_PROGRESS`.
            Returns an empty list when no such rows exist.
        """
        stmt = select(BatchJobORM).where(
            BatchJobORM.status.in_(
                [BatchJobStatus.PENDING.value, BatchJobStatus.IN_PROGRESS.value]
            )
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return [_orm_to_record(row) for row in rows]
