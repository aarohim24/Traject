"""Unit tests for axon.core.pricing.

Validates: Requirements R1.4, R3.6, R16.5
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from axon.core.pricing import PROVIDER_PRICING

_EXPECTED_MODELS = [
    "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo",
    "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229",
    "gemini-1.5-pro", "gemini-1.5-flash",
]


class TestProviderPricing:

    def test_all_nine_models_present(self) -> None:
        for model in _EXPECTED_MODELS:
            assert model in PROVIDER_PRICING, f"Missing model: {model}"

    @pytest.mark.parametrize("model", _EXPECTED_MODELS)
    def test_input_cost_is_decimal(self, model: str) -> None:
        assert isinstance(PROVIDER_PRICING[model].input_cost_per_1m_tokens, Decimal)

    @pytest.mark.parametrize("model", _EXPECTED_MODELS)
    def test_output_cost_is_decimal(self, model: str) -> None:
        assert isinstance(PROVIDER_PRICING[model].output_cost_per_1m_tokens, Decimal)

    @pytest.mark.parametrize("model", _EXPECTED_MODELS)
    def test_all_costs_non_negative(self, model: str) -> None:
        p = PROVIDER_PRICING[model]
        assert p.input_cost_per_1m_tokens >= Decimal("0")
        assert p.output_cost_per_1m_tokens >= Decimal("0")

    @pytest.mark.parametrize("model", _EXPECTED_MODELS)
    def test_cache_read_cost_is_decimal_or_none(self, model: str) -> None:
        v = PROVIDER_PRICING[model].cache_read_cost_per_1m_tokens
        assert v is None or isinstance(v, Decimal)

    @pytest.mark.parametrize("model", _EXPECTED_MODELS)
    def test_last_verified_is_date(self, model: str) -> None:
        assert isinstance(PROVIDER_PRICING[model].last_verified, date)

    @pytest.mark.parametrize("model", _EXPECTED_MODELS)
    def test_pricing_url_non_empty(self, model: str) -> None:
        assert PROVIDER_PRICING[model].pricing_url.startswith("https://")

    def test_model_pricing_is_frozen(self) -> None:
        import dataclasses

        p = PROVIDER_PRICING["gpt-4o"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.input_cost_per_1m_tokens = Decimal("99")  # type: ignore[misc]

    def test_gpt4o_values(self) -> None:
        p = PROVIDER_PRICING["gpt-4o"]
        assert p.provider == "openai"
        assert p.input_cost_per_1m_tokens == Decimal("2.50")
        assert p.output_cost_per_1m_tokens == Decimal("10.00")
        assert p.cache_read_cost_per_1m_tokens == Decimal("1.25")

    def test_claude_sonnet_has_cache_write(self) -> None:
        p = PROVIDER_PRICING["claude-3-5-sonnet-20241022"]
        assert p.cache_write_cost_per_1m_tokens is not None
        assert p.cache_write_cost_per_1m_tokens > Decimal("0")

    def test_gpt_turbo_no_cache_rate(self) -> None:
        p = PROVIDER_PRICING["gpt-4-turbo"]
        assert p.cache_read_cost_per_1m_tokens is None
