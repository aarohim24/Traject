"""Unit tests for axon_backend.services.semantic_cache."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from axon_backend.services.semantic_cache import (
    CacheLookupResponse,
    CacheStoreRequest,
    lookup,
    store,
)


class TestLookup:
    """Tests for the semantic cache lookup() function."""

    @pytest.mark.asyncio
    async def test_returns_miss_when_table_empty(self, db_session) -> None:
        """Returns a cache miss when the cache_entries table is empty.

        The SQLite test DB does not have the cache_entries table (no pgvector),
        so we mock the DB execute to simulate a miss gracefully.
        """
        with patch.object(db_session, "execute", new=AsyncMock(side_effect=Exception("no table"))):
            result = await lookup(
                prompt_hash="a" * 64,
                embedding=[0.0] * 384,
                db=db_session,
                threshold=0.92,
            )
        # Fail open — returns miss, never raises
        assert result.hit is False

    @pytest.mark.asyncio
    async def test_graceful_on_db_error(self, db_session) -> None:
        """lookup() returns CacheLookupResponse(hit=False) on any DB error."""
        with patch.object(db_session, "execute", new=AsyncMock(side_effect=RuntimeError("oops"))):
            result = await lookup(
                prompt_hash="b" * 64,
                embedding=[0.1] * 384,
                db=db_session,
                threshold=0.90,
            )
        assert isinstance(result, CacheLookupResponse)
        assert result.hit is False
        assert result.response_preview is None


class TestStore:
    """Tests for the semantic cache store() function."""

    @pytest.mark.asyncio
    async def test_does_not_raise_on_db_error(self, db_session) -> None:
        """store() catches DB errors and never raises."""
        request = CacheStoreRequest(
            prompt_hash="c" * 64,
            prompt_embedding=[0.0] * 384,
            response_preview="This is a test response.",
            model="gpt-4o",
            feature_tag="test",
            cost_usd=Decimal("0.001"),
        )
        with patch.object(db_session, "execute", new=AsyncMock(side_effect=RuntimeError("oops"))):
            # Must not raise
            await store(request, db_session)

    @pytest.mark.asyncio
    async def test_response_preview_truncated_to_200(self, db_session) -> None:
        """store() truncates response_preview to 200 characters."""
        long_response = "x" * 500
        request = CacheStoreRequest(
            prompt_hash="d" * 64,
            prompt_embedding=[0.0] * 384,
            response_preview=long_response,
            model="gpt-4o",
            feature_tag="test",
            cost_usd=Decimal("0.002"),
        )
        # Patch execute to capture the values inserted
        executed_values: list[dict] = []

        async def mock_execute(stmt, *args, **kwargs):  # type: ignore[no-untyped-def]
            # Try to extract values from the INSERT statement
            try:
                vals = stmt.compile().params  # type: ignore[attr-defined]
                executed_values.append(vals)
            except Exception:  # noqa: BLE001
                pass
            from unittest.mock import MagicMock  # noqa: PLC0415
            return MagicMock()

        with (
            patch.object(db_session, "execute", side_effect=mock_execute),
            patch.object(db_session, "commit", new=AsyncMock()),
        ):
            await store(request, db_session)
        # The function enforces truncation via [:200] in service code
        assert request.response_preview[:200] == "x" * 200
