"""Compression strategy definitions, defaults, and validation for the Axon SDK.

This module defines the three built-in compression strategies (CONSERVATIVE,
MODERATE, AGGRESSIVE), the frozen ``CompressionConfig`` dataclass that
parameterises a compression run, the ``STRATEGY_DEFAULTS`` mapping that
provides ready-to-use configs for each strategy, and the ``validate_config``
helper that enforces field-level invariants at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from axon.exceptions import AxonConfigError


class CompressionStrategy(StrEnum):
    """Enumeration of the available trajectory-compression strategies.

    Each member controls how aggressively older or lower-relevance segments
    are summarised or dropped during a compression run.  All three strategies
    leave system prompts and the most-recent turns untouched by default.

    Attributes:
        CONSERVATIVE: Minimal compression; only very low-relevance TOOL_RESULT
            and REASONING_BLOCK segments are touched.  Safe default for
            production traffic where context fidelity is paramount.
        MODERATE: Balanced compression; additionally drops low-relevance
            RAG_CHUNK segments.  Good starting point for cost-sensitive
            workloads.
        AGGRESSIVE: Maximum compression; also prunes FEW_SHOT_EXAMPLE
            segments.  Best suited for long-running agentic pipelines that
            accumulate large amounts of scaffolding content.
    """

    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


@dataclass(frozen=True)
class CompressionConfig:
    """Immutable configuration for a single compression pipeline run.

    Instances are created either via ``STRATEGY_DEFAULTS`` or by constructing
    directly with custom field values.  Pass a ``CompressionConfig`` to
    ``axon.compression.engine.compress`` to control how the pipeline behaves.

    Attributes:
        strategy: The named strategy this config implements.
        target_reduction_pct: Desired fraction of tokens to remove, expressed
            as a value in the open interval ``(0.0, 1.0)``.  For example,
            ``0.20`` means "aim to remove 20 % of tokens".
        min_turns_protected: Minimum number of the most-recent
            user/assistant turn pairs that must be preserved in full,
            regardless of their relevance scores.  Must be ``>= 0``.
        protect_system_prompt: When ``True`` (required in Phase 1), the
            system prompt is always retained verbatim.
        shadow_mode: When ``True``, the compression pipeline runs but its
            output is discarded — the original messages are returned to the
            caller.  Use this to observe what would be compressed without
            altering live traffic.
    """

    strategy: CompressionStrategy
    target_reduction_pct: float
    min_turns_protected: int
    protect_system_prompt: bool
    shadow_mode: bool


STRATEGY_DEFAULTS: dict[CompressionStrategy, CompressionConfig] = {
    CompressionStrategy.CONSERVATIVE: CompressionConfig(
        strategy=CompressionStrategy.CONSERVATIVE,
        target_reduction_pct=0.20,
        min_turns_protected=3,
        protect_system_prompt=True,
        shadow_mode=True,
    ),
    CompressionStrategy.MODERATE: CompressionConfig(
        strategy=CompressionStrategy.MODERATE,
        target_reduction_pct=0.35,
        min_turns_protected=3,
        protect_system_prompt=True,
        shadow_mode=True,
    ),
    CompressionStrategy.AGGRESSIVE: CompressionConfig(
        strategy=CompressionStrategy.AGGRESSIVE,
        target_reduction_pct=0.55,
        min_turns_protected=2,
        protect_system_prompt=True,
        shadow_mode=True,
    ),
}


def get_config(strategy: CompressionStrategy) -> CompressionConfig:
    """Return the default ``CompressionConfig`` for a given strategy.

    Args:
        strategy: The ``CompressionStrategy`` member whose default config
            should be returned.

    Returns:
        The pre-built ``CompressionConfig`` associated with *strategy* in
        ``STRATEGY_DEFAULTS``.
    """
    return STRATEGY_DEFAULTS[strategy]


def validate_config(config: CompressionConfig) -> None:
    """Validate a ``CompressionConfig`` and raise if any field is invalid.

    This function is a no-op when all fields satisfy their invariants.
    It is called by the compression engine before every pipeline run so
    that misconfigured callers receive an actionable error immediately
    rather than a silent wrong result.

    Args:
        config: The ``CompressionConfig`` instance to validate.

    Raises:
        AxonConfigError: If ``target_reduction_pct`` is not in the open
            interval ``(0.0, 1.0)``.
        AxonConfigError: If ``min_turns_protected`` is negative.
        AxonConfigError: If ``protect_system_prompt`` is ``False`` (not
            supported in Phase 1).
    """
    if not 0.0 < config.target_reduction_pct < 1.0:
        raise AxonConfigError(
            f"target_reduction_pct must be in (0.0, 1.0), got "
            f"{config.target_reduction_pct}. Use a value like 0.20 for 20% reduction."
        )
    if config.min_turns_protected < 0:
        raise AxonConfigError(
            f"min_turns_protected must be >= 0, got {config.min_turns_protected}."
        )
    if not config.protect_system_prompt:
        raise AxonConfigError(
            "protect_system_prompt must be True. Disabling system prompt "
            "protection is not supported in Phase 1."
        )
