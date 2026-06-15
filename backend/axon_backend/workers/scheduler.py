"""APScheduler background workers for the Axon backend.

Defines four recurring jobs:
- ``materialize_attribution``: runs every hour at :05 to aggregate spans.
- ``expire_cache_entries``: runs daily at 02:00 to remove stale cache rows.
- ``recompute_budget_counters``: runs every 15 minutes to refresh Redis.
- ``ml_weekly_training``: runs every Sunday at 01:00 to retrain the ML router.

The module-level ``scheduler`` instance is started and stopped by the
FastAPI lifespan context manager in :mod:`axon_backend.main`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from axon_backend.core.database import AsyncSessionLocal
from axon_backend.core.redis_client import get_redis

_log = structlog.get_logger(__name__)

scheduler = AsyncIOScheduler()


async def _run_materialize_attribution() -> None:
    """Aggregate inference spans for the most recently completed hour.

    Computes the start of the previous complete hour bucket and calls
    :func:`~axon_backend.services.cost_attribution.materialize_hourly`.
    Errors are caught and logged; the scheduler is never crashed.
    """
    try:
        from axon_backend.services.cost_attribution import materialize_hourly  # noqa: PLC0415

        now = datetime.utcnow()
        previous_hour = (now - timedelta(hours=1)).replace(
            minute=0, second=0, microsecond=0
        )
        async with AsyncSessionLocal() as db:
            rows = await materialize_hourly(db, previous_hour)
        _log.info(
            "axon.worker.materialize_attribution.done",
            hour=str(previous_hour),
            rows=rows,
        )
    except Exception as exc:  # noqa: BLE001
        _log.error("axon.worker.materialize_attribution.error", error=str(exc))


async def _run_expire_cache_entries() -> None:
    """Delete cache entries whose ``expires_at`` timestamp has passed.

    Errors are caught and logged; the scheduler is never crashed.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "DELETE FROM cache_entries "
                    "WHERE expires_at IS NOT NULL AND expires_at < now()"
                )
            )
            await db.commit()
        _log.info("axon.worker.expire_cache.done")
    except Exception as exc:  # noqa: BLE001
        _log.error("axon.worker.expire_cache.error", error=str(exc))


async def _run_recompute_budget_counters() -> None:
    """Refresh Redis budget counters from the DB for all configured budgets.

    Queries all ``BudgetControlRecord`` rows and recomputes the spend for
    each feature tag by summing ``cost_usd`` from ``inference_spans`` for
    the current budget period.  Stores the result in Redis.

    Errors are caught and logged; the scheduler is never crashed.
    """
    try:
        from sqlalchemy import func, select  # noqa: PLC0415

        from axon_backend.core.config import settings  # noqa: PLC0415
        from axon_backend.models.budget import BudgetControlRecord  # noqa: PLC0415
        from axon_backend.models.span import InferenceSpanRecord  # noqa: PLC0415
        from axon_backend.services.budget_enforcer import (  # noqa: PLC0415
            _period_start,
        )

        redis = get_redis()
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(BudgetControlRecord))
            budgets = result.scalars().all()

            for budget in budgets:
                period_start = _period_start(budget.period)
                spend_result = await db.execute(
                    select(
                        func.coalesce(
                            func.sum(InferenceSpanRecord.cost_usd), 0
                        )
                    ).where(
                        InferenceSpanRecord.feature_tag == budget.feature_tag,
                        InferenceSpanRecord.timestamp >= period_start,
                    )
                )
                spent = spend_result.scalar() or 0
                redis_key = f"axon:budget:{budget.feature_tag}"
                await redis.set(
                    redis_key,
                    str(spent),
                    ex=settings.redis_cache_ttl_seconds,
                )

        _log.info(
            "axon.worker.recompute_budget_counters.done",
            count=len(budgets),
        )
    except Exception as exc:  # noqa: BLE001
        _log.error("axon.worker.recompute_budget_counters.error", error=str(exc))


async def _run_anomaly_scan() -> None:
    """Scan all feature tags for IQR-based cost anomalies and emit alerts.

    Creates a fresh :class:`~axon_backend.services.anomaly_detector.AnomalyDetector`
    instance, opens a database session, and calls ``run_scan(db)``.  Each
    returned :class:`~axon_backend.services.anomaly_detector.AnomalyAlert` is
    emitted as a structlog WARNING with full context fields.

    Errors are caught and logged; the scheduler is never crashed.
    """
    try:
        from axon_backend.services.anomaly_detector import (  # noqa: PLC0415
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        async with AsyncSessionLocal() as db:
            alerts = await detector.run_scan(db)
        for alert in alerts:
            _log.warning(
                "axon.anomaly_detector.alert",
                feature_tag=alert.feature_tag,
                metric=alert.metric,
                direction=alert.direction,
                observed_value=alert.observed_value,
                upper_fence=alert.upper_fence,
                lower_fence=alert.lower_fence,
            )
        _log.info("axon.worker.anomaly_scan.done", alert_count=len(alerts))
    except Exception as exc:  # noqa: BLE001
        _log.error("axon.worker.anomaly_scan.error", error=str(exc))


async def _run_ml_weekly_training() -> None:
    """Retrain the ML routing model on the latest labeled inference spans.

    Creates a fresh :class:`~axon_backend.services.ml_training.MLTrainingService`
    instance, opens a database session, and delegates all training and
    persistence logic to
    :meth:`~axon_backend.services.ml_training.MLTrainingService.run_weekly_training_job`.

    Errors are caught and logged; the scheduler is never crashed.
    """
    try:
        from axon_backend.services.ml_training import MLTrainingService  # noqa: PLC0415

        svc = MLTrainingService()
        async with AsyncSessionLocal() as db:
            await svc.run_weekly_training_job(db)
        _log.info("axon.worker.ml_weekly_training.done")
    except Exception as exc:  # noqa: BLE001
        _log.error("axon.worker.ml_weekly_training.error", error=str(exc))


def register_jobs() -> None:
    """Register all background jobs with the module-level scheduler.

    Should be called once before :meth:`~apscheduler.schedulers.asyncio.AsyncIOScheduler.start`.
    Calling it more than once is safe — the scheduler deduplicates jobs by ID.
    """
    scheduler.add_job(
        _run_materialize_attribution,
        trigger="cron",
        minute=5,
        id="materialize_attribution",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_expire_cache_entries,
        trigger="cron",
        hour=2,
        minute=0,
        id="expire_cache_entries",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_recompute_budget_counters,
        trigger="interval",
        minutes=15,
        id="recompute_budget_counters",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_ml_weekly_training,
        trigger="cron",
        day_of_week="sun",
        hour=1,
        minute=0,
        id="ml_weekly_training",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_anomaly_scan,
        trigger="interval",
        hours=6,
        id="anomaly_scan",
        replace_existing=True,
    )
