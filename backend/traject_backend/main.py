"""Axon Backend — FastAPI application entry point.

Wires up the lifespan context manager (DB init, Redis ping, scheduler),
CORS and request-logging middleware, health endpoints, and the v1 router.

Version: 0.2.0
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from traject_backend.api.v1.router import router as v1_router
from traject_backend.core.config import settings
from traject_backend.core.database import engine, init_db
from traject_backend.core.redis_client import get_redis, ping_redis
from traject_backend.workers.scheduler import register_jobs, scheduler

_log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and shutdown of backend resources.

    Startup sequence:
    1. ``init_db()`` — ensure tables exist.
    2. ``ping_redis()`` — verify Redis connectivity.
    3. ``register_jobs()`` + ``scheduler.start()`` — begin background jobs.

    Shutdown sequence (reversed):
    1. ``scheduler.shutdown(wait=False)``
    2. ``engine.dispose()`` — close DB connection pool.
    3. ``get_redis().aclose()`` — close Redis connections.
    """
    # Startup
    _log.info(""traject.backend.startup")
    await init_db()
    await ping_redis()
    register_jobs()
    scheduler.start()
    _log.info(""traject.backend.ready")

    yield

    # Shutdown
    _log.info(""traject.backend.shutdown")
    scheduler.shutdown(wait=False)
    await engine.dispose()
    try:
        await get_redis().aclose()
    except Exception as exc:  # noqa: BLE001
        _log.warning(""traject.backend.redis.close_error", error=str(exc))
    _log.info(""traject.backend.stopped")


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status code, and duration.

    Uses structlog exclusively — no ``print()`` statements.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process a request, measure latency, and emit a structured log.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The HTTP response from the next handler.
        """
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        _log.info(
            ""traject.http.request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Axon Backend",
    description="Self-hosted LLM observability: span ingestion, cost attribution, semantic cache.",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS — allow configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging
app.add_middleware(RequestLoggingMiddleware)

# v1 API routes
app.include_router(v1_router, prefix="/v1")


# ---------------------------------------------------------------------------
# Health endpoints (no authentication required)
# ---------------------------------------------------------------------------


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Return a simple liveness probe.

    Returns:
        Dict with ``status`` and ``version`` keys.
    """
    return {"status": "ok", "version": "0.2.0"}


@app.get("/health/db", tags=["health"])
async def health_db() -> dict[str, str]:
    """Check that the database is reachable.

    Returns:
        Dict with ``status: "ok"`` on success.

    Raises:
        HTTPException: 503 when the database is unreachable.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        _log.error(""traject.health.db.error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@app.get("/health/redis", tags=["health"])
async def health_redis() -> dict[str, str]:
    """Check that Redis is reachable.

    Returns:
        Dict with ``status: "ok"`` on success.

    Raises:
        HTTPException: 503 when Redis is unreachable.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    try:
        await get_redis().ping()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        _log.error(""traject.health.redis.error", error=str(exc))
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc
