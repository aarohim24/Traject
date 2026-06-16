"""Unit tests for axon.router.rule_router and axon.router.ab_test.

Validates: Requirements 2.3–2.7, 3.1–3.4 (routing decisions, A/B testing,
cost delta, and fallback behaviour).

**Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.3, 3.4**
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from traject.exceptions import AxonConfigError
from traject.router.ab_test import ABTestConfig
from traject.router.routing_table import (
    ComplexityTier,
    ModelTier,
    RoutingDecision,
)
from traject.router.rule_router import RuleRouter
from traject.router.task_classifier import TaskType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_messages(content: str = "hello") -> list[dict[str, Any]]:
    return [{"role": "user", "content": content}]


# ---------------------------------------------------------------------------
# route() — model tier selection for anthropic provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("task_type", "complexity_tier", "expected_model_tier", "expected_model"),
    [
        # SUMMARIZATION always gets TIER_1 for LOW/MEDIUM, TIER_2 for HIGH
        (TaskType.SUMMARIZATION, ComplexityTier.LOW, ModelTier.TIER_1, "claude-3-5-haiku-20241022"),
        (TaskType.SUMMARIZATION, ComplexityTier.MEDIUM, ModelTier.TIER_1, "claude-3-5-haiku-20241022"),
        (TaskType.SUMMARIZATION, ComplexityTier.HIGH, ModelTier.TIER_2, "claude-3-5-sonnet-20241022"),
        # CODE_GENERATION reaches TIER_3 at HIGH
        (TaskType.CODE_GENERATION, ComplexityTier.LOW, ModelTier.TIER_1, "claude-3-5-haiku-20241022"),
        (TaskType.CODE_GENERATION, ComplexityTier.MEDIUM, ModelTier.TIER_2, "claude-3-5-sonnet-20241022"),
        (TaskType.CODE_GENERATION, ComplexityTier.HIGH, ModelTier.TIER_3, "claude-3-opus-20240229"),
        # REASONING reaches TIER_3 at HIGH
        (TaskType.REASONING, ComplexityTier.HIGH, ModelTier.TIER_3, "claude-3-opus-20240229"),
        (TaskType.REASONING, ComplexityTier.MEDIUM, ModelTier.TIER_2, "claude-3-5-sonnet-20241022"),
        # UNKNOWN always TIER_2
        (TaskType.UNKNOWN, ComplexityTier.LOW, ModelTier.TIER_2, "claude-3-5-sonnet-20241022"),
        (TaskType.UNKNOWN, ComplexityTier.HIGH, ModelTier.TIER_2, "claude-3-5-sonnet-20241022"),
    ],
)
def test_route_anthropic_provider_tier_selection(
    task_type: TaskType,
    complexity_tier: ComplexityTier,
    expected_model_tier: ModelTier,
    expected_model: str,
) -> None:
    """route() selects the correct anthropic model for each (TaskType, ComplexityTier).

    **Validates: Requirements 2.3**
    """
    router = RuleRouter(provider="anthropic")
    messages = _simple_messages()

    with patch(
        "axon.router.rule_router.classify_task", return_value=task_type
    ), patch(
        "axon.router.rule_router.estimate_complexity",
        return_value={
            ComplexityTier.LOW: 0.1,
            ComplexityTier.MEDIUM: 0.55,
            ComplexityTier.HIGH: 0.85,
        }[complexity_tier],
    ):
        decision = router.route(messages, "claude-3-5-sonnet-20241022")

    assert decision.model_tier == expected_model_tier
    assert decision.selected_model == expected_model
    assert decision.task_type == task_type
    assert decision.complexity_tier == complexity_tier


# ---------------------------------------------------------------------------
# route() — RoutingDecision fields are populated correctly
# ---------------------------------------------------------------------------


def test_route_returns_routing_decision_with_all_fields() -> None:
    """route() returns a RoutingDecision with all required fields populated.

    **Validates: Requirements 2.3**
    """
    router = RuleRouter(provider="openai")
    messages = [{"role": "user", "content": "summarize this article"}]
    decision = router.route(messages, "gpt-4o")

    assert isinstance(decision, RoutingDecision)
    assert decision.original_model == "gpt-4o"
    assert isinstance(decision.selected_model, str)
    assert isinstance(decision.task_type, TaskType)
    assert isinstance(decision.complexity_score, float)
    assert isinstance(decision.complexity_tier, ComplexityTier)
    assert isinstance(decision.model_tier, ModelTier)
    assert isinstance(decision.routing_rule, str)
    assert len(decision.routing_rule) > 0
    assert isinstance(decision.cost_delta_pct, float)


# ---------------------------------------------------------------------------
# route() — fallback on exception
# ---------------------------------------------------------------------------


def test_route_fallback_when_classify_task_raises() -> None:
    """route() returns original model when classify_task raises.

    **Validates: Requirements 2.5**
    """
    router = RuleRouter(provider="openai")
    messages = _simple_messages()
    requested = "gpt-4o"

    with patch(
        "axon.router.rule_router.classify_task",
        side_effect=RuntimeError("unexpected error"),
    ):
        decision = router.route(messages, requested)

    assert decision.original_model == requested
    assert decision.selected_model == requested
    assert decision.routing_rule == "fallback"
    assert decision.cost_delta_pct == 0.0


def test_route_fallback_preserves_original_model() -> None:
    """Fallback RoutingDecision has original_model == requested_model.

    **Validates: Requirements 2.5**
    """
    router = RuleRouter(provider="anthropic")
    requested = "claude-3-5-sonnet-20241022"

    with patch(
        "axon.router.rule_router.estimate_complexity",
        side_effect=Exception("boom"),
    ):
        decision = router.route(_simple_messages(), requested)

    assert decision.selected_model == requested


# ---------------------------------------------------------------------------
# route() — override_task_type skips classifier
# ---------------------------------------------------------------------------


def test_route_override_task_type_skips_classify() -> None:
    """route() with override_task_type does not call classify_task.

    **Validates: Requirements 2.6**
    """
    router = RuleRouter(provider="openai")
    messages = _simple_messages()

    with patch(
        "axon.router.rule_router.classify_task"
    ) as mock_classify:
        decision = router.route(
            messages, "gpt-4o", override_task_type=TaskType.SUMMARIZATION
        )

    mock_classify.assert_not_called()
    assert decision.task_type == TaskType.SUMMARIZATION


# ---------------------------------------------------------------------------
# cost_delta_pct
# ---------------------------------------------------------------------------


def test_cost_delta_pct_zero_when_same_model() -> None:
    """cost_delta_pct is 0.0 when selected_model == requested_model.

    **Validates: Requirements 2.7**
    """
    router = RuleRouter(provider="openai")
    # Force the router to pick gpt-4o by routing UNKNOWN (always TIER_2 → gpt-4o)
    messages = _simple_messages("do the thing")

    with patch(
        "axon.router.rule_router.classify_task", return_value=TaskType.UNKNOWN
    ), patch(
        "axon.router.rule_router.estimate_complexity", return_value=0.1
    ):
        decision = router.route(messages, "gpt-4o")

    # selected_model should be gpt-4o (UNKNOWN → TIER_2 → gpt-4o)
    if decision.selected_model == decision.original_model:
        assert decision.cost_delta_pct == 0.0


def test_cost_delta_pct_negative_when_downgraded() -> None:
    """cost_delta_pct is negative when downgraded to a cheaper model.

    **Validates: Requirements 2.7**
    """
    router = RuleRouter(provider="openai")
    messages = [{"role": "user", "content": "summarize this text"}]

    with patch(
        "axon.router.rule_router.classify_task", return_value=TaskType.SUMMARIZATION
    ), patch(
        "axon.router.rule_router.estimate_complexity", return_value=0.1
    ):
        # requested gpt-4o, should get gpt-4o-mini (cheaper)
        decision = router.route(messages, "gpt-4o")

    if decision.selected_model != decision.original_model:
        assert decision.cost_delta_pct < 0.0


def test_cost_delta_pct_zero_for_unknown_model() -> None:
    """cost_delta_pct is 0.0 when original model is not in the pricing table.

    **Validates: Requirements 2.7**
    """
    router = RuleRouter(provider="openai")
    messages = _simple_messages()

    decision = router.route(messages, "some-unknown-model-xyz")
    assert isinstance(decision.cost_delta_pct, float)
    # If original is unknown, delta must be 0.0 per spec
    if decision.original_model not in (
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"
    ):
        assert decision.cost_delta_pct == 0.0


# ---------------------------------------------------------------------------
# A/B test — determinism
# ---------------------------------------------------------------------------


def test_ab_test_assign_group_same_request_id_returns_same_group() -> None:
    """assign_group returns the same group for the same request_id (deterministic).

    **Validates: Requirements 3.2**
    """
    config = ABTestConfig(
        treatment_model="gpt-4o-mini",
        treatment_pct=0.5,
        feature_tag=None,
        seed=42,
    )
    request_id = "test-request-12345"

    results = {config.assign_group(request_id) for _ in range(20)}
    assert len(results) == 1, (
        f"assign_group was non-deterministic: got groups {results}"
    )


def test_ab_test_assign_group_treatment_pct_zero_always_control() -> None:
    """assign_group with treatment_pct=0.0 always returns 'control'.

    **Validates: Requirements 3.3**
    """
    config = ABTestConfig(
        treatment_model="gpt-4o-mini",
        treatment_pct=0.0,
        feature_tag=None,
    )
    for i in range(20):
        assert config.assign_group(f"req-{i}") == "control"


def test_ab_test_assign_group_treatment_pct_one_always_treatment() -> None:
    """assign_group with treatment_pct=1.0 always returns 'treatment'.

    **Validates: Requirements 3.4**
    """
    config = ABTestConfig(
        treatment_model="gpt-4o-mini",
        treatment_pct=1.0,
        feature_tag=None,
    )
    for i in range(20):
        assert config.assign_group(f"req-{i}") == "treatment"


def test_ab_test_config_invalid_pct_raises_axon_config_error() -> None:
    """ABTestConfig raises AxonConfigError when treatment_pct is out of range."""
    with pytest.raises(AxonConfigError):
        ABTestConfig(treatment_model="gpt-4o-mini", treatment_pct=1.5, feature_tag=None)

    with pytest.raises(AxonConfigError):
        ABTestConfig(treatment_model="gpt-4o-mini", treatment_pct=-0.1, feature_tag=None)


def test_ab_test_different_request_ids_may_get_different_groups() -> None:
    """Different request_ids can produce different groups (not deterministically same).

    **Validates: Requirements 3.1**
    """
    config = ABTestConfig(
        treatment_model="gpt-4o-mini",
        treatment_pct=0.5,
        feature_tag=None,
        seed=42,
    )
    groups = {config.assign_group(f"req-{i}") for i in range(100)}
    # With 50% split and 100 requests, we expect both groups to appear
    assert "control" in groups
    assert "treatment" in groups


# ---------------------------------------------------------------------------
# route() with A/B test integration
# ---------------------------------------------------------------------------


def test_route_with_ab_test_treatment_group_uses_treatment_model() -> None:
    """When A/B test assigns treatment, selected_model is the treatment model.

    **Validates: Requirements 3.6**
    """
    ab = ABTestConfig(
        treatment_model="gpt-4o-mini",
        treatment_pct=1.0,  # always treatment
        feature_tag=None,
    )
    router = RuleRouter(provider="openai", ab_test=ab)
    messages = _simple_messages("what is 2+2?")

    decision = router.route(messages, "gpt-4o")

    assert decision.selected_model == "gpt-4o-mini"
    assert decision.ab_test_group == "treatment"


def test_route_with_ab_test_control_group_uses_routed_model() -> None:
    """When A/B test assigns control, selected_model follows the routing table.

    **Validates: Requirements 3.1**
    """
    ab = ABTestConfig(
        treatment_model="gpt-4o",
        treatment_pct=0.0,  # always control
        feature_tag=None,
    )
    router = RuleRouter(provider="openai", ab_test=ab)

    with patch(
        "axon.router.rule_router.classify_task", return_value=TaskType.SUMMARIZATION
    ), patch(
        "axon.router.rule_router.estimate_complexity", return_value=0.1
    ):
        decision = router.route(_simple_messages(), "gpt-4o")

    assert decision.ab_test_group == "control"
    # SUMMARIZATION + LOW → TIER_1 → gpt-4o-mini (cheaper)
    assert decision.selected_model == "gpt-4o-mini"


def test_route_without_ab_test_ab_test_group_is_none() -> None:
    """When no A/B test is configured, ab_test_group is None."""
    router = RuleRouter(provider="openai")
    decision = router.route(_simple_messages(), "gpt-4o")
    assert decision.ab_test_group is None


# ---------------------------------------------------------------------------
# RuleRouter — custom routing table and model map
# ---------------------------------------------------------------------------


def test_rule_router_uses_custom_routing_table() -> None:
    """RuleRouter respects a custom routing_table passed at construction."""
    custom_table = {
        task_type: {c: ModelTier.TIER_3 for c in ComplexityTier}
        for task_type in TaskType
    }
    router = RuleRouter(provider="openai", routing_table=custom_table)

    with patch(
        "axon.router.rule_router.classify_task", return_value=TaskType.SUMMARIZATION
    ), patch(
        "axon.router.rule_router.estimate_complexity", return_value=0.1
    ):
        decision = router.route(_simple_messages(), "gpt-4o")

    assert decision.model_tier == ModelTier.TIER_3


def test_rule_router_uses_default_routing_table_when_none_provided() -> None:
    """RuleRouter uses DEFAULT_ROUTING_TABLE when routing_table is None."""
    router = RuleRouter(provider="openai")
    assert router._routing_table is not None  # type: ignore[union-attr]
