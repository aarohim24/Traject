"""Cost calculation utilities for LLM inference calls.

Provides ``get_pricing`` for model price lookups and ``calculate_cost`` for
computing the exact USD cost of an inference call using Decimal arithmetic
throughout (ADR-006) — no float values are used at any point in the
computation pipeline.
"""

from __future__ import annotations

from decimal import Decimal

import structlog

from traject.core.pricing import PROVIDER_PRICING, ModelPricing

_log = structlog.get_logger(__name__)


def get_pricing(model: str) -> ModelPricing | None:
    """Return pricing data for the given model identifier, or ``None``.

    Performs a direct key lookup against the static ``PROVIDER_PRICING``
    table.  Unknown model strings are silently ignored — no exception is
    raised and no warning is logged.

    Args:
        model: The model identifier string as used in provider API requests
            (e.g. ``"gpt-4o"``).

    Returns:
        A :class:`~traject.core.pricing.ModelPricing` instance if the model is
        present in the pricing table, or ``None`` if it is unknown.
    """
    return PROVIDER_PRICING.get(model)


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> Decimal | None:
    """Compute the total USD cost for a single inference call.

    All arithmetic is performed exclusively with :class:`~decimal.Decimal`
    values (ADR-006).  No ``float`` values are introduced at any point.  The
    result is quantized to eight decimal places.

    If the model is not present in the pricing table, a ``WARNING``-level
    structured log event is emitted and ``None`` is returned — no exception
    is raised.

    Args:
        model: The model identifier string (e.g. ``"gpt-4o"``).
        input_tokens: Total number of input (prompt) tokens billed, including
            any tokens that were served from the provider's prompt cache.
        output_tokens: Total number of output (completion) tokens billed.
        cached_tokens: Number of input tokens that were served from the
            provider's prompt cache and should therefore be billed at the
            cache-read rate rather than the standard input rate.  Defaults to
            ``0``.  Must be ``<= input_tokens``.

    Returns:
        The total cost as a :class:`~decimal.Decimal` quantized to eight
        decimal places (e.g. ``Decimal("0.00250000")``), or ``None`` if the
        model is not found in the pricing table.

    Notes:
        The formula applied is::

            MILLION = Decimal("1000000")
            non_cached_input = input_tokens - cached_tokens
            input_cost  = (Decimal(non_cached_input) / MILLION)
                          * pricing.input_cost_per_1m_tokens
            cache_cost  = (Decimal(cached_tokens)    / MILLION)
                          * pricing.cache_read_cost_per_1m_tokens
                          (only when cached_tokens > 0 and cache rate is not None)
            output_cost = (Decimal(output_tokens)    / MILLION)
                          * pricing.output_cost_per_1m_tokens
            total = (input_cost + cache_cost + output_cost)
                    .quantize(Decimal("0.00000001"))
    """
    pricing = get_pricing(model)
    if pricing is None:
        _log.warning("traject.cost.unknown_model", model=model)
        return None

    million = Decimal("1000000")

    non_cached_input = input_tokens - cached_tokens
    input_cost = (
        Decimal(non_cached_input) / million
    ) * pricing.input_cost_per_1m_tokens

    cache_cost = Decimal("0")
    if cached_tokens > 0 and pricing.cache_read_cost_per_1m_tokens is not None:
        cache_cost = (
            Decimal(cached_tokens) / million
        ) * pricing.cache_read_cost_per_1m_tokens

    output_cost = (Decimal(output_tokens) / million) * pricing.output_cost_per_1m_tokens

    total = input_cost + cache_cost + output_cost
    return total.quantize(Decimal("0.00000001"))
