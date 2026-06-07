"""Unit and property-based tests for axon.core.cost_calculator.

Validates: Requirements R3.6, R3.7, R3.8, R3.9
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from axon.core.cost_calculator import calculate_cost, get_pricing
from axon.core.pricing import PROVIDER_PRICING

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KNOWN_MODELS = list(PROVIDER_PRICING.keys())


# ---------------------------------------------------------------------------
# Tests for get_pricing
# ---------------------------------------------------------------------------


def test_get_pricing_returns_none_for_unknown_model() -> None:
    """get_pricing returns None for an unrecognised model, no exception."""
    result = get_pricing("not-a-real-model-xyz")
    assert result is None


@pytest.mark.parametrize("model", _KNOWN_MODELS)
def test_get_pricing_returns_model_pricing_for_known_models(model: str) -> None:
    """get_pricing returns a ModelPricing instance for every known model."""
    result = get_pricing(model)
    assert result is not None
    assert result.model == model


# ---------------------------------------------------------------------------
# Tests for calculate_cost — known models
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", _KNOWN_MODELS)
def test_calculate_cost_returns_decimal_for_known_models(model: str) -> None:
    """calculate_cost returns a Decimal >= 0 for every known model."""
    result = calculate_cost(model, 1000, 500)
    assert isinstance(result, Decimal)
    assert result >= Decimal("0")


def test_calculate_cost_zero_tokens_returns_zero() -> None:
    """Zero input and output tokens yields exactly Decimal zero."""
    result = calculate_cost("gpt-4o", 0, 0)
    assert result is not None
    assert result == Decimal("0.00000000")


def test_calculate_cost_unknown_model_returns_none(caplog: pytest.LogCaptureFixture) -> None:
    """Unknown model returns None without raising an exception."""
    result = calculate_cost("totally-unknown-model-abc123", 100, 100)
    assert result is None


def test_calculate_cost_unknown_model_no_exception() -> None:
    """calculate_cost never raises for an unknown model string."""
    # Should not raise anything
    calculate_cost("completely-fake-model", 0, 0)
    calculate_cost("", 100, 200)


# ---------------------------------------------------------------------------
# Cached-token scenario
# ---------------------------------------------------------------------------


def test_calculate_cost_cached_tokens_uses_cache_rate() -> None:
    """Cached tokens are billed at the cache-read rate, not the input rate.

    gpt-4o: input=$2.50/M, cache_read=$1.25/M, output=$10.00/M
    input=1000, cached=1000, output=0
      → non_cached_input = 0  → input_cost  = 0
      → cache_cost = (1000/1_000_000) * 1.25 = 0.00000125
      → output_cost = 0
    """
    result = calculate_cost("gpt-4o", input_tokens=1000, output_tokens=0, cached_tokens=1000)
    assert result is not None
    # cache_cost only: 1000 / 1_000_000 * 1.25
    expected = (Decimal("1000") / Decimal("1000000")) * Decimal("1.25")
    expected = expected.quantize(Decimal("0.00000001"))
    assert result == expected


def test_calculate_cost_no_cache_rate_model_ignores_cached_tokens() -> None:
    """When model has no cache rate, cached_tokens are billed at standard input rate.

    gpt-4-turbo has no cache_read_cost_per_1m_tokens.
    input=1000, cached=500, output=0
      → non_cached_input = 500, cache_cost = 0 (no cache rate)
      → input_cost = (500/1_000_000) * 10.00
    """
    result = calculate_cost("gpt-4-turbo", input_tokens=1000, output_tokens=0, cached_tokens=500)
    assert result is not None
    expected = (Decimal("500") / Decimal("1000000")) * Decimal("10.00")
    expected = expected.quantize(Decimal("0.00000001"))
    assert result == expected


# ---------------------------------------------------------------------------
# Decimal precision and no-float-drift tests
# ---------------------------------------------------------------------------


def test_calculate_cost_precision_at_most_8_decimal_places() -> None:
    """Result has no more than 8 decimal places for any known model."""
    for model in _KNOWN_MODELS:
        result = calculate_cost(model, 123456, 78901)
        assert result is not None
        # The number of decimal places in the quantized result must be <= 8
        _sign, _digits, exponent = result.as_tuple()
        assert exponent >= -8, f"{model}: exponent {exponent} exceeds 8 decimal places"


def test_calculate_cost_no_float_drift_exact_decimal() -> None:
    """Cost for exactly 1,000,000 tokens matches the expected Decimal exactly.

    gpt-4o: input=$2.50/M, output=$10.00/M
    1_000_000 input + 1_000_000 output = $12.50 exactly
    """
    result = calculate_cost("gpt-4o", 1_000_000, 1_000_000)
    assert result is not None
    assert result == Decimal("12.50000000")


def test_calculate_cost_gpt4o_mini_exact() -> None:
    """Exact cost for gpt-4o-mini with known token counts."""
    # gpt-4o-mini: input=0.15/M, output=0.60/M
    # 500_000 input + 250_000 output
    # input_cost = 0.5 * 0.15 = 0.075
    # output_cost = 0.25 * 0.60 = 0.15
    # total = 0.225
    result = calculate_cost("gpt-4o-mini", 500_000, 250_000)
    assert result is not None
    assert result == Decimal("0.22500000")


# ---------------------------------------------------------------------------
# Property P9 — non-negativity for all known models
# Validates: Requirements R3.6, R3.7
# ---------------------------------------------------------------------------


@given(
    model=st.sampled_from(_KNOWN_MODELS),
    input_tokens=st.integers(min_value=0, max_value=10**6),
    output_tokens=st.integers(min_value=0, max_value=10**6),
)
@settings(max_examples=200)
def test_property_p9_cost_is_non_negative(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """**Validates: Requirements R3.6, R3.7**

    P9: calculate_cost always returns a non-negative Decimal for any
    known model and any non-negative token counts.
    """
    result = calculate_cost(model, input_tokens, output_tokens)
    assert result is not None
    assert isinstance(result, Decimal)
    assert result >= Decimal("0")


# ---------------------------------------------------------------------------
# Property P10 — unknown models return None
# Validates: Requirements R3.8, R3.9
# ---------------------------------------------------------------------------


@given(
    model=st.text().filter(lambda s: s not in PROVIDER_PRICING),
)
@settings(max_examples=200)
def test_property_p10_unknown_model_returns_none(model: str) -> None:
    """**Validates: Requirements R3.8, R3.9**

    P10: calculate_cost returns None (and never raises) for any string
    that is not a key in PROVIDER_PRICING.
    """
    result = calculate_cost(model, 0, 0)
    assert result is None
