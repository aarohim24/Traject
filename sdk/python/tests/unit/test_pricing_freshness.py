"""Pricing freshness contract.

For a cost-optimization product, a stale price is a correctness bug: every
savings figure and routing decision reads from ``PROVIDER_PRICING``. These
tests enforce that prices are re-verified periodically (the audit flagged the
table as ~18 months stale with no guard), and pin the current-generation
Claude rates so a silent edit to them fails CI.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from traject.core.pricing import (
    MAX_PRICE_AGE_DAYS,
    PROVIDER_PRICING,
    VERIFICATION_PENDING,
    stale_models,
)

# Current-generation Claude models that must be present with verified pricing.
_CURRENT_CLAUDE = {
    "claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
    "claude-opus-4-7": (Decimal("5.00"), Decimal("25.00")),
    "claude-opus-4-6": (Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-4-6": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    "claude-fable-5": (Decimal("10.00"), Decimal("50.00")),
}


class TestPricingFreshness:
    def test_no_stale_prices(self) -> None:
        """Every non-pending model must have been verified within the window.

        This is time-dependent by design: once a price ages past
        ``MAX_PRICE_AGE_DAYS`` it fails here, forcing a re-verification pass.
        """
        stale = stale_models(date.today())
        assert not stale, (
            f"Pricing older than {MAX_PRICE_AGE_DAYS} days: {stale}. "
            "Re-verify against the provider pricing page and bump last_verified, "
            "or add to VERIFICATION_PENDING with a tracking note."
        )

    def test_no_future_dates(self) -> None:
        today = date.today()
        for model, pricing in PROVIDER_PRICING.items():
            assert pricing.last_verified <= today, (
                f"{model} has a future last_verified ({pricing.last_verified})"
            )

    def test_verification_pending_entries_exist(self) -> None:
        """Allowlist entries must be real models (no dangling exemptions)."""
        for model in VERIFICATION_PENDING:
            assert model in PROVIDER_PRICING, (
                f"VERIFICATION_PENDING has unknown model: {model}"
            )


class TestCurrentClaudePricing:
    @pytest.mark.parametrize("model", sorted(_CURRENT_CLAUDE))
    def test_present(self, model: str) -> None:
        assert model in PROVIDER_PRICING, f"Missing current Claude model: {model}"

    @pytest.mark.parametrize("model", sorted(_CURRENT_CLAUDE))
    def test_input_output_rates(self, model: str) -> None:
        expected_in, expected_out = _CURRENT_CLAUDE[model]
        p = PROVIDER_PRICING[model]
        assert p.input_cost_per_1m_tokens == expected_in
        assert p.output_cost_per_1m_tokens == expected_out

    @pytest.mark.parametrize("model", sorted(_CURRENT_CLAUDE))
    def test_cache_read_is_tenth_of_input(self, model: str) -> None:
        """Cache-read tier follows the documented ~0.1x-input economics."""
        p = PROVIDER_PRICING[model]
        assert p.cache_read_cost_per_1m_tokens == p.input_cost_per_1m_tokens / Decimal(
            10
        )

    @pytest.mark.parametrize("model", sorted(_CURRENT_CLAUDE))
    def test_not_pending(self, model: str) -> None:
        assert model not in VERIFICATION_PENDING
