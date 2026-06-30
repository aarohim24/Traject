"""APScheduler background workers for the Traject backend.

Defines the recurring jobs:
- ``materialize_attribution``: hourly at :05, backfilling any missed hours.
- ``expire_cache_entries``: daily at 02:00 to remove stale cache rows.
- ``recompute_budget_counters``: every 15 minutes to refresh Redis.
- ``span_retention``: daily at 03:30 to prune spans past the retention window.
- ``ml_weekly_training``: Sundays at 01:00 to retrain the ML router.
- ``anomaly_scan``: every 6 hours to flag cost anomalies.

Every job runs under a per-job Redis lock so that with multiple workers only
one process executes a given invocation (audit H11). The module-level
``scheduler`` is started/stopped by the FastAPI lifespan in
:mod:`traject_backend.main`, gated on ``settings.run_scheduler``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from traject_backend.core.database import AsyncSessionLocal
from traject_backend.core.redis_client import get_redis

_log = structlog.get_logger(__name__)

scheduler = AsyncIOScheduler()

# A job invocation runs on at most one process at a time: each acquires a short
# Redis lock keyed by job id (audit H11 — every Uvicorn worker otherwise fires
# every job). Lock TTL bounds how long a crashed holder blocks the next run.
_LOCK_TTL_SECONDS = 300


async def _run_locked(
    job_id: str, fn: Callable[[], Awaitable[None]], ttl: int = _LOCK_TTL_SECONDS
) -> None:
    """Run *fn* only if this process wins the per-job Redis lock."""
    redis = get_redis()
    token = str(uuid.uuid4())
    key = f"traject:lock:{job_id}"
    try:
        acquired = await redis.set(key, token, nx=True, ex=ttl)
    except Exception as exc:  # noqa: BLE001 — if Redis is down, run anyway
        _log.warning("traject.worker.lock.unavailable", job=job_id, error=str(exc))
        acquired = True
    if not acquired:
        _log.debug("traject.worker.lock.skipped", job=job_id)
        return
    await fn()


async def _run_materialize_attribution() -> None:
    """Aggregate inference spans for the most recently completed hour.

    Computes the start of the previous complete hour bucket and calls
    :func:`~traject_backend.services.cost_attribution.materialize_hourly`.
    Errors are caught and logged; the scheduler is never crashed.
    """
    try:
        from traject_backend.services.cost_attribution import materialize_hourly  # noqa: PLC0415

        now = datetime.utcnow()
        current_hour = now.replace(minute=0, second=0, microsecond=0)

        # Backfill every un-materialized hour since the last watermark (audit
        # M1 — the prior version only did the previous hour, so any downtime
        # left permanent gaps). Watermark is stored in Redis; cap the catch-up
        # window so a long outage doesn't do unbounded work in one run.
        redis = get_redis()
        watermark_key = "traject:watermark:materialize_hourly"
        try:
            wm = await redis.get(watermark_key)
        except Exception:  # noqa: BLE001
            wm = None
        if wm is not None:
            wm_str = wm.decode() if isinstance(wm, bytes) else str(wm)
            start = datetime.fromisoformat(wm_str) + timedelta(hours=1)
        else:
            start = current_hour - timedelta(hours=1)
        max_hours = 48
        if start < current_hour - timedelta(hours=max_hours):
            start = current_hour - timedelta(hours=max_hours)

        total_rows = 0
        hour = start
        async with AsyncSessionLocal() as db:
            while hour < current_hour:
                total_rows += await materialize_hourly(db, hour)
                last_done = hour
                hour += timedelta(hours=1)
                try:
                    await redis.set(watermark_key, last_done.isoformat())
                except Exception:  # noqa: BLE001
                    pass
        _log.info(
            "traject.worker.materialize_attribution.done",
            through=str(current_hour - timedelta(hours=1)),
            rows=total_rows,
        )
    except Exception as exc:  # noqa: BLE001
        _log.error("traject.worker.materialize_attribution.error", error=str(exc))


async def _run_span_retention() -> None:
    """Prune inference_spans older than the retention window (audit H10).

    Raw spans grow without bound; history lives in the cost_attribution rollup.
    A future migration should range-partition this table and drop old
    partitions instead of a bulk DELETE for higher-volume deployments.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        from traject_backend.core.config import settings  # noqa: PLC0415

        cutoff = datetime.utcnow() - timedelta(days=settings.span_retention_days)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("DELETE FROM inference_spans WHERE timestamp < :cutoff"),
                {"cutoff": cutoff},
            )
            await db.commit()
        _log.info(
            "traject.worker.span_retention.done",
            deleted=getattr(result, "rowcount", -1),
            cutoff=str(cutoff),
        )
    except Exception as exc:  # noqa: BLE001
        _log.error("traject.worker.span_retention.error", error=str(exc))


