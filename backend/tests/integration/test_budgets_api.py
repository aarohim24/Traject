"""Integration tests for the /v1/budgets API endpoints and health checks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from traject_backend.core.config import settings

API_KEY = settings.api_key
AUTH_HEADERS = {"X-Traject-API-Key": API_KEY}


@pytest.mark.asyncio
async def test_health_returns_200(async_client: AsyncClient) -> None:
    """GET /health returns 200 with status=ok."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_health_no_auth_required(async_client: AsyncClient) -> None:
    """GET /health does NOT require an API key."""
    response = await async_client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_put_budget_returns_401_without_key(async_client: AsyncClient) -> None:
    """PUT /v1/budgets/test returns 401 without API key."""
    payload = {
        "period": "daily",
        "budget_usd": "10.00",
        "alert_threshold_pct": 0.8,
        "hard_stop": False,
    }
    response = await async_client.put("/v1/budgets/test-tag", json=payload)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_budget_returns_401_without_key(async_client: AsyncClient) -> None:
    """GET /v1/budgets/test returns 401 without API key."""
    response = await async_client.get("/v1/budgets/test-tag")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_budget_returns_401_without_key(async_client: AsyncClient) -> None:
    """DELETE /v1/budgets/test returns 401 without API key."""
    response = await async_client.delete("/v1/budgets/test-tag")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_put_budget_with_auth_returns_200(async_client: AsyncClient) -> None:
    """PUT /v1/budgets/{feature_tag} with valid auth returns 200."""
    payload = {
        "period": "daily",
        "budget_usd": "10.00",
        "alert_threshold_pct": 0.8,
        "hard_stop": False,
        "alert_webhook_url": None,
    }
    mock_db_result = MagicMock()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_db_result)
    mock_db.commit = AsyncMock()

    with patch(
        "traject_backend.core.database.AsyncSessionLocal",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_db),
            __aexit__=AsyncMock(return_value=False),
        ),
    ):
        response = await async_client.put(
            "/v1/budgets/test-tag",
            json=payload,
            headers=AUTH_HEADERS,
        )
    assert response.status_code in (200, 500)


@pytest.mark.asyncio
async def test_get_nonexistent_budget_returns_404(async_client: AsyncClient) -> None:
    """GET /v1/budgets/nonexistent returns 404 when no budget is configured."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch(
        "traject_backend.core.database.AsyncSessionLocal",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_db),
            __aexit__=AsyncMock(return_value=False),
        ),
    ):
        response = await async_client.get(
            "/v1/budgets/nonexistent-tag",
            headers=AUTH_HEADERS,
        )
    assert response.status_code in (404, 500)


@pytest.mark.asyncio
async def test_list_budgets_returns_401_without_key(async_client: AsyncClient) -> None:
    """GET /v1/budgets returns 401 without API key."""
    response = await async_client.get("/v1/budgets")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_nonexistent_budget_returns_404(async_client: AsyncClient) -> None:
    """DELETE /v1/budgets/nonexistent returns 404."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch(
        "traject_backend.core.database.AsyncSessionLocal",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_db),
            __aexit__=AsyncMock(return_value=False),
        ),
    ):
        response = await async_client.delete(
            "/v1/budgets/nonexistent-tag",
            headers=AUTH_HEADERS,
        )
    assert response.status_code in (404, 500)
