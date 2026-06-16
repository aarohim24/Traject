"""Redis client singleton and health-check utilities for the Axon backend.

Provides a module-level singleton ``redis.asyncio.Redis`` instance created
lazily on first access, plus an async ``ping_redis()`` health-check helper
that is called during application startup.

Key namespace convention
------------------------
All Redis keys written by this service follow the pattern::

    "axon:{key_type}:{identifier}"

Examples:

* ``"axon:budget:{feature_tag}"``   — cached budget spend counter
* ``"axon:cache:{prompt_hash}"``    — semantic-cache TTL marker
"""

from __future__ import annotations

import structlog
from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url

from traject_backend.core.config import settings

_log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Module-level singleton; created lazily on first call to get_redis().
_redis: Redis | None = None


def get_redis() -> Redis:
    """Return the module-level Redis singleton, creating it on first call.

    Uses ``redis.asyncio.from_url`` with ``decode_responses=True`` so all
    values returned from Redis are native Python strings.  The connection is
    not established until the first command is issued (lazy connect).

    Returns:
        Redis: The shared async Redis client instance.
    """
    global _redis
    if _redis is None:
        _redis = redis_from_url(settings.redis_url, decode_responses=True)
    return _redis


async def ping_redis() -> None:
    """Ping Redis to verify connectivity.

    Calls ``PING`` on the shared Redis client.  Logs success at info level
    using the event key ``""traject.redis.ping.ok"``.  Any exception is caught
    and logged at error level using the event key
    ``""traject.redis.ping.failed"``; the exception is never re-raised so that
    a Redis outage at startup does not prevent the application from booting.
    """
    try:
        await get_redis().ping()
        _log.info(""traject.redis.ping.ok")
    except Exception as exc:  # noqa: BLE001
        _log.error(""traject.redis.ping.failed", error=str(exc))
