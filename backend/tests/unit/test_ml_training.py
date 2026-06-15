"""Unit tests for axon_backend.services.ml_training.MLTrainingService.

Validates that:
- ``train()`` raises ``InsufficientDataError`` on an empty database.
- ``run_weekly_training_job()`` catches all exceptions and never re-raises.

**Validates: Requirements 5.5, 5.6**
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from axon.exceptions import InsufficientDataError
from axon_backend.services.ml_training import MLTrainingService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_db_empty() -> AsyncMock:
    """Return a mock AsyncSession whose execute() returns an empty result set.

    Simulates a database with no labeled InferenceSpanRecord rows.

    Returns:
        An ``AsyncMock`` that mimics ``AsyncSession`` with
        ``session.execute()`` → ``result.scalars().all()`` → ``[]``.
    """
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# Task 8.1 — train() raises InsufficientDataError on empty DB
# ---------------------------------------------------------------------------


class TestMLTrainingServiceTrain:
    """Tests for MLTrainingService.train()."""

    @pytest.mark.asyncio
    async def test_train_raises_insufficient_data_error_on_empty_db(self) -> None:
        """train() raises InsufficientDataError when DB returns no labeled rows.

        **Validates: Requirements 5.5**
        """
        db = _make_mock_db_empty()
        service = MLTrainingService(artifact_path="/tmp/test_axon_artifact.json")

        with pytest.raises(InsufficientDataError):
            await service.train(db)

    @pytest.mark.asyncio
    async def test_train_calls_db_execute_once(self) -> None:
        """train() issues exactly one SELECT query against the database.

        **Validates: Requirements 5.5**
        """
        db = _make_mock_db_empty()
        service = MLTrainingService(artifact_path="/tmp/test_axon_artifact.json")

        with pytest.raises(InsufficientDataError):
            await service.train(db)

        # Should have executed exactly one query
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_train_insufficient_data_error_has_descriptive_message(
        self,
    ) -> None:
        """InsufficientDataError raised by train() carries a descriptive message.

        **Validates: Requirements 5.5**
        """
        db = _make_mock_db_empty()
        service = MLTrainingService(artifact_path="/tmp/test_axon_artifact.json")

        with pytest.raises(InsufficientDataError) as exc_info:
            await service.train(db)

        message = str(exc_info.value)
        # The message must explain what went wrong and what to do
        assert len(message) > 10
        assert "routing_decision" in message.lower() or "labeled" in message.lower()


# ---------------------------------------------------------------------------
# Task 8.2 — run_weekly_training_job() never re-raises
# ---------------------------------------------------------------------------


class TestMLTrainingServiceWeeklyJob:
    """Tests for MLTrainingService.run_weekly_training_job()."""

    @pytest.mark.asyncio
    async def test_weekly_job_does_not_reraise_when_train_raises(self) -> None:
        """run_weekly_training_job() catches train() exceptions and never re-raises.

        The scheduler must never be disrupted by training failures. Even when
        train() raises InsufficientDataError, the job must complete silently.

        **Validates: Requirements 5.6**
        """
        db = _make_mock_db_empty()
        service = MLTrainingService(artifact_path="/tmp/test_axon_artifact.json")

        # Must NOT raise — this is the key assertion
        await service.run_weekly_training_job(db)

    @pytest.mark.asyncio
    async def test_weekly_job_does_not_reraise_on_arbitrary_exception(self) -> None:
        """run_weekly_training_job() suppresses any exception from train().

        **Validates: Requirements 5.6**
        """
        db = AsyncMock()
        service = MLTrainingService(artifact_path="/tmp/test_axon_artifact.json")

        # Patch train() to raise an arbitrary unexpected error
        with patch.object(
            service,
            "train",
            new=AsyncMock(side_effect=RuntimeError("unexpected database failure")),
        ):
            # Must NOT raise
            await service.run_weekly_training_job(db)

    @pytest.mark.asyncio
    async def test_weekly_job_does_not_reraise_on_os_error(self) -> None:
        """run_weekly_training_job() suppresses OSError from _save_artifact().

        If the artifact cannot be written (e.g. permission denied), the job
        must still not propagate the exception to the scheduler.

        **Validates: Requirements 5.6**
        """
        db = AsyncMock()
        service = MLTrainingService(artifact_path="/tmp/test_axon_artifact.json")

        with patch.object(
            service,
            "train",
            new=AsyncMock(side_effect=OSError("disk full")),
        ):
            # Must NOT raise
            await service.run_weekly_training_job(db)

    @pytest.mark.asyncio
    async def test_weekly_job_insufficient_data_error_is_swallowed(self) -> None:
        """run_weekly_training_job() swallows InsufficientDataError specifically.

        InsufficientDataError is the most common expected failure mode during
        early deployment (before enough spans are collected), so it must be
        silently absorbed rather than crashing the scheduler.

        **Validates: Requirements 5.6**
        """
        db = _make_mock_db_empty()
        service = MLTrainingService(artifact_path="/tmp/test_axon_artifact.json")

        with patch.object(
            service,
            "train",
            new=AsyncMock(side_effect=InsufficientDataError("not enough data")),
        ):
            # Must NOT raise
            await service.run_weekly_training_job(db)