async def _run_expire_cache_entries() -> None:
    """Delete cache entries whose ``expires_at`` timestamp has passed.

    Errors are caught and logged; the scheduler is never crashed.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "DELETE FROM cache_entries WHERE expires_at IS NOT NULL AND expires_at < now()"
                )
            )
            await db.commit()
        _log.info("traject.worker.expire_cache.done")
    except Exception as exc:  # noqa: BLE001
        _log.error("traject.worker.expire_cache.error", error=str(exc))


async def _run_recompute_budget_counters() -> None:
    """Refresh Redis budget counters from the DB for all configured budgets.

    Queries all ``BudgetControlRecord`` rows and recomputes the spend for
    each feature tag by summing ``cost_usd`` from ``inference_spans`` for
    the current budget period.  Stores the result in Redis.

    Errors are caught and logged; the scheduler is never crashed.
    """
    try:
        from sqlalchemy import func, select  # noqa: PLC0415

        from traject_backend.core.config import settings  # noqa: PLC0415
        from traject_backend.models.budget import BudgetControlRecord  # noqa: PLC0415
        from traject_backend.models.span import InferenceSpanRecord  # noqa: PLC0415
        from traject_backend.services.budget_enforcer import (  # noqa: PLC0415
            _period_start,
        )

        redis = get_redis()
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(BudgetControlRecord))
            budgets = result.scalars().all()

            for budget in budgets:
                period_start = _period_start(budget.period)
                spend_result = await db.execute(
                    select(func.coalesce(func.sum(InferenceSpanRecord.cost_usd), 0)).where(
                        InferenceSpanRecord.feature_tag == budget.feature_tag,
                        InferenceSpanRecord.timestamp >= period_start,
                    )
                )
                spent = spend_result.scalar() or 0
                redis_key = f"traject:budget:{budget.feature_tag}"
                await redis.set(
                    redis_key,
                    str(spent),
                    ex=settings.redis_cache_ttl_seconds,
                )

        _log.info(
            "traject.worker.recompute_budget_counters.done",
            count=len(budgets),
        )
    except Exception as exc:  # noqa: BLE001
        _log.error("traject.worker.recompute_budget_counters.error", error=str(exc))


async def _run_anomaly_scan() -> None:
    """Scan all feature tags for IQR-based cost anomalies and emit alerts.

    Creates a fresh :class:`~traject_backend.services.anomaly_detector.AnomalyDetector`
    instance, opens a database session, and calls ``run_scan(db)``.  Each
    returned :class:`~traject_backend.services.anomaly_detector.AnomalyAlert` is
    emitted as a structlog WARNING with full context fields.

    Errors are caught and logged; the scheduler is never crashed.
    """
    try:
        from traject_backend.services.anomaly_detector import (  # noqa: PLC0415
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        async with AsyncSessionLocal() as db:
            alerts = await detector.run_scan(db)
        for alert in alerts:
            _log.warning(
                "traject.anomaly_detector.alert",
                feature_tag=alert.feature_tag,
                metric=alert.metric,
                direction=alert.direction,
                observed_value=alert.observed_value,
                upper_fence=alert.upper_fence,
                lower_fence=alert.lower_fence,
            )
        _log.info("traject.worker.anomaly_scan.done", alert_count=len(alerts))
    except Exception as exc:  # noqa: BLE001
        _log.error("traject.worker.anomaly_scan.error", error=str(exc))


async def _run_ml_weekly_training() -> None:
    """Retrain the ML routing model on the latest labeled inference spans.

    Creates a fresh :class:`~traject_backend.services.ml_training.MLTrainingService`
    instance, opens a database session, and delegates all training and
    persistence logic to
    :meth:`~traject_backend.services.ml_training.MLTrainingService.run_weekly_training_job`.

    Errors are caught and logged; the scheduler is never crashed.
    """
    try:
        from traject_backend.services.ml_training import MLTrainingService  # noqa: PLC0415

        svc = MLTrainingService()
        async with AsyncSessionLocal() as db:
            await svc.run_weekly_training_job(db)
        _log.info("traject.worker.ml_weekly_training.done")
    except Exception as exc:  # noqa: BLE001
        _log.error("traject.worker.ml_weekly_training.error", error=str(exc))


def register_jobs() -> None:
    """Register all background jobs with the module-level scheduler.

    Should be called once before :meth:`~apscheduler.schedulers.asyncio.AsyncIOScheduler.start`.
    Calling it more than once is safe — the scheduler deduplicates jobs by ID.
    """

    def _locked(job_id: str, fn: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
        async def _wrapped() -> None:
            await _run_locked(job_id, fn)

        return _wrapped

    scheduler.add_job(
        _locked("materialize_attribution", _run_materialize_attribution),
        trigger="cron",
        minute=5,
        id="materialize_attribution",
        replace_existing=True,
    )
    scheduler.add_job(
        _locked("expire_cache_entries", _run_expire_cache_entries),
        trigger="cron",
        hour=2,
        minute=0,
        id="expire_cache_entries",
        replace_existing=True,
    )
    scheduler.add_job(
        _locked("recompute_budget_counters", _run_recompute_budget_counters),
        trigger="interval",
        minutes=15,
        id="recompute_budget_counters",
        replace_existing=True,
    )
    scheduler.add_job(
        _locked("ml_weekly_training", _run_ml_weekly_training),
        trigger="cron",
        day_of_week="sun",
        hour=1,
        minute=0,
        id="ml_weekly_training",
        replace_existing=True,
    )
    scheduler.add_job(
        _locked("anomaly_scan", _run_anomaly_scan),
        trigger="interval",
        hours=6,
        id="anomaly_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        _locked("span_retention", _run_span_retention),
        trigger="cron",
        hour=3,
        minute=30,
        id="span_retention",
        replace_existing=True,
    )
