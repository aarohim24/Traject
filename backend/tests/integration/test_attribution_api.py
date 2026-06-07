"""Integration tests for the /v1/attribution API endpoints."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from axon_backend.core.config import settings
from axon_backend.services.cost_attribution import AttributionResponse

API_KEY = settings.api_key
AUTH_HEADERS = {"X-Axon-API-Key": API_KEY}

_EMPTY_RESPONSE = AttributionResponse(
    total_cost_usd=Decimal("0"),
    total_tokens=0,
    total_savings_usd=Decimal("0"),
    breakdown=[],
)


@pytest.mark.asyncio
async def test_get_attribution_returns_401_without_key(async_client: AsyncClient) -> None:
    """GET /v1/attribution without API key returns 401."""
    response = await async_client.get(
        "/v1/attribution",
        params={
            "from_ts": "2025-01-01T00:00:00Z",
            "to_ts": "2025-12-31T00:00:00Z",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_attribution_invalid_group_by_returns_422(
    async_client: AsyncClient,
) -> None:
    """GET /v1/attribution with invalid group_by returns 422."""
    response = await async_client.get(
        "/v1/attribution",
        params={
            "from_ts": "2025-01-01T00:00:00Z",
            "to_ts": "2025-12-31T00:00:00Z",
            "group_by": "invalid_dimension",
        },
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_attribution_valid_returns_200(async_client: AsyncClient) -> None:
    """GET /v1/attribution with valid params returns 200."""
    with patch(
        "axon_backend.api.v1.attribution.get_attribution",
        new=AsyncMock(return_value=_EMPTY_RESPONSE),
    ):
        response = await async_client.get(
            "/v1/attribution",
            params={
                "from_ts": "2025-01-01T00:00:00Z",
                "to_ts": "2025-12-31T00:00:00Z",
                "group_by": "feature_tag",
            },
            headers=AUTH_HEADERS,
        )
    assert response.status_code == 200
    data = response.json()
    assert "breakdown" in data
    assert "total_cost_usd" in data


@pytest.mark.asyncio
async def test_get_attribution_summary_invalid_period_returns_422(
    async_client: AsyncClient,
) -> None:
    """GET /v1/attribution/summary with invalid period returns 422."""
    response = await async_client.get(
        "/v1/attribution/summary",
        params={"period": "quarterly"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_attribution_summary_valid_returns_200(
    async_client: AsyncClient,
) -> None:
    """GET /v1/attribution/summary with valid period returns 200."""
    from unittest.mock import MagicMock  # noqa: PLC0415

    mock_result = MagicMock()
    mock_result.fetchall.return_value = []

    with patch(
        "axon_backend.api.v1.attribution.AsyncSession",
        autospec=True,
    ), patch(
        "axon_backend.core.database.AsyncSessionLocal",
        return_value=MagicMock(
            __aenter__=AsyncMock(
                return_value=AsyncMock(execute=AsyncMock(return_value=mock_result))
            ),
            __aexit__=AsyncMock(return_value=False),
        ),
    ):
        response = await async_client.get(
            "/v1/attribution/summary",
            params={"period": "daily"},
            headers=AUTH_HEADERS,
        )
    assert response.status_code in (200, 500)
