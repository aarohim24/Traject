"""Unit tests for traject.router.routing_table.

Validates: Requirements 2.1, 2.2 (routing table completeness and model map).

**Validates: Requirements 2.1, 2.2**
"""

from __future__ import annotations

import pytest

from traject.router.routing_table import (
    DEFAULT_MODEL_MAP,
    DEFAULT_ROUTING_TABLE,
    ComplexityTier,
    ModelTier,
    RoutingDecision,
    complexity_score_to_tier,
)
from traject.router.task_classifier import TaskType

# ---------------------------------------------------------------------------
# complexity_score_to_tier — boundary conditions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "expected_tier"),
    [
        (0.0, ComplexityTier.LOW),
        (0.20, ComplexityTier.LOW),
        (0.39, ComplexityTier.LOW),
        (0.40, ComplexityTier.MEDIUM),
        (0.55, ComplexityTier.MEDIUM),
        (0.69, ComplexityTier.MEDIUM),
        (0.70, ComplexityTier.HIGH),
        (0.85, ComplexityTier.HIGH),
        (1.0, ComplexityTier.HIGH),
    ],
)
def test_complexity_score_to_tier_boundaries(
    score: float, expected_tier: ComplexityTier
) -> None:
    """complexity_score_to_tier maps scores to the correct complexity tier."""
    result = complexity_score_to_tier(score)
    assert result == expected_tier, (
        f"score={score} → expected {expected_tier!r}, got {result!r}"
    )


# ---------------------------------------------------------------------------
# DEFAULT_ROUTING_TABLE — completeness: all 10 TaskTypes x 3 ComplexityTiers
# ---------------------------------------------------------------------------


def test_default_routing_table_covers_all_task_types() -> None:
    """DEFAULT_ROUTING_TABLE has an entry for every TaskType."""
    for task_type in TaskType:
        assert task_type in DEFAULT_ROUTING_TABLE, (
            f"TaskType.{task_type.name} is missing from DEFAULT_ROUTING_TABLE"
        )


def test_default_routing_table_covers_all_complexity_tiers_for_each_task_type() -> None:
    """Every TaskType entry in DEFAULT_ROUTING_TABLE covers all 3 ComplexityTiers."""
    for task_type in TaskType:
        tier_map = DEFAULT_ROUTING_TABLE[task_type]
        for complexity_tier in ComplexityTier:
            assert complexity_tier in tier_map, (
                f"DEFAULT_ROUTING_TABLE[{task_type.name}] missing "
                f"ComplexityTier.{complexity_tier.name}"
            )


def test_default_routing_table_values_are_model_tiers() -> None:
    """Every value in DEFAULT_ROUTING_TABLE is a valid ModelTier member."""
    for task_type, tier_map in DEFAULT_ROUTING_TABLE.items():
        for complexity_tier, model_tier in tier_map.items():
            assert isinstance(model_tier, ModelTier), (
                f"DEFAULT_ROUTING_TABLE[{task_type}][{complexity_tier}] = "
                f"{model_tier!r} is not a ModelTier"
            )


# ---------------------------------------------------------------------------
# Specific routing table rules from the spec
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("task_type", "complexity_tier", "expected_model_tier"),
    [
        # Simple tasks cap at TIER_2
        (TaskType.SUMMARIZATION, ComplexityTier.LOW, ModelTier.TIER_1),
        (TaskType.SUMMARIZATION, ComplexityTier.MEDIUM, ModelTier.TIER_1),
        (TaskType.SUMMARIZATION, ComplexityTier.HIGH, ModelTier.TIER_2),
        (TaskType.CLASSIFICATION, ComplexityTier.LOW, ModelTier.TIER_1),
        (TaskType.CLASSIFICATION, ComplexityTier.HIGH, ModelTier.TIER_2),
        (TaskType.EXTRACTION, ComplexityTier.LOW, ModelTier.TIER_1),
        (TaskType.TRANSLATION, ComplexityTier.LOW, ModelTier.TIER_1),
        (TaskType.TRANSLATION, ComplexityTier.HIGH, ModelTier.TIER_2),
        # Complex tasks reach TIER_3
        (TaskType.CODE_GENERATION, ComplexityTier.HIGH, ModelTier.TIER_3),
        (TaskType.CODE_GENERATION, ComplexityTier.MEDIUM, ModelTier.TIER_2),
        (TaskType.CODE_GENERATION, ComplexityTier.LOW, ModelTier.TIER_1),
        (TaskType.REASONING, ComplexityTier.HIGH, ModelTier.TIER_3),
        (TaskType.REASONING, ComplexityTier.MEDIUM, ModelTier.TIER_2),
        (TaskType.CREATIVE_WRITING, ComplexityTier.HIGH, ModelTier.TIER_3),
        # UNKNOWN is always TIER_2
        (TaskType.UNKNOWN, ComplexityTier.LOW, ModelTier.TIER_2),
        (TaskType.UNKNOWN, ComplexityTier.MEDIUM, ModelTier.TIER_2),
        (TaskType.UNKNOWN, ComplexityTier.HIGH, ModelTier.TIER_2),
    ],
)
def test_default_routing_table_specific_rules(
    task_type: TaskType, complexity_tier: ComplexityTier, expected_model_tier: ModelTier
) -> None:
    """DEFAULT_ROUTING_TABLE entries match the spec-defined routing rules."""
    result = DEFAULT_ROUTING_TABLE[task_type][complexity_tier]
    assert result == expected_model_tier, (
        f"DEFAULT_ROUTING_TABLE[{task_type.name}][{complexity_tier.name}] = "
        f"{result!r}, expected {expected_model_tier!r}"
    )


