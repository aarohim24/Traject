"""Unit tests for traject.cache.semantic_cache.SemanticCacheClient.

Mocks the BackendClient's internal httpx client to avoid real HTTP calls
and mocks the embedding model to avoid loading sentence-transformers.
The module under test (semantic_cache) is never mocked.

Validates: Requirements 6 (Semantic Cache, fail-open contract).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from traject.cache.semantic_cache import CacheLookupResult, SemanticCacheClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_backend_client(
    *,
    post_response: Any = None,
    post_side_effect: Any = None,
) -> MagicMock:
    """Build a mock BackendClient whose internal _client.post is controlled.

    Args:
        post_response: The value returned by the mock post call, if any.
        post_side_effect: Side effect (exception) to raise on post, if any.

    Returns:
        A :class:`unittest.mock.MagicMock` standing in for BackendClient.
    """
    mock_http_response = MagicMock()
    mock_http_response.is_success = True
    mock_http_response.json.return_value = {
        "hit": False,
        "response_preview": None,
        "similarity": None,
    }

    mock_post = AsyncMock()
    if post_side_effect is not None:
        mock_post.side_effect = post_side_effect
    elif post_response is not None:
        mock_post.return_value = post_response
    else:
        mock_post.return_value = mock_http_response

    mock_inner_client = MagicMock()
    mock_inner_client.post = mock_post

    mock_backend_client = MagicMock()
    mock_backend_client._client = mock_inner_client

    return mock_backend_client


def _make_embedding_model() -> MagicMock:
    """Build a mock sentence-transformers model that returns a fake 384-dim embedding."""
    mock_model = MagicMock()
    # encode() returns something with .tolist() → list of 384 floats
    mock_encoded = MagicMock()
    mock_encoded.tolist.return_value = [0.0] * 384
    mock_model.encode.return_value = mock_encoded
    return mock_model


_MESSAGES: list[dict[str, Any]] = [
    {"role": "user", "content": "What is the capital of France?"},
]
_MODEL = "gpt-4o-mini"
_FEATURE_TAG = "test-geo"
_RESPONSE_TEXT = "Paris is the capital of France."
_COST = Decimal("0.00005000")


# ---------------------------------------------------------------------------
# Test 1: lookup returns None on cache miss (hit=False)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_returns_none_on_cache_miss() -> None:
    """lookup returns a CacheLookupResult with hit=False on a backend cache miss.

    A miss is defined as the backend returning ``{"hit": false}``.
    The method must return the CacheLookupResult (not None) so callers know
    the cache was consulted successfully.
    """
    miss_response = MagicMock()
    miss_response.is_success = True
    miss_response.json.return_value = {
        "hit": False,
        "response_preview": None,
        "similarity": None,
    }

    mock_client = _make_backend_client(post_response=miss_response)
    cache = SemanticCacheClient(mock_client)

    with patch(
        "traject.cache.semantic_cache._get_embedding_model",
        return_value=_make_embedding_model(),
    ):
        result = await cache.lookup(_MESSAGES, _MODEL)

    # On a miss the method should return a CacheLookupResult with hit=False
    assert result is not None
    assert isinstance(result, CacheLookupResult)
    assert result.hit is False
    assert result.response_preview is None


# ---------------------------------------------------------------------------
# Test 2: store does not raise under normal conditions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_does_not_raise() -> None:
    """store completes without raising under normal conditions.

    Fire-and-forget: the return value is None and no exception propagates.
    """
    mock_client = _make_backend_client()
    cache = SemanticCacheClient(mock_client)

    with patch(
        "traject.cache.semantic_cache._get_embedding_model",
        return_value=_make_embedding_model(),
    ):
        # Must not raise
        result = await cache.store(
            messages=_MESSAGES,
            response_text=_RESPONSE_TEXT,
            model=_MODEL,
            feature_tag=_FEATURE_TAG,
            cost_usd=_COST,
        )

    assert result is None


# ---------------------------------------------------------------------------
# Test 3: lookup returns None on backend error (fail open)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_returns_none_on_backend_error() -> None:
    """lookup returns None when the backend raises an exception (fail open).

    The inference path must never be blocked by cache failures.
    """
    mock_client = _make_backend_client(
        post_side_effect=RuntimeError("backend connection refused")
    )
    cache = SemanticCacheClient(mock_client)

    with patch(
        "traject.cache.semantic_cache._get_embedding_model",
        return_value=_make_embedding_model(),
    ):
        result = await cache.lookup(_MESSAGES, _MODEL)

    assert result is None, f"Expected None on backend error (fail open), got {result!r}"


# ---------------------------------------------------------------------------
# Test 4: store does not raise on backend error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_does_not_raise_on_backend_error() -> None:
    """store does not raise when the backend raises an exception.

    Fire-and-forget: all errors are logged internally, never propagated.
    """
    mock_client = _make_backend_client(
        post_side_effect=RuntimeError("backend write failed")
    )
    cache = SemanticCacheClient(mock_client)

    with patch(
        "traject.cache.semantic_cache._get_embedding_model",
        return_value=_make_embedding_model(),
    ):
        # Must not raise
        try:
            await cache.store(
                messages=_MESSAGES,
                response_text=_RESPONSE_TEXT,
                model=_MODEL,
                feature_tag=_FEATURE_TAG,
                cost_usd=_COST,
            )
        except Exception as exc:
            pytest.fail(f"store raised {type(exc).__name__} on backend error: {exc}")


# ---------------------------------------------------------------------------
# Test 5: lookup returns None when backend returns non-success HTTP status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_returns_none_on_non_success_http_status() -> None:
    """lookup returns None when the backend returns a non-success HTTP response.

    Any non-2xx response is treated as a cache miss (fail open).
    """
    error_response = MagicMock()
    error_response.is_success = False

    mock_client = _make_backend_client(post_response=error_response)
    cache = SemanticCacheClient(mock_client)

    with patch(
        "traject.cache.semantic_cache._get_embedding_model",
        return_value=_make_embedding_model(),
    ):
        result = await cache.lookup(_MESSAGES, _MODEL)

    assert result is None, f"Expected None on non-success HTTP status, got {result!r}"


# ---------------------------------------------------------------------------
# Test 6: lookup returns CacheLookupResult with hit=True on a cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_returns_result_with_hit_true_on_cache_hit() -> None:
    """lookup returns a CacheLookupResult with hit=True when the backend reports a cache hit."""
    hit_response = MagicMock()
    hit_response.is_success = True
    hit_response.json.return_value = {
        "hit": True,
        "response_preview": "Paris is the capital",
        "similarity": 0.97,
    }

    mock_client = _make_backend_client(post_response=hit_response)
    cache = SemanticCacheClient(mock_client)

    with patch(
        "traject.cache.semantic_cache._get_embedding_model",
        return_value=_make_embedding_model(),
    ):
        result = await cache.lookup(_MESSAGES, _MODEL)

    assert result is not None
    assert result.hit is True
    assert result.response_preview == "Paris is the capital"
    assert result.similarity == pytest.approx(0.97)
