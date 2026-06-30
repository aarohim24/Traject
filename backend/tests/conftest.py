"""Shared pytest fixtures for traject-backend tests.

Provides async database sessions (isolated per test), a fakeredis mock,
an async FastAPI test client, and span payload factories.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import fakeredis.aioredis  # type: ignore[import-untyped]
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from traject_backend.main import app
from traject_backend.models.base import Base
from traject_backend.services.span_ingestion import InferenceSpanPayload

# ---------------------------------------------------------------------------
# In-memory SQLite test engine
# ---------------------------------------------------------------------------
# SQLite does not support the pgvector column type, so tests that require
# vector search are skipped in unit tests. Integration tests using the real
# PG DB handle those paths.

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

_test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
_TestSession = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_tables() -> AsyncGenerator[None, None]:
    """Create all tables once for the test session (excluding pgvector).

    The CacheEntryRecord model uses Vector(384) which SQLite does not
    support.  We create tables for the three non-vector models only.
    """
    from traject_backend.models.attribution import CostAttributionRecord  # noqa: F401
    from traject_backend.models.budget import BudgetControlRecord  # noqa: F401
    from traject_backend.models.span import InferenceSpanRecord  # noqa: F401

    async with _test_engine.begin() as conn:
        # Only create tables that don't use pgvector
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c,
                tables=[
                    Base.metadata.tables[t]
                    for t in Base.metadata.tables
                    if t != "cache_entries"
                ],
            )
        )
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an isolated async database session that is rolled back after each test."""
    async with _TestSession() as session, session.begin():
        yield session
        await session.rollback()


@pytest.fixture
def redis_mock() -> Any:
    """Return an in-memory fakeredis client for unit tests."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Yield an HTTPX AsyncClient backed by the FastAPI app (no real server)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Span payload factories
# ---------------------------------------------------------------------------


def sample_span_payload(**overrides: Any) -> InferenceSpanPayload:
    """Build a valid InferenceSpanPayload with realistic defaults.

    Args:
        **overrides: Any field values to override.

    Returns:
        A valid :class:`InferenceSpanPayload` instance.
    """
    return InferenceSpanPayload(
        id=overrides.get("id", uuid.uuid4()),
        trace_id=overrides.get("trace_id", str(uuid.uuid4())),
        span_name=overrides.get("span_name", "gen_ai.openai.gpt-4o"),
        timestamp=overrides.get("timestamp", datetime.now(tz=UTC)),
        duration_ms=overrides.get("duration_ms", 150),
        provider=overrides.get("provider", "openai"),
        model=overrides.get("model", "gpt-4o"),
        input_tokens=overrides.get("input_tokens", 100),
        output_tokens=overrides.get("output_tokens", 50),
        cached_tokens=overrides.get("cached_tokens", 0),
        token_count_method=overrides.get("token_count_method", "exact"),
        cost_usd=overrides.get("cost_usd", Decimal("0.00125000")),
        feature_tag=overrides.get("feature_tag", "test-feature"),
        prompt_hash=overrides.get("prompt_hash", "a" * 64),
        artifact_type=overrides.get("artifact_type", "user_message"),
        compression_applied=overrides.get("compression_applied", False),
        shadow_mode=overrides.get("shadow_mode", True),
        cache_hit=overrides.get("cache_hit", False),
        environment=overrides.get("environment", "test"),
    )


def sample_spans_batch(n: int = 10, **overrides: Any) -> list[InferenceSpanPayload]:
    """Build a batch of n valid InferenceSpanPayload instances.

    Args:
        n: Number of payloads to generate.
        **overrides: Applied to every span in the batch.

    Returns:
        List of :class:`InferenceSpanPayload` instances.
    """
    return [sample_span_payload(**overrides) for _ in range(n)]
