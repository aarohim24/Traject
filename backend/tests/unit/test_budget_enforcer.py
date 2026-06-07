"""Unit tests for axon_backend.services.budget_enforcer."""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from axon_backend.services.budget_enforcer import BudgetAlertPayload, check_budget, fire_webhook
from axon_backend.services.span_ingestion import BudgetStatus


class TestCheckBudget:
    """Tests for check_budget()."""

    @pytest.mark.asyncio
    async def test_returns_ok_when_no_budget_configured(
        self, db_session, redis_mock
    ) -> None:
        """Returns OK when no budget row exists for the feature tag."""
        status = await check_budget("nonexistent-tag", db_session, redis_mock)
        assert status == BudgetStatus.OK

    @pytest.mark.asyncio
    async def test_returns_ok_on_db_error(self, db_session, redis_mock) -> None:
        """Returns OK (fail open) when the database raises an exception."""
        with patch(
            "axon_backend.services.budget_enforcer._load_budget",
            new=AsyncMock(side_effect=RuntimeError("DB down")),
        ):
            status = await check_budget("any-tag", db_session, redis_mock)
        assert status == BudgetStatus.OK

    @pytest.mark.asyncio
    async def test_uses_redis_fast_path(self, db_session, redis_mock) -> None:
        """When Redis has a cached value, DB is not queried for spend."""
        # Insert a budget record
        import uuid  # noqa: PLC0415
        from datetime import datetime  # noqa: PLC0415

        from axon_backend.models.budget import BudgetControlRecord  # noqa: PLC0415

        record = BudgetControlRecord(
            id=uuid.uuid4(),
            feature_tag="cached-tag",
            period="daily",
            budget_usd=Decimal("10.00"),
            alert_threshold_pct=0.8,
            hard_stop=False,
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        db_session.add(record)
        await db_session.flush()

        # Pre-populate Redis with a low spend value
        await redis_mock.set("axon:budget:cached-tag", "1.00")

        status = await check_budget("cached-tag", db_session, redis_mock)
        assert status == BudgetStatus.OK

    @pytest.mark.asyncio
    async def test_exhausted_when_over_budget(self, db_session, redis_mock) -> None:
        """Returns EXHAUSTED when cached spend >= budget_usd."""
        import uuid  # noqa: PLC0415
        from datetime import datetime  # noqa: PLC0415

        from axon_backend.models.budget import BudgetControlRecord  # noqa: PLC0415

        record = BudgetControlRecord(
            id=uuid.uuid4(),
            feature_tag="exhausted-tag",
            period="daily",
            budget_usd=Decimal("5.00"),
            alert_threshold_pct=0.8,
            hard_stop=True,
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        db_session.add(record)
        await db_session.flush()

        # Spend equals the budget
        await redis_mock.set("axon:budget:exhausted-tag", "5.00")

        status = await check_budget("exhausted-tag", db_session, redis_mock)
        assert status == BudgetStatus.EXHAUSTED

    @pytest.mark.asyncio
    async def test_warning_between_threshold_and_limit(
        self, db_session, redis_mock
    ) -> None:
        """Returns WARNING when spend is between threshold and budget limit."""
        import uuid  # noqa: PLC0415
        from datetime import datetime  # noqa: PLC0415

        from axon_backend.models.budget import BudgetControlRecord  # noqa: PLC0415

        record = BudgetControlRecord(
            id=uuid.uuid4(),
            feature_tag="warning-tag",
            period="daily",
            budget_usd=Decimal("10.00"),
            alert_threshold_pct=0.8,
            hard_stop=False,
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        db_session.add(record)
        await db_session.flush()

        # 85% of budget — above 80% threshold, below 100%
        await redis_mock.set("axon:budget:warning-tag", "8.50")

        status = await check_budget("warning-tag", db_session, redis_mock)
        assert status == BudgetStatus.WARNING


class TestFireWebhook:
    """Tests for fire_webhook()."""

    @pytest.mark.asyncio
    async def test_does_not_raise_on_timeout(self) -> None:
        """fire_webhook never raises even when the HTTP call times out."""
        payload = BudgetAlertPayload(
            feature_tag="test",
            budget_usd=Decimal("10.00"),
            spent_usd=Decimal("10.00"),
            pct_used=1.0,
            status="exhausted",
            timestamp="2025-01-01T00:00:00Z",
        )
        with patch("axon_backend.services.budget_enforcer.httpx.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(side_effect=TimeoutError("timeout"))
            mock_cls.return_value = mock_instance

            # Must not raise
            await fire_webhook("http://example.com/webhook", payload)

    @pytest.mark.asyncio
    async def test_does_not_raise_on_5xx_response(self) -> None:
        """fire_webhook never raises even when the server returns 5xx."""
        payload = BudgetAlertPayload(
            feature_tag="test",
            budget_usd=Decimal("10.00"),
            spent_usd=Decimal("9.50"),
            pct_used=0.95,
            status="warning",
            timestamp="2025-01-01T00:00:00Z",
        )
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.is_success = False

        with patch("axon_backend.services.budget_enforcer.httpx.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_cls.return_value = mock_instance

            # Must not raise
            await fire_webhook("http://example.com/webhook", payload)
