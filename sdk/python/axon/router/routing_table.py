"""Routing table definitions for the Axon adaptive model router.

Defines model tiers, complexity tiers, the ``RoutingDecision`` dataclass, and
the default routing table and model map that map (TaskType, ComplexityTier)
pairs to concrete provider model identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from axon.router.task_classifier import TaskType

if TYPE_CHECKING:
    pass


class ModelTier(StrEnum):
    """Enumeration of model capability tiers supported by the router.

    Attributes:
        TIER_1: Lightest, cheapest model for simple tasks.
        TIER_2: Mid-range model for moderately complex tasks.
        TIER_3: Most capable model for highly complex tasks.
    """

    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class ComplexityTier(StrEnum):
    """Enumeration of request complexity levels derived from a float score.

    Complexity score ranges:
        LOW:    0.0 - 0.39
        MEDIUM: 0.40 - 0.69
        HIGH:   0.70 - 1.0

    Attributes:
        LOW: Score in [0.0, 0.39].
        MEDIUM: Score in [0.40, 0.69].
        HIGH: Score in [0.70, 1.0].
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def complexity_score_to_tier(score: float) -> ComplexityTier:
    """Convert a float complexity score into a ``ComplexityTier`` enum value.

    Args:
        score: A float in [0.0, 1.0] as returned by
            ``estimate_complexity``. Values outside this range are
            clamped to the nearest boundary tier.

    Returns:
        ``ComplexityTier.LOW`` for scores 0.0-0.39,
        ``ComplexityTier.MEDIUM`` for 0.40-0.69,
        ``ComplexityTier.HIGH`` for 0.70-1.0.
    """
    if score < 0.40:
        return ComplexityTier.LOW
    if score < 0.70:
        return ComplexityTier.MEDIUM
    return ComplexityTier.HIGH


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable record describing a single model routing decision.

    Attributes:
        original_model: The model string originally requested by the
            caller (e.g. ``"gpt-4o"``).
        selected_model: The model string chosen by the router after
            applying routing rules and any A/B assignment.
        task_type: The ``TaskType`` inferred (or overridden) for this
            request.
        complexity_score: Raw float score in [0.0, 1.0] from
            ``estimate_complexity``.
        complexity_tier: The ``ComplexityTier`` derived from
            ``complexity_score``.
        model_tier: The ``ModelTier`` looked up from the routing table
            for this (task_type, complexity_tier) pair.
        routing_rule: Human-readable description of the rule that was
            applied, e.g. ``"summarization.low → tier_1"``.
        cost_delta_pct: Signed percentage change in estimated input-token
            cost versus the originally requested model. Negative values
            indicate cost savings.
        ab_test_group: A/B test group assignment for this request:
            ``"control"``, ``"treatment"``, or ``None`` when no A/B
            test is configured.
    """

    original_model: str
    selected_model: str
    task_type: TaskType
    complexity_score: float
    complexity_tier: ComplexityTier
    model_tier: ModelTier
    routing_rule: str
    cost_delta_pct: float
    ab_test_group: str | None


# ---------------------------------------------------------------------------
# Default routing table
# ---------------------------------------------------------------------------
# Maps each (TaskType, ComplexityTier) pair to a ModelTier.
# ---------------------------------------------------------------------------

DEFAULT_ROUTING_TABLE: dict[TaskType, dict[ComplexityTier, ModelTier]] = {
    TaskType.SUMMARIZATION: {
        ComplexityTier.LOW: ModelTier.TIER_1,
        ComplexityTier.MEDIUM: ModelTier.TIER_1,
        ComplexityTier.HIGH: ModelTier.TIER_2,
    },
    TaskType.CLASSIFICATION: {
        ComplexityTier.LOW: ModelTier.TIER_1,
        ComplexityTier.MEDIUM: ModelTier.TIER_1,
        ComplexityTier.HIGH: ModelTier.TIER_2,
    },
    TaskType.EXTRACTION: {
        ComplexityTier.LOW: ModelTier.TIER_1,
        ComplexityTier.MEDIUM: ModelTier.TIER_1,
        ComplexityTier.HIGH: ModelTier.TIER_2,
    },
    TaskType.TRANSLATION: {
        ComplexityTier.LOW: ModelTier.TIER_1,
        ComplexityTier.MEDIUM: ModelTier.TIER_1,
        ComplexityTier.HIGH: ModelTier.TIER_2,
    },
    TaskType.QUESTION_ANSWERING: {
        ComplexityTier.LOW: ModelTier.TIER_1,
        ComplexityTier.MEDIUM: ModelTier.TIER_2,
        ComplexityTier.HIGH: ModelTier.TIER_2,
    },
    TaskType.CODE_REVIEW: {
        ComplexityTier.LOW: ModelTier.TIER_1,
        ComplexityTier.MEDIUM: ModelTier.TIER_2,
        ComplexityTier.HIGH: ModelTier.TIER_2,
    },
    TaskType.CODE_GENERATION: {
        ComplexityTier.LOW: ModelTier.TIER_1,
        ComplexityTier.MEDIUM: ModelTier.TIER_2,
        ComplexityTier.HIGH: ModelTier.TIER_3,
    },
    TaskType.REASONING: {
        ComplexityTier.LOW: ModelTier.TIER_1,
        ComplexityTier.MEDIUM: ModelTier.TIER_2,
        ComplexityTier.HIGH: ModelTier.TIER_3,
    },
    TaskType.CREATIVE_WRITING: {
        ComplexityTier.LOW: ModelTier.TIER_1,
        ComplexityTier.MEDIUM: ModelTier.TIER_2,
        ComplexityTier.HIGH: ModelTier.TIER_3,
    },
    TaskType.UNKNOWN: {
        ComplexityTier.LOW: ModelTier.TIER_2,
        ComplexityTier.MEDIUM: ModelTier.TIER_2,
        ComplexityTier.HIGH: ModelTier.TIER_2,
    },
}

# ---------------------------------------------------------------------------
# Default model map
# ---------------------------------------------------------------------------
# Maps each (provider, ModelTier) pair to a concrete model identifier.
# ---------------------------------------------------------------------------

DEFAULT_MODEL_MAP: dict[str, dict[ModelTier, str]] = {
    "openai": {
        ModelTier.TIER_1: "gpt-4o-mini",
        ModelTier.TIER_2: "gpt-4o",
        ModelTier.TIER_3: "gpt-4o",
    },
    "anthropic": {
        ModelTier.TIER_1: "claude-3-5-haiku-20241022",
        ModelTier.TIER_2: "claude-3-5-sonnet-20241022",
        ModelTier.TIER_3: "claude-3-opus-20240229",
    },
}
