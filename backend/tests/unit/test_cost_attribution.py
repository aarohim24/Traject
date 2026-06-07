"""Unit tests for axon_backend.services.cost_attribution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from axon_backend.services.cost_attribution import get_attribution, materialize_hourly


def _mock_db_no_rows() -> MagicMock:
    """Return a mock session whose execute returns an empty result."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_result.scalar.return_value = Decimal("0")
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    return db


class TestMaterializeHourly:
    """Tests for materialize_hourly()."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_spans(self) -> None:
        """Returns 0 when the DB query returns no rows."""
        db = _mock_db_no_rows()
        hour = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        result = await materialize_hourly(db, hour)
        assert result == 0

    @pytest.mark.asyncio
    async def test_idempotent_returns_same_count(self) -> None:
        """Two calls with the same hour return the same count."""
        db = _mock_db_no_rows()
        hour = datetime(2025, 1, 1, 11, 0, 0, tzinfo=UTC)
        result1 = await materialize_hourly(db, hour)
        result2 = await materialize_hourly(db, hour)
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_naive_datetime_handled(self) -> None:
        """materialize_hourly handles naive datetimes without error."""
        db = _mock_db_no_rows()
        # Naive datetime — should be treated as UTC
        hour = datetime(2025, 1, 1, 12, 0, 0)
        result = await materialize_hourly(db, hour)
        assert result == 0


class TestGetAttribution:
    """Tests for get_attribution()."""

    @pytest.mark.asyncio
    async def test_returns_empty_breakdown_no_data(self) -> None:
        """Returns empty breakdown and zero totals when no rows exist."""
        db = _mock_db_no_rows()
        now = datetime.now(tz=UTC)
        result = await get_attribution(
            db,
            feature_tag=None,
            from_ts=now - timedelta(days=1),
            to_ts=now,
            group_by="feature_tag",
        )
        assert result.breakdown == []
        assert result.total_tokens == 0

    @pytest.mark.asyncio
    async def test_group_by_model_works(self) -> None:
        """group_by='model' executes without error on empty data."""
        db = _mock_db_no_rows()
        now = datetime.now(tz=UTC)
        result = await get_attribution(
            db,
            feature_tag=None,
            from_ts=now - timedelta(days=1),
            to_ts=now,
            group_by="model",
        )
        assert isinstance(result.breakdown, list)

    @pytest.mark.asyncio
    async def test_group_by_provider_works(self) -> None:
        """group_by='provider' executes without error on empty data."""
        db = _mock_db_no_rows()
        now = datetime.now(tz=UTC)
        result = await get_attribution(
            db,
            feature_tag=None,
            from_ts=now - timedelta(days=1),
            to_ts=now,
            group_by="provider",
        )
        assert isinstance(result.breakdown, list)

    @pytest.mark.asyncio
    async def test_feature_tag_filter_applied(self) -> None:
        """Passing feature_tag restricts the query (no error raised)."""
        db = _mock_db_no_rows()
        now = datetime.now(tz=UTC)
        result = await get_attribution(
            db,
            feature_tag="my-feature",
            from_ts=now - timedelta(days=1),
            to_ts=now,
            group_by="feature_tag",
        )
        assert result.total_tokens == 0
