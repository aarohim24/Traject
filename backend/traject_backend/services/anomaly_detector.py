"""IQR-based anomaly detector for feature-tag cost metrics.

Scans ``CostAttributionRecord`` hourly data for each feature tag and emits
``AnomalyAlert`` instances when the most-recent observed value falls outside
the ``[Q1 - 1.5·IQR, Q3 + 1.5·IQR]`` Tukey fence computed over the last
seven days of data.  All database errors are caught internally; ``run_scan``
never raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.models.attribution import CostAttributionRecord

_log = structlog.get_logger(__name__)

_LOOKBACK_DAYS: int = 7
_MIN_DATA_POINTS: int = 7
_IQR_MULTIPLIER: float = 1.5


@dataclass
class AnomalyAlert:
    """A detected cost anomaly for a single feature tag.

    Attributes:
        feature_tag: The feature-attribution label where the anomaly was found.
        metric: The metric name that triggered the alert (e.g. ``"cost_usd"``).
        direction: ``"high"`` when the observed value exceeds the upper fence,
            ``"low"`` when it falls below the lower fence.
        observed_value: The most-recent hourly value that triggered the alert.
        upper_fence: The Tukey upper fence (``Q3 + 1.5 * IQR``).
        lower_fence: The Tukey lower fence (``Q1 - 1.5 * IQR``).
        detected_at: UTC timestamp when the anomaly was detected.
    """

    feature_tag: str
    metric: str
    direction: str
    observed_value: float
    upper_fence: float
    lower_fence: float
    detected_at: datetime


class AnomalyDetector:
    """Detects cost anomalies across all tracked feature tags.

    Uses Tukey's IQR method to identify feature tags whose most-recent
    hourly ``total_cost_usd`` value lies outside the expected range derived
    from the preceding seven days of data.

    Example::

        detector = AnomalyDetector()
        async with AsyncSessionLocal() as db:
            alerts = await detector.run_scan(db)
    """

    async def run_scan(self, db: AsyncSession) -> list[AnomalyAlert]:
        """Scan all feature tags for cost anomalies using IQR fencing.

        Queries every distinct ``feature_tag`` that has at least
        ``_MIN_DATA_POINTS`` hourly ``CostAttributionRecord`` rows within the
        last ``_LOOKBACK_DAYS`` days.  For each qualifying tag the method:

        1. Extracts all ``total_cost_usd`` values as ``float`` (oldest-first).
        2. Computes ``Q1`` (25th percentile), ``Q3`` (75th percentile), and
           ``IQR = Q3 - Q1``.
        3. Computes Tukey fences:
           ``upper_fence = Q3 + 1.5 * IQR``,
           ``lower_fence = Q1 - 1.5 * IQR``.
        4. Compares the most-recent hourly value (row with the greatest
           ``hour_bucket``) against the fences.
        5. Emits an :class:`AnomalyAlert` when the observed value is outside
           either fence.

        Args:
            db: An active async SQLAlchemy session.

        Returns:
            A list of :class:`AnomalyAlert` instances (may be empty).  Never
            raises — any exception is caught and logged; the method returns
            ``[]`` on error.
        """
        try:
            return await self._do_scan(db)
        except Exception as exc:  # noqa: BLE001
            _log.error(""traject.anomaly_detector.scan_error", error=str(exc))
            return []

    async def _do_scan(self, db: AsyncSession) -> list[AnomalyAlert]:
        """Internal scan implementation (may raise; caller catches all).

        Args:
            db: An active async SQLAlchemy session.

        Returns:
            List of detected :class:`AnomalyAlert` instances.
        """
        cutoff = datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)

        # Fetch all distinct feature_tags that have rows in the window
        tag_stmt = (
            select(CostAttributionRecord.feature_tag)
            .where(CostAttributionRecord.hour_bucket >= cutoff)
            .distinct()
        )
        tag_result = await db.execute(tag_stmt)
        feature_tags: list[str] = list(tag_result.scalars().all())

        alerts: list[AnomalyAlert] = []

        for feature_tag in feature_tags:
            tag_alerts = await self._scan_feature_tag(db, feature_tag, cutoff)
            alerts.extend(tag_alerts)

        return alerts

    async def _scan_feature_tag(
        self,
        db: AsyncSession,
        feature_tag: str,
        cutoff: datetime,
    ) -> list[AnomalyAlert]:
        """Evaluate one feature tag for cost anomalies.

        Args:
            db: An active async SQLAlchemy session.
            feature_tag: The feature tag to evaluate.
            cutoff: The earliest ``hour_bucket`` timestamp to include.

        Returns:
            A list of zero or one :class:`AnomalyAlert` instances.
        """
        rows_stmt = (
            select(
                CostAttributionRecord.hour_bucket,
                CostAttributionRecord.total_cost_usd,
            )
            .where(
                CostAttributionRecord.feature_tag == feature_tag,
                CostAttributionRecord.hour_bucket >= cutoff,
            )
            .order_by(CostAttributionRecord.hour_bucket)
        )
        rows_result = await db.execute(rows_stmt)
        rows = rows_result.all()

        if len(rows) < _MIN_DATA_POINTS:
            return []

        # Extract cost values in ascending time order
        cost_values: list[float] = [float(row.total_cost_usd) for row in rows]

        # Compute IQR fences on the sorted distribution
        sorted_values = sorted(cost_values)
        q1 = _percentile(sorted_values, 0.25)
        q3 = _percentile(sorted_values, 0.75)
        iqr = q3 - q1
        upper_fence = q3 + _IQR_MULTIPLIER * iqr
        lower_fence = q1 - _IQR_MULTIPLIER * iqr

        # Most-recent row is the last in the time-ordered result
        observed_value = cost_values[-1]
        detected_at = datetime.utcnow()

        if observed_value > upper_fence:
            return [
                AnomalyAlert(
                    feature_tag=feature_tag,
                    metric="cost_usd",
                    direction="high",
                    observed_value=observed_value,
                    upper_fence=upper_fence,
                    lower_fence=lower_fence,
                    detected_at=detected_at,
                )
            ]

        if observed_value < lower_fence:
            return [
                AnomalyAlert(
                    feature_tag=feature_tag,
                    metric="cost_usd",
                    direction="low",
                    observed_value=observed_value,
                    upper_fence=upper_fence,
                    lower_fence=lower_fence,
                    detected_at=detected_at,
                )
            ]

        return []


def _percentile(sorted_values: list[float], q: float) -> float:
    """Return the ``q``-th quantile of an already-sorted list.

    Uses the simple floor-index approach:
    ``index = int(q * len(sorted_values))``, clamped to a valid position.

    Args:
        sorted_values: A non-empty sorted list of float values.
        q: Quantile in ``[0.0, 1.0]`` (e.g. ``0.25`` for the 25th percentile).

    Returns:
        The value at the computed index.
    """
    n = len(sorted_values)
    index = int(q * n)
    # Clamp to valid range
    index = min(index, n - 1)
    return sorted_values[index]
