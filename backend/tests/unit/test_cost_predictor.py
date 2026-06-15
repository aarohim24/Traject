"""Unit and property-based tests for axon_backend.services.cost_predictor.

Covers:
- Sparse fallback (< 10 rows): lower = 0.50 * point, upper = 1.50 * point.
- KeyError on unknown model identifier.
- Property: lower_bound <= point_estimate <= upper_bound for all valid inputs.

**Validates: Requirements 7.1, 7.2**
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from axon.core.pricing import PROVIDER_PRICING
from axon_backend.services.cost_predictor import CostPredictor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_db(cost_rows: list[Decimal]) -> AsyncMock:
    """Build a mock AsyncSession that returns *cost_rows* from db.execute().

    Simulates the result chain:
        result = await db.execute(stmt)
        rows   = result.scalars().all()  →  cost_rows

    Args:
        cost_rows: The list of Decimal cost_usd values to return.

    Returns:
        An ``AsyncMock`` mimicking an ``AsyncSession``.
    """
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = cost_rows
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# Task 23.1 — Unit tests
# ---------------------------------------------------------------------------


class TestCostPredictorUnit:
    """Unit tests for CostPredictor."""

    @pytest.mark.asyncio
    async def test_returns_50_pct_fallback_when_fewer_than_10_rows(self) -> None:
        """Sparse fallback: lower = 0.50 * point, upper = 1.50 * point.

        When DB returns fewer than 10 ``cost_usd`` rows the predictor must
        use the static 50% / 150% envelope around the point estimate.

        **Validates: Requirements 7.1**
        """
        predictor = CostPredictor()
        model = "gpt-4o"
        input_tokens = 1_000
        output_tokens = 500

        point_estimate = predictor.compute_point_estimate(
            model, input_tokens, output_tokens
        )

        # Fewer than 10 rows → sparse path
        db = _make_mock_db(
            [Decimal("0.001"), Decimal("0.002"), Decimal("0.003")]  # 3 rows
        )

        lower, upper, sample_count = await predictor.predict_interval(
            db, model, point_estimate, input_tokens, output_tokens
        )

        expected_lower = point_estimate * Decimal("0.50")
        expected_upper = point_estimate * Decimal("1.50")

        assert lower == expected_lower, (
            f"Expected lower={expected_lower}, got {lower}"
        )
        assert upper == expected_upper, (
            f"Expected upper={expected_upper}, got {upper}"
        )
        assert sample_count == 3

    def test_raises_key_error_on_unknown_model(self) -> None:
        """compute_point_estimate raises KeyError for an unrecognised model.

        **Validates: Requirements 7.1**
        """
        predictor = CostPredictor()
        with pytest.raises(KeyError):
            predictor.compute_point_estimate("unknown-model-xyz", 100, 100)


# ---------------------------------------------------------------------------
# Task 23.2 — Property-based test
# ---------------------------------------------------------------------------


class TestCostPredictorProperties:
    """Hypothesis property tests for CostPredictor."""

    @settings(max_examples=50)
    @given(
        model=st.sampled_from(list(PROVIDER_PRICING.keys())),
        input_tokens=st.integers(min_value=0, max_value=10_000),
        output_tokens=st.integers(min_value=0, max_value=10_000),
    )
    @pytest.mark.asyncio
    async def test_lower_bound_lte_point_estimate_lte_upper_bound(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """lower_bound <= point_estimate <= upper_bound holds for all valid inputs.

        Uses the sparse path (5 rows) so no live DB is required.

        **Validates: Requirements 7.2**
        """
        predictor = CostPredictor()
        point_estimate = predictor.compute_point_estimate(
            model, input_tokens, output_tokens
        )

        # 5 sparse rows → sparse fallback path
        db = _make_mock_db(
            [Decimal("0.001")] * 5
        )

        lower, upper, _ = await predictor.predict_interval(
            db, model, point_estimate, input_tokens, output_tokens
        )

        assert lower <= point_estimate, (
            f"lower ({lower}) > point_estimate ({point_estimate}) for model={model}, "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}"
        )
        assert point_estimate <= upper, (
            f"point_estimate ({point_estimate}) > upper ({upper}) for model={model}, "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}"
        )
