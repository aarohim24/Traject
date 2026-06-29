"""Unit tests for traject.compression.ccr.

Tests that do not require a live Redis connection use CCRStore.make_stub
and CCRStore.extract_hash.  Tests that require Redis are skipped when
the redis package is not installed.
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from traject.compression.ccr import (
    _HASH_LEN,
    DEFAULT_TTL_SECONDS,
    STUB_PREFIX,
    STUB_SUFFIX,
    CCRStore,
    _sha256_prefix,
)

# ── Hash utilities ────────────────────────────────────────────────────────────


class TestSha256Prefix:
    def test_length(self) -> None:
        assert len(_sha256_prefix("hello")) == _HASH_LEN

    def test_deterministic(self) -> None:
        assert _sha256_prefix("abc") == _sha256_prefix("abc")

    def test_different_inputs(self) -> None:
        assert _sha256_prefix("abc") != _sha256_prefix("xyz")

    def test_matches_hashlib(self) -> None:
        expected = hashlib.sha256(b"test content").hexdigest()[:_HASH_LEN]
        assert _sha256_prefix("test content") == expected


# ── Stub format ───────────────────────────────────────────────────────────────


class TestStubFormat:
    def test_make_stub_format(self) -> None:
        stub = CCRStore.make_stub("some content")
        assert stub.startswith(STUB_PREFIX)
        assert stub.endswith(STUB_SUFFIX)

    def test_make_stub_length(self) -> None:
        stub = CCRStore.make_stub("content")
        inner = stub[len(STUB_PREFIX) : -len(STUB_SUFFIX)]
        assert len(inner) == _HASH_LEN

    def test_is_stub_true(self) -> None:
        stub = CCRStore.make_stub("hello world")
        assert CCRStore.is_stub(stub) is True

    def test_is_stub_false_plain(self) -> None:
        assert CCRStore.is_stub("plain text") is False

    def test_is_stub_false_empty(self) -> None:
        assert CCRStore.is_stub("") is False

    def test_extract_hash_valid(self) -> None:
        stub = CCRStore.make_stub("hello world")
        h = CCRStore.extract_hash(stub)
        assert h == _sha256_prefix("hello world")

    def test_extract_hash_invalid(self) -> None:
        assert CCRStore.extract_hash("not a stub") is None

    def test_extract_hash_empty(self) -> None:
        assert CCRStore.extract_hash("") is None

    def test_stub_with_leading_whitespace(self) -> None:
        stub = "  " + CCRStore.make_stub("x") + "  "
        assert CCRStore.is_stub(stub) is True

    def test_make_stub_deterministic(self) -> None:
        assert CCRStore.make_stub("content") == CCRStore.make_stub("content")

    def test_different_content_different_stub(self) -> None:
        assert CCRStore.make_stub("aaa") != CCRStore.make_stub("bbb")


# ── CCRStore with mocked Redis ────────────────────────────────────────────────


def _make_mock_redis() -> MagicMock:
    mock = MagicMock()
    _store: dict[str, bytes] = {}

    def fake_set(key: str, value: bytes, ex: int | None = None) -> None:
        _store[key] = value

    def fake_get(key: str) -> bytes | None:
        return _store.get(key)

    mock.set.side_effect = fake_set
    mock.get.side_effect = fake_get
    return mock


class TestCCRStoreWithMockRedis:
    def test_store_returns_stub(self) -> None:
        store = CCRStore(_make_mock_redis())
        stub = store.store("hello world")
        assert stub.startswith(STUB_PREFIX)
        assert stub.endswith(STUB_SUFFIX)

    def test_store_then_retrieve(self) -> None:
        mock_redis = _make_mock_redis()
        store = CCRStore(mock_redis)
        content = "This is the original dropped content."
        stub = store.store(content)
        h = CCRStore.extract_hash(stub)
        assert h is not None
        result = store.retrieve(h)
        assert result == content

    def test_retrieve_missing_key(self) -> None:
        store = CCRStore(_make_mock_redis())
        assert store.retrieve("0000000000000000") is None

    def test_store_calls_redis_set_with_ttl(self) -> None:
        mock_redis = _make_mock_redis()
        store = CCRStore(mock_redis, ttl_seconds=3600)
        store.store("content")
        mock_redis.set.assert_called_once()
        _, kwargs = mock_redis.set.call_args
        assert kwargs.get("ex") == 3600 or mock_redis.set.call_args[0][2] == 3600

    def test_default_ttl(self) -> None:
        store = CCRStore(_make_mock_redis())
        assert store._ttl == DEFAULT_TTL_SECONDS

    def test_bytes_result_decoded(self) -> None:
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"byte content"
        store = CCRStore(mock_redis)
        result = store.retrieve("anykey")
        assert result == "byte content"
        assert isinstance(result, str)


# ── from_url without redis installed ─────────────────────────────────────────


class TestFromUrlWithoutRedis:
    def test_raises_dependency_error(self) -> None:
        with patch.dict("sys.modules", {"redis": None}):
            from traject.exceptions import TrajectDependencyError

            with pytest.raises(TrajectDependencyError, match="redis"):
                CCRStore.from_url("redis://localhost:6379/0")
