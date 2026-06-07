"""Static pricing table for supported LLM providers.

This module implements the authoritative, auditable pricing reference for all
models supported by the Axon SDK. Per ADR-006, all monetary values are stored
as ``Decimal`` instances constructed from string literals — never float
literals — to eliminate floating-point representation drift. Per ADR-010, the
table is a plain, human-readable data structure that can be diffed, audited,
and updated in a single pull-request without touching any computation logic.

The ``ModelPricing`` dataclass is defined here (frozen) so that the pricing
table can be imported by ``axon.core.cost_calculator`` without creating a
circular dependency. ``axon.models`` will re-export ``ModelPricing`` from this
module once it is implemented in Task 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ModelPricing:
    """Verified pricing for a single LLM model.

    All cost fields are in USD per 1,000,000 tokens. Values are stored as
    ``Decimal`` instances constructed from string literals to preserve exact
    decimal representation (ADR-006).

    Attributes:
        provider: Provider name (e.g. ``"openai"``, ``"anthropic"``,
            ``"google"``).
        model: Model identifier string as used in provider API requests
            (e.g. ``"gpt-4o"``).
        input_cost_per_1m_tokens: Cost in USD per 1 million input (prompt)
            tokens.
        output_cost_per_1m_tokens: Cost in USD per 1 million output
            (completion) tokens.
        cache_read_cost_per_1m_tokens: Cost in USD per 1 million tokens read
            from the provider's prompt cache, or ``None`` if the model does
            not support prompt caching.
        cache_write_cost_per_1m_tokens: Cost in USD per 1 million tokens
            written to the provider's prompt cache, or ``None`` if the model
            does not charge separately for cache writes (or does not support
            caching at all).
        pricing_url: Canonical URL of the provider's public pricing page from
            which these values were sourced.
        last_verified: Date on which these prices were last manually verified
            against the provider's published pricing page.
    """

    provider: str
    model: str
    input_cost_per_1m_tokens: Decimal
    output_cost_per_1m_tokens: Decimal
    cache_read_cost_per_1m_tokens: Decimal | None
    cache_write_cost_per_1m_tokens: Decimal | None
    pricing_url: str
    last_verified: date


# ---------------------------------------------------------------------------
# Static pricing table
# ---------------------------------------------------------------------------
# All Decimal values are constructed from string literals (ADR-006).
# Source URLs are cited above each provider block.
# ---------------------------------------------------------------------------

# Source: https://openai.com/api/pricing
_OPENAI_URL = "https://openai.com/api/pricing"

PROVIDER_PRICING: dict[str, ModelPricing] = {
    "gpt-4o": ModelPricing(
        provider="openai",
        model="gpt-4o",
        input_cost_per_1m_tokens=Decimal("2.50"),
        output_cost_per_1m_tokens=Decimal("10.00"),
        cache_read_cost_per_1m_tokens=Decimal("1.25"),
        cache_write_cost_per_1m_tokens=None,
        pricing_url=_OPENAI_URL,
        last_verified=date(2025, 1, 1),
    ),
    "gpt-4o-mini": ModelPricing(
        provider="openai",
        model="gpt-4o-mini",
        input_cost_per_1m_tokens=Decimal("0.15"),
        output_cost_per_1m_tokens=Decimal("0.60"),
        cache_read_cost_per_1m_tokens=Decimal("0.075"),
        cache_write_cost_per_1m_tokens=None,
        pricing_url=_OPENAI_URL,
        last_verified=date(2025, 1, 1),
    ),
    "gpt-4-turbo": ModelPricing(
        provider="openai",
        model="gpt-4-turbo",
        input_cost_per_1m_tokens=Decimal("10.00"),
        output_cost_per_1m_tokens=Decimal("30.00"),
        cache_read_cost_per_1m_tokens=None,
        cache_write_cost_per_1m_tokens=None,
        pricing_url=_OPENAI_URL,
        last_verified=date(2025, 1, 1),
    ),
    "gpt-3.5-turbo": ModelPricing(
        provider="openai",
        model="gpt-3.5-turbo",
        input_cost_per_1m_tokens=Decimal("0.50"),
        output_cost_per_1m_tokens=Decimal("1.50"),
        cache_read_cost_per_1m_tokens=None,
        cache_write_cost_per_1m_tokens=None,
        pricing_url=_OPENAI_URL,
        last_verified=date(2025, 1, 1),
    ),
    # Source: https://www.anthropic.com/pricing
    "claude-3-5-sonnet-20241022": ModelPricing(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        input_cost_per_1m_tokens=Decimal("3.00"),
        output_cost_per_1m_tokens=Decimal("15.00"),
        cache_read_cost_per_1m_tokens=Decimal("0.30"),
        cache_write_cost_per_1m_tokens=Decimal("3.75"),
        pricing_url="https://www.anthropic.com/pricing",
        last_verified=date(2025, 1, 1),
    ),
    "claude-3-5-haiku-20241022": ModelPricing(
        provider="anthropic",
        model="claude-3-5-haiku-20241022",
        input_cost_per_1m_tokens=Decimal("0.80"),
        output_cost_per_1m_tokens=Decimal("4.00"),
        cache_read_cost_per_1m_tokens=Decimal("0.08"),
        cache_write_cost_per_1m_tokens=Decimal("1.00"),
        pricing_url="https://www.anthropic.com/pricing",
        last_verified=date(2025, 1, 1),
    ),
    "claude-3-opus-20240229": ModelPricing(
        provider="anthropic",
        model="claude-3-opus-20240229",
        input_cost_per_1m_tokens=Decimal("15.00"),
        output_cost_per_1m_tokens=Decimal("75.00"),
        cache_read_cost_per_1m_tokens=Decimal("1.50"),
        cache_write_cost_per_1m_tokens=Decimal("18.75"),
        pricing_url="https://www.anthropic.com/pricing",
        last_verified=date(2025, 1, 1),
    ),
    # Source: https://ai.google.dev/pricing
    "gemini-1.5-pro": ModelPricing(
        provider="google",
        model="gemini-1.5-pro",
        input_cost_per_1m_tokens=Decimal("1.25"),
        output_cost_per_1m_tokens=Decimal("5.00"),
        cache_read_cost_per_1m_tokens=Decimal("0.3125"),
        cache_write_cost_per_1m_tokens=None,
        pricing_url="https://ai.google.dev/pricing",
        last_verified=date(2025, 1, 1),
    ),
    "gemini-1.5-flash": ModelPricing(
        provider="google",
        model="gemini-1.5-flash",
        input_cost_per_1m_tokens=Decimal("0.075"),
        output_cost_per_1m_tokens=Decimal("0.30"),
        cache_read_cost_per_1m_tokens=Decimal("0.01875"),
        cache_write_cost_per_1m_tokens=None,
        pricing_url="https://ai.google.dev/pricing",
        last_verified=date(2025, 1, 1),
    ),
}