# ---------------------------------------------------------------------------
# DEFAULT_MODEL_MAP — completeness and correct model identifiers
# ---------------------------------------------------------------------------


def test_default_model_map_has_openai_and_anthropic() -> None:
    """DEFAULT_MODEL_MAP contains entries for openai and anthropic."""
    assert "openai" in DEFAULT_MODEL_MAP
    assert "anthropic" in DEFAULT_MODEL_MAP


def test_default_model_map_covers_all_tiers_for_openai() -> None:
    """openai entry in DEFAULT_MODEL_MAP covers all ModelTier values."""
    for tier in ModelTier:
        assert tier in DEFAULT_MODEL_MAP["openai"], (
            f"DEFAULT_MODEL_MAP['openai'] missing ModelTier.{tier.name}"
        )


def test_default_model_map_covers_all_tiers_for_anthropic() -> None:
    """anthropic entry in DEFAULT_MODEL_MAP covers all ModelTier values."""
    for tier in ModelTier:
        assert tier in DEFAULT_MODEL_MAP["anthropic"], (
            f"DEFAULT_MODEL_MAP['anthropic'] missing ModelTier.{tier.name}"
        )


@pytest.mark.parametrize(
    ("provider", "tier", "expected_model"),
    [
        ("openai", ModelTier.TIER_1, "gpt-4o-mini"),
        ("openai", ModelTier.TIER_2, "gpt-4o"),
        ("openai", ModelTier.TIER_3, "gpt-4o"),
        ("anthropic", ModelTier.TIER_1, "claude-3-5-haiku-20241022"),
        ("anthropic", ModelTier.TIER_2, "claude-3-5-sonnet-20241022"),
        ("anthropic", ModelTier.TIER_3, "claude-3-opus-20240229"),
    ],
)
def test_default_model_map_correct_model_identifiers(
    provider: str, tier: ModelTier, expected_model: str
) -> None:
    """DEFAULT_MODEL_MAP maps providers and tiers to the correct model identifiers."""
    result = DEFAULT_MODEL_MAP[provider][tier]
    assert result == expected_model, (
        f"DEFAULT_MODEL_MAP[{provider!r}][{tier.name}] = {result!r}, "
        f"expected {expected_model!r}"
    )


# ---------------------------------------------------------------------------
# RoutingDecision dataclass
# ---------------------------------------------------------------------------


def test_routing_decision_is_frozen() -> None:
    """RoutingDecision is a frozen dataclass — mutation raises FrozenInstanceError."""
    decision = RoutingDecision(
        original_model="gpt-4o",
        selected_model="gpt-4o-mini",
        task_type=TaskType.SUMMARIZATION,
        complexity_score=0.1,
        complexity_tier=ComplexityTier.LOW,
        model_tier=ModelTier.TIER_1,
        routing_rule="summarization.low → tier_1",
        cost_delta_pct=-94.0,
        ab_test_group=None,
    )
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.selected_model = "gpt-4o"  # type: ignore[misc]


def test_routing_decision_ab_test_group_can_be_none() -> None:
    """RoutingDecision.ab_test_group accepts None."""
    decision = RoutingDecision(
        original_model="x",
        selected_model="x",
        task_type=TaskType.UNKNOWN,
        complexity_score=0.0,
        complexity_tier=ComplexityTier.LOW,
        model_tier=ModelTier.TIER_2,
        routing_rule="unknown.low → tier_2",
        cost_delta_pct=0.0,
        ab_test_group=None,
    )
    assert decision.ab_test_group is None
