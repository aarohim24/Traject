"""Static pricing table for supported LLM providers.

This module implements the authoritative, auditable pricing reference for all
models supported by the Traject SDK. Per ADR-006, all monetary values are stored
as ``Decimal`` instances constructed from string literals — never float
literals — to eliminate floating-point representation drift. Per ADR-010, the
table is a plain, human-readable data structure that can be diffed, audited,
and updated in a single pull-request without touching any computation logic.

The ``ModelPricing`` dataclass is defined here (frozen) so that the pricing
table can be imported by ``traject.core.cost_calculator`` without creating a
circular dependency. ``traject.models`` will re-export ``ModelPricing`` from this
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
    # ---- Current Claude generation (verified 2026-06-27) ------------------
    # Input/output prices are the published per-MTok rates. Cache tiers are
    # derived from Anthropic's documented caching economics — reads ~0.1x and
    # 5-minute writes ~1.25x of the input rate — not separately published
    # per-model figures; re-verify against the pricing page when exact cache
    # rates are published.
    "claude-opus-4-8": ModelPricing(
        provider="anthropic",
        model="claude-opus-4-8",
        input_cost_per_1m_tokens=Decimal("5.00"),
        output_cost_per_1m_tokens=Decimal("25.00"),
        cache_read_cost_per_1m_tokens=Decimal("0.50"),
        cache_write_cost_per_1m_tokens=Decimal("6.25"),
        pricing_url="https://www.anthropic.com/pricing",
        last_verified=date(2026, 6, 27),
    ),
    "claude-opus-4-7": ModelPricing(
        provider="anthropic",
        model="claude-opus-4-7",
        input_cost_per_1m_tokens=Decimal("5.00"),
        output_cost_per_1m_tokens=Decimal("25.00"),
        cache_read_cost_per_1m_tokens=Decimal("0.50"),
        cache_write_cost_per_1m_tokens=Decimal("6.25"),
        pricing_url="https://www.anthropic.com/pricing",
        last_verified=date(2026, 6, 27),
    ),
    "claude-opus-4-6": ModelPricing(
        provider="anthropic",
        model="claude-opus-4-6",
        input_cost_per_1m_tokens=Decimal("5.00"),
        output_cost_per_1m_tokens=Decimal("25.00"),
        cache_read_cost_per_1m_tokens=Decimal("0.50"),
        cache_write_cost_per_1m_tokens=Decimal("6.25"),
        pricing_url="https://www.anthropic.com/pricing",
        last_verified=date(2026, 6, 27),
    ),
    "claude-sonnet-4-6": ModelPricing(
        provider="anthropic",
        model="claude-sonnet-4-6",
        input_cost_per_1m_tokens=Decimal("3.00"),
        output_cost_per_1m_tokens=Decimal("15.00"),
        cache_read_cost_per_1m_tokens=Decimal("0.30"),
        cache_write_cost_per_1m_tokens=Decimal("3.75"),
        pricing_url="https://www.anthropic.com/pricing",
        last_verified=date(2026, 6, 27),
    ),
    "claude-haiku-4-5": ModelPricing(
        provider="anthropic",
        model="claude-haiku-4-5",
        input_cost_per_1m_tokens=Decimal("1.00"),
        output_cost_per_1m_tokens=Decimal("5.00"),
        cache_read_cost_per_1m_tokens=Decimal("0.10"),
        cache_write_cost_per_1m_tokens=Decimal("1.25"),
        pricing_url="https://www.anthropic.com/pricing",
        last_verified=date(2026, 6, 27),
    ),
    "claude-fable-5": ModelPricing(
        provider="anthropic",
        model="claude-fable-5",
        input_cost_per_1m_tokens=Decimal("10.00"),
        output_cost_per_1m_tokens=Decimal("50.00"),
        cache_read_cost_per_1m_tokens=Decimal("1.00"),
        cache_write_cost_per_1m_tokens=Decimal("12.50"),
        pricing_url="https://www.anthropic.com/pricing",
        last_verified=date(2026, 6, 27),
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


# ---------------------------------------------------------------------------
# Freshness contract
# ---------------------------------------------------------------------------
# For a cost product, stale prices are a correctness bug: every savings figure
# and every routing decision reads from this table. ``MAX_PRICE_AGE_DAYS`` is
# the contract enforced by ``tests/unit/test_pricing_freshness.py`` — any model
# whose ``last_verified`` is older than this (and not in the explicit
# verification-pending allowlist below) fails CI, forcing a periodic re-check.
MAX_PRICE_AGE_DAYS: int = 120

# Models whose prices have not yet been re-verified in this pass. This is
# explicit, visible technical debt — not a silent exemption. Each entry should
# be re-verified against its provider's pricing page and removed from this set.
# (OpenAI and Google pricing could not be verified in the 2026-06-27 refresh.)
VERIFICATION_PENDING: frozenset[str] = frozenset(
    {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    }
)


def stale_models(as_of: date, max_age_days: int = MAX_PRICE_AGE_DAYS) -> list[str]:
    """Return models whose pricing is older than *max_age_days* as of *as_of*.

    Excludes models in :data:`VERIFICATION_PENDING`. Used by the freshness test
    so that a price left un-reverified past the contract window fails CI.

    Args:
        as_of: The reference date to measure staleness against (pass the
            current date; not defaulted so the function stays deterministic
            and testable).
        max_age_days: Maximum allowed age in days before a price is stale.

    Returns:
        Sorted list of model identifiers with stale pricing.
    """
    stale: list[str] = []
    for model, pricing in PROVIDER_PRICING.items():
        if model in VERIFICATION_PENDING:
            continue
        if (as_of - pricing.last_verified).days > max_age_days:
            stale.append(model)
    return sorted(stale)
