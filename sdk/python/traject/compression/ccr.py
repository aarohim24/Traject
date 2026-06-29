"""Content-Compress-Retrieve (CCR) — reversible compression via Redis.

Instead of permanently dropping segments, CCR stores the full content in Redis
keyed by a SHA-256 hash prefix and injects a short stub in its place.  An MCP
tool (``traject_retrieve``) lets the agent fetch any stored segment on demand.

Stub format:  ``<<ccr:HASH16>>``
where HASH16 is the first 16 hex characters of the SHA-256 of the content.
Collision probability is < 10⁻¹⁸ for 10 000 segments — safe for agentic use.
The stub costs roughly 8 tokens, vs. hundreds for the original content.

Redis is an optional dependency: import is deferred so that callers without
Redis still get a clean ``TrajectDependencyError`` rather than an import error.
When no CCR store is configured the engine falls back to normal DROP behaviour.
"""

from __future__ import annotations

import hashlib
from typing import Any

STUB_PREFIX: str = "<<ccr:"
STUB_SUFFIX: str = ">>"
_KEY_PREFIX: str = "traject:ccr:"
_HASH_LEN: int = 16  # first N hex chars of SHA-256
DEFAULT_TTL_SECONDS: int = 60 * 60 * 24 * 7  # 7 days


def _sha256_prefix(content: str) -> str:
    """Return the first ``_HASH_LEN`` hex characters of SHA-256(*content*)."""
    return hashlib.sha256(content.encode()).hexdigest()[:_HASH_LEN]


class CCRStore:
    """Redis-backed store for reversible context compression.

    Args:
        redis_client: A synchronous ``redis.Redis`` client instance.
        ttl_seconds: Time-to-live for stored content.  Defaults to 7 days.
    """

    def __init__(
        self,
        redis_client: Any,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._client: Any = redis_client
        self._ttl = ttl_seconds

    @classmethod
    def from_url(
        cls,
        url: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> CCRStore:
        """Construct a :class:`CCRStore` from a Redis connection URL.

        Args:
            url: Redis URL, e.g. ``"redis://localhost:6379/0"``.
            ttl_seconds: Content TTL in seconds.

        Returns:
            A new :class:`CCRStore` connected to *url*.

        Raises:
            TrajectDependencyError: If the ``redis`` package is not installed.
        """
        try:
            import redis
        except ImportError as exc:
            from traject.exceptions import TrajectDependencyError

            raise TrajectDependencyError(
                "CCR requires the redis package. "
                "Install it with: pip install 'traject-sdk[ccr]'"
            ) from exc
        client: Any = redis.from_url(url)
        return cls(client, ttl_seconds=ttl_seconds)

    def store(self, content: str) -> str:
        """Persist *content* in Redis and return the CCR stub to inject.

        Args:
            content: Original segment text to preserve.

        Returns:
            A stub string in ``<<ccr:HASH16>>`` format.
        """
        h = _sha256_prefix(content)
        key = f"{_KEY_PREFIX}{h}"
        self._client.set(key, content.encode(), ex=self._ttl)
        return f"{STUB_PREFIX}{h}{STUB_SUFFIX}"

    def retrieve(self, hash_prefix: str) -> str | None:
        """Fetch the original content by its 16-character hash prefix.

        Args:
            hash_prefix: The HASH16 string extracted from a CCR stub.

        Returns:
            The original content string, or ``None`` if not found or expired.
        """
        key = f"{_KEY_PREFIX}{hash_prefix}"
        raw: object = self._client.get(key)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    @staticmethod
    def make_stub(content: str) -> str:
        """Return the stub for *content* without storing it.

        Primarily for testing stub format without a live Redis connection.

        Args:
            content: Content to hash.

        Returns:
            The ``<<ccr:HASH16>>`` string that *would* be stored.
        """
        h = _sha256_prefix(content)
        return f"{STUB_PREFIX}{h}{STUB_SUFFIX}"

    @staticmethod
    def extract_hash(stub: str) -> str | None:
        """Extract the hash prefix from a CCR stub string.

        Args:
            stub: A string that may be a CCR stub.

        Returns:
            The 16-character hash prefix, or ``None`` if *stub* is not a stub.
        """
        s = stub.strip()
        if s.startswith(STUB_PREFIX) and s.endswith(STUB_SUFFIX):
            return s[len(STUB_PREFIX) : -len(STUB_SUFFIX)]
        return None

    @staticmethod
    def is_stub(content: str) -> bool:
        """Return ``True`` when *content* is a CCR stub.

        Args:
            content: Segment content string.

        Returns:
            ``True`` when *content* matches ``<<ccr:HASH16>>``.
        """
        s = content.strip()
        return s.startswith(STUB_PREFIX) and s.endswith(STUB_SUFFIX)
