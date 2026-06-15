"""Cost predictor service for LLM inference calls.

Computes point estimates and 90% prediction intervals for planned LLM API
calls using static pricing data and historical span records from the database.
All monetary arithmetic uses ``Decimal`` exclusively (ADR-006).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_backend.models.span import InferenceSpanRecord

_log = structlog.get_logger(__name__)

_LOOKBACK_DAYS: int = 30
_MIN_SAMPLES: int = 10
_MAX_SAMPLES: int = 1000
_SPARSE_LOWER_FACTOR = Decimal("0.50")
_SPARSE_UPPER_FACTOR = Decimal("1.50")


class CostPredictor:
    """Predicts the cost of a planned LLM API call with a 90% prediction interval.

    Uses Decimal arithmetic for all monetary calculations (ADR-006).
    Point estimates are derived from the static ``PROVIDER_PRICING`` table.
    Prediction intervals are derived from historical ``InferenceSpanRecord``
    rows scaled to the requested token volume.
    """

    def compute_point_estimate(
        self,
        model: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
    ) -> Decimal:
        """Compute a point estimate for the cost of a planned LLM call.

        Uses the formula::

            (input_tokens / 1_000_000) * input_price
            + (output_tokens / 1_000_000) * output_price

        Args:
            model: Model identifier string (e.g. ``"gpt-4o"``).
            estimated_input_tokens: Estimated number of input/prompt tokens.
            estimated_output_tokens: Estimated number of output/completion tokens.

        Returns:
            Estimated cost in USD as a ``Decimal``.

        Raises:
            KeyError: If ``model`` is not found in ``PROVIDER_PRICING``.
        """
        from axon.core.pricing import PROVIDER_PRICING  # noqa: PLC0415

        pricing = PROVIDER_PRICING[model]
        input_cost = Decimal(
            str(
                (Decimal(str(estimated_input_tokens)) / Decimal("1000000"))
                * Decimal(str(pricing.input_cost_per_1m_tokens))
            )
        )
        output_cost = Decimal(
            str(
                (Decimal(str(estimated_output_tokens)) / Decimal("1000000"))
                * Decimal(str(pricing.output_cost_per_1m_tokens))
            )
        )
        return input_cost + output_cost

    async def predict_interval(
        self,
        db: AsyncSession,
        model: str,
        point_estimate: Decimal,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
    ) -> tuple[Decimal, Decimal, int]:
        """Compute a 90% prediction interval around the point estimate.

        Queries up to 1 000 historical ``InferenceSpanRecord.cost_usd`` rows
        for the same model within the last 30 days.  Two code paths apply:

        - **Sparse fallback** (< 10 rows): returns ``(0.50 * point, 1.50 * point)``.
        - **Empirical interval** (≥ 10 rows): scales historical costs to the
          requested token volume using the ratio of the point estimate to the
          historical median, then takes the 5th and 95th percentiles of the
          scaled distribution.

        The invariant ``lower_bound <= point_estimate <= upper_bound`` is
        enforced as a post-condition; if violated the sparse fallback is used
        instead.

        Args:
            db: An active async SQLAlchemy session.
            model: Model identifier string (e.g. ``"gpt-4o"``).
            point_estimate: The pre-computed point estimate (Decimal USD).
            estimated_input_tokens: Estimated number of input tokens.
            estimated_output_tokens: Estimated number of output tokens.

        Returns:
            A 3-tuple of ``(lower_bound, upper_bound, sample_count)`` where
            both bounds are ``Decimal`` USD values and ``sample_count`` is the
            number of historical rows used.
        """
        cutoff = datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)

        stmt = (
            select(InferenceSpanRecord.cost_usd)
            .where(
                InferenceSpanRecord.model == model,
                InferenceSpanRecord.timestamp >= cutoff,
            )
            .limit(_MAX_SAMPLES)
        )
        result = await db.execute(stmt)
        raw_rows = result.scalars().all()

        # Filter out NULL cost_usd values
        historical_costs: list[Decimal] = [
            c for c in raw_rows if c is not None
        ]
        sample_count = len(historical_costs)

        if sample_count < _MIN_SAMPLES:
            lower_bound = point_estimate * _SPARSE_LOWER_FACTOR
            upper_bound = point_estimate * _SPARSE_UPPER_FACTOR
            return (lower_bound, upper_bound, sample_count)

        # Empirical interval: scale historical costs to requested token volume
        sorted_costs = sorted(historical_costs)
        median = _percentile(sorted_costs, 50)

        if median == Decimal("0"):
            # Avoid division by zero; fall back to sparse
            lower_bound = point_estimate * _SPARSE_LOWER_FACTOR
            upper_bound = point_estimate * _SPARSE_UPPER_FACTOR
            return (lower_bound, upper_bound, sample_count)

        scale_factor = point_estimate / median
        scaled_costs = sorted([c * scale_factor for c in sorted_costs])

        lower_bound = _percentile(scaled_costs, 5)
        upper_bound = _percentile(scaled_costs, 95)

        # Enforce post-condition: lower_bound <= point_estimate <= upper_bound
        if not (lower_bound <= point_estimate <= upper_bound):
            _log.warning(
                "axon.cost_predictor.bounds_violated",
                lower_bound=str(lower_bound),
                point_estimate=str(point_estimate),
                upper_bound=str(upper_bound),
                model=model,
            )
            lower_bound = point_estimate * _SPARSE_LOWER_FACTOR
            upper_bound = point_estimate * _SPARSE_UPPER_FACTOR

        return (lower_bound, upper_bound, sample_count)


def _percentile(sorted_values: list[Decimal], pct: int) -> Decimal:
    """Compute the ``pct``-th percentile of an already-sorted list.

    Uses linear interpolation (same as ``numpy.percentile`` default method
    for ``method="linear"``).

    Args:
        sorted_values: A non-empty sorted list of ``Decimal`` values.
        pct: Integer percentile in the range ``[0, 100]``.

    Returns:
        The interpolated percentile value as a ``Decimal``.
    """
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    # Compute the fractional index
    index = Decimal(str(pct)) / Decimal("100") * Decimal(str(n - 1))
    lower_idx = int(index)
    upper_idx = lower_idx + 1
    if upper_idx >= n:
        return sorted_values[n - 1]
    fraction = index - Decimal(str(lower_idx))
    result: Decimal = sorted_values[lower_idx] + fraction * (
        sorted_values[upper_idx] - sorted_values[lower_idx]
    )
    return result
