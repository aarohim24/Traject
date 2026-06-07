"""Unit tests for axon_backend.services.span_ingestion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from axon_backend.services.span_ingestion import BudgetStatus, ingest_spans
from tests.conftest import sample_span_payload, sample_spans_batch


def _make_mock_db() -> MagicMock:
    """Return a mock AsyncSession that records execute/commit calls."""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.commit = AsyncMock()
    return db


class TestIngestSpans:
    """Tests for ingest_spans()."""

    @pytest.mark.asyncio
    async def test_valid_spans_accepted(self, redis_mock) -> None:
        """All valid spans are accepted and the count is correct."""
        db = _make_mock_db()
        spans = sample_spans_batch(5)
        result = await ingest_spans(spans, db, redis_mock)
        assert result.accepted == 5
        assert result.rejected == 0

    @pytest.mark.asyncio
    async def test_future_timestamp_rejected(self, redis_mock) -> None:
        """Spans with timestamps more than 60 seconds in the future are rejected."""
        db = _make_mock_db()
        future_ts = datetime.now(tz=UTC) + timedelta(seconds=120)
        future_span = sample_span_payload(timestamp=future_ts)
        valid_span = sample_span_payload()

        result = await ingest_spans([future_span, valid_span], db, redis_mock)
        assert result.accepted == 1
        assert result.rejected == 1

    @pytest.mark.asyncio
    async def test_all_future_timestamps_no_error(self, redis_mock) -> None:
        """When all spans are in the future, accepted=0 but no error raised."""
        db = _make_mock_db()
        future_ts = datetime.now(tz=UTC) + timedelta(seconds=200)
        spans = [sample_span_payload(timestamp=future_ts) for _ in range(3)]

        result = await ingest_spans(spans, db, redis_mock)
        assert result.accepted == 0
        assert result.rejected == 3

    @pytest.mark.asyncio
    async def test_empty_batch(self, redis_mock) -> None:
        """An empty batch returns accepted=0, rejected=0 without error."""
        db = _make_mock_db()
        result = await ingest_spans([], db, redis_mock)
        assert result.accepted == 0
        assert result.rejected == 0

    @pytest.mark.asyncio
    async def test_webhook_failure_does_not_fail_ingestion(self, redis_mock) -> None:
        """Budget check failure does not prevent successful span ingestion."""
        db = _make_mock_db()
        spans = sample_spans_batch(3)
        # Force the lazy import to resolve, then patch on the module
        import sys  # noqa: PLC0415

        be_mod = sys.modules["axon_backend.services.budget_enforcer"]
        with patch.object(be_mod, "check_budget", new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = await ingest_spans(spans, db, redis_mock)
        assert result.accepted == 3
        assert result.rejected == 0

    @pytest.mark.asyncio
    async def test_span_just_within_future_tolerance(self, redis_mock) -> None:
        """A span exactly 59 seconds in the future is accepted."""
        db = _make_mock_db()
        slightly_future = datetime.now(tz=UTC) + timedelta(seconds=59)
        span = sample_span_payload(timestamp=slightly_future)
        result = await ingest_spans([span], db, redis_mock)
        assert result.accepted == 1
        assert result.rejected == 0

    @pytest.mark.asyncio
    async def test_exactly_at_tolerance_boundary_accepted(self, redis_mock) -> None:
        """A span exactly 60 seconds in the future is accepted (< 61s boundary)."""
        db = _make_mock_db()
        at_boundary = datetime.now(tz=UTC) + timedelta(seconds=60)
        span = sample_span_payload(timestamp=at_boundary)
        result = await ingest_spans([span], db, redis_mock)
        # 60s == cutoff, so it IS accepted (cutoff = now + 60)
        assert result.accepted == 1


class TestBudgetStatus:
    """Tests for the BudgetStatus enum values."""

    def test_ok_value(self) -> None:
        assert BudgetStatus.OK == "ok"

    def test_warning_value(self) -> None:
        assert BudgetStatus.WARNING == "warning"

    def test_exhausted_value(self) -> None:
        assert BudgetStatus.EXHAUSTED == "exhausted"
