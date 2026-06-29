"""Unit tests for the health/readiness probe endpoints in main.py.

These mock the database engine and Redis client so both the success and the
failure branches are exercised deterministically, without requiring live
services. Hitting any endpoint also exercises the request-logging middleware.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from traject_backend.main import app


@asynccontextmanager
async def _ok_conn() -> Any:
    """An async context manager yielding a connection whose execute() succeeds."""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=None)
    yield conn


def _ok_engine() -> MagicMock:
    engine = MagicMock()
    engine.connect = MagicMock(return_value=_ok_conn())
    return engine


def _failing_engine() -> MagicMock:
    engine = MagicMock()
    engine.connect = MagicMock(side_effect=RuntimeError("db down"))
    return engine


def _ok_redis() -> MagicMock:
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    return redis


def _failing_redis() -> MagicMock:
    redis = MagicMock()
    redis.ping = AsyncMock(side_effect=RuntimeError("redis down"))
    return redis


async def _get(client_factory: Any, path: str) -> Any:
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.get(path)


class TestHealthEndpoints:
    @pytest.mark.asyncio
    async def test_health_liveness(self) -> None:
        resp = await _get(None, "/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body

    @pytest.mark.asyncio
    async def test_health_db_ok(self) -> None:
        with patch("traject_backend.main.engine", _ok_engine()):
            resp = await _get(None, "/health/db")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_db_unavailable(self) -> None:
        with patch("traject_backend.main.engine", _failing_engine()):
            resp = await _get(None, "/health/db")
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_health_redis_ok(self) -> None:
        with patch("traject_backend.main.get_redis", return_value=_ok_redis()):
            resp = await _get(None, "/health/redis")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_redis_unavailable(self) -> None:
        with patch("traject_backend.main.get_redis", return_value=_failing_redis()):
            resp = await _get(None, "/health/redis")
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_readyz_ready(self) -> None:
        with (
            patch("traject_backend.main.engine", _ok_engine()),
            patch("traject_backend.main.get_redis", return_value=_ok_redis()),
        ):
            resp = await _get(None, "/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["db"] == "ok"
        assert body["redis"] == "ok"

    @pytest.mark.asyncio
    async def test_readyz_not_ready_when_db_down(self) -> None:
        with (
            patch("traject_backend.main.engine", _failing_engine()),
            patch("traject_backend.main.get_redis", return_value=_ok_redis()),
        ):
            resp = await _get(None, "/readyz")
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_readyz_not_ready_when_redis_down(self) -> None:
        with (
            patch("traject_backend.main.engine", _ok_engine()),
            patch("traject_backend.main.get_redis", return_value=_failing_redis()),
        ):
            resp = await _get(None, "/readyz")
        assert resp.status_code == 503
