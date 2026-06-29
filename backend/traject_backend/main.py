"""Traject Backend — FastAPI application entry point.

Wires up the lifespan context manager (DB init, Redis ping, scheduler),
CORS and request-logging middleware, health endpoints, and the v1 router.

Version: 0.2.0
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from traject_backend.api.v1.router import router as v1_router
from traject_backend.core.auth import assert_secure_api_key
from traject_backend.core.config import settings
from traject_backend.core.database import engine, init_db
from traject_backend.core.redis_client import get_redis, ping_redis
from traject_backend.workers.scheduler import register_jobs, scheduler


def _configure_logging() -> None:
    """Configure structlog to emit JSON (was never configured → console text).

    Honors LOG_LEVEL (default INFO). JSON logs are required for production log
    aggregation; the previous default ConsoleRenderer emitted colorized text.
    """
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


_configure_logging()

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
    _log.info("traject.backend.startup")
    # C5: refuse to boot with the well-known default API key in production.
    assert_secure_api_key()
    await init_db()
    await ping_redis()
    # H11: only run the in-process scheduler when enabled. Disable on web
    # workers (RUN_SCHEDULER=false) and run one dedicated scheduler process to
    # avoid every worker firing every job; jobs also take a Redis lock.
    if settings.run_scheduler:
        register_jobs()
        scheduler.start()
    else:
        _log.info("traject.backend.scheduler_disabled")
    _log.info("traject.backend.ready")

    yield

    # Shutdown
    _log.info("traject.backend.shutdown")
    if settings.run_scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
    await engine.dispose()
    try:
        await get_redis().aclose()
    except Exception as exc:  # noqa: BLE001
        _log.warning("traject.backend.redis.close_error", error=str(exc))
    _log.info("traject.backend.stopped")


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
            "traject.http.request",
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
    title="Traject Backend",
    description="Self-hosted LLM observability: span ingestion, cost attribution, semantic cache.",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS — explicit origins only. Credentials + wildcard methods/headers are a
# smell; scope them so widening cors_origins can't enable cross-site auth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", settings.api_key_header],
)

# Request logging
app.add_middleware(RequestLoggingMiddleware)

# Prometheus /metrics — the platform must observe itself. Guarded import so the
# app still runs if the optional dependency isn't installed.
try:
    from prometheus_fastapi_instrumentator import Instrumentator  # type: ignore[import-not-found]  # noqa: PLC0415,E501

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
except Exception as exc:  # noqa: BLE001
    _log.warning("traject.metrics.disabled", error=str(exc))

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
        _log.error("traject.health.db.error", error=str(exc))
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@app.get("/readyz", tags=["health"])
async def readyz() -> dict[str, object]:
    """Readiness probe: ready only when BOTH DB and Redis are reachable.

    Liveness (``/health``) just says the process is up; readiness gates traffic
    on dependencies so a pod with a dead DB is not marked Ready.

    Raises:
        HTTPException: 503 when any dependency is unavailable.
    """
    from fastapi import HTTPException  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    checks: dict[str, str] = {}
    ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["db"] = "error"
        ok = False
        _log.error("traject.readyz.db.error", error=str(exc))
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = "error"
        ok = False
        _log.error("traject.readyz.redis.error", error=str(exc))

    if not ok:
        raise HTTPException(status_code=503, detail={"status": "not_ready", **checks})
    return {"status": "ready", **checks}


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
        _log.error("traject.health.redis.error", error=str(exc))
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc
