"""Rule-based model router for the Axon adaptive routing layer.

Implements ``RuleRouter``, which classifies an incoming LLM conversation by
task type and estimated complexity, looks up the appropriate model tier from a
configurable routing table, optionally applies deterministic A/B traffic
splitting, computes the cost delta versus the caller's originally requested
model, and returns an immutable ``RoutingDecision``.  The ``route`` method
is guaranteed never to raise; any internal error falls back to the original
requested model transparently.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog

from axon.core.pricing import PROVIDER_PRICING
from axon.router.ab_test import ABTestConfig
from axon.router.routing_table import (
    DEFAULT_MODEL_MAP,
    DEFAULT_ROUTING_TABLE,
    ComplexityTier,
    ModelTier,
    RoutingDecision,
    complexity_score_to_tier,
)
from axon.router.task_classifier import TaskType, classify_task, estimate_complexity

_log = structlog.get_logger(__name__)


class RuleRouter:
    """Transparent, rule-based LLM model router.

    On each call to ``route``, the router:

    1. Classifies the conversation as a ``TaskType`` (or uses the caller's
       override).
    2. Estimates the request's complexity as a float in [0.0, 1.0].
    3. Maps (task_type, complexity_tier) → ``ModelTier`` via the routing
       table.
    4. Resolves ``ModelTier`` → concrete model identifier via the model map.
    5. Optionally applies a deterministic A/B test to override the selected
       model for a configurable traffic fraction.
    6. Computes the signed cost-delta percentage versus the originally
       requested model using the static pricing table.

    The ``route`` method is guaranteed never to raise; any unhandled
    exception causes a transparent fallback ``RoutingDecision`` that
    preserves the caller's original model unchanged.

    Args:
        provider: Provider name used to look up the model map
            (e.g. ``"openai"`` or ``"anthropic"``).
        routing_table: Optional custom routing table mapping
            ``(TaskType, ComplexityTier)`` pairs to ``ModelTier`` values.
            Defaults to ``DEFAULT_ROUTING_TABLE``.
        model_map: Optional custom model map resolving
            ``(provider, ModelTier)`` to a concrete model string.
            Defaults to ``DEFAULT_MODEL_MAP``.
        ab_test: Optional ``ABTestConfig`` for deterministic A/B traffic
            splitting.  When ``None`` no A/B assignment is performed.
    """

    def __init__(
        self,
        provider: str,
        routing_table: dict[TaskType, dict[ComplexityTier, ModelTier]] | None = None,
        model_map: dict[str, dict[ModelTier, str]] | None = None,
        ab_test: ABTestConfig | None = None,
    ) -> None:
        self.provider = provider
        self._routing_table: dict[TaskType, dict[ComplexityTier, ModelTier]] = (
            routing_table if routing_table is not None else DEFAULT_ROUTING_TABLE
        )
        self._model_map: dict[str, dict[ModelTier, str]] = (
            model_map if model_map is not None else DEFAULT_MODEL_MAP
        )
        self._ab_test: ABTestConfig | None = ab_test

    def route(
        self,
        messages: list[dict[str, Any]],
        requested_model: str,
        override_task_type: TaskType | None = None,
    ) -> RoutingDecision:
        """Compute a routing decision for the given conversation.

        Never raises.  Any unhandled internal error causes a fallback
        ``RoutingDecision`` that routes to ``requested_model`` unchanged with
        a ``routing_rule`` of ``"fallback"`` and ``cost_delta_pct`` of
        ``0.0``.

        Args:
            messages: List of message dicts following the OpenAI chat
                completions schema.  Malformed or empty lists are handled
                gracefully.
            requested_model: The model identifier originally requested by
                the caller.  Used as fallback on error and as the baseline
                for ``cost_delta_pct`` computation.
            override_task_type: When set, skips heuristic classification
                and uses this value directly.  Useful for callers that
                already know the task type.

        Returns:
            An immutable ``RoutingDecision`` describing the routing outcome.
        """
        try:
            return self._route_impl(messages, requested_model, override_task_type)
        except Exception:  # broad catch is intentional — route() must never raise
            return RoutingDecision(
                original_model=requested_model,
                selected_model=requested_model,
                task_type=TaskType.UNKNOWN,
                complexity_score=0.0,
                complexity_tier=ComplexityTier.LOW,
                model_tier=ModelTier.TIER_2,
                routing_rule="fallback",
                cost_delta_pct=0.0,
                ab_test_group=None,
            )

    def _route_impl(
        self,
        messages: list[dict[str, Any]],
        requested_model: str,
        override_task_type: TaskType | None,
    ) -> RoutingDecision:
        """Core routing logic, separated so the outer wrapper can catch exceptions.

        Args:
            messages: Raw message list from the caller.
            requested_model: Caller's original model string.
            override_task_type: Optional task-type override.

        Returns:
            A fully populated ``RoutingDecision``.
        """
        task_type: TaskType = override_task_type or classify_task(messages)
        complexity_score: float = estimate_complexity(messages, task_type)
        complexity_tier: ComplexityTier = complexity_score_to_tier(complexity_score)
        model_tier: ModelTier = self._routing_table[task_type][complexity_tier]
        selected_model: str = self._model_map[self.provider][model_tier]

        routing_rule = f"{task_type.value}.{complexity_tier.value} → {model_tier.value}"

        # A/B test assignment
        ab_test_group: str | None = None
        if self._ab_test is not None:
            tag = self._ab_test.feature_tag
            if tag is None or tag == task_type.value:
                request_id = uuid4().hex
                ab_test_group = self._ab_test.assign_group(request_id)
                if ab_test_group == "treatment":
                    selected_model = self._ab_test.treatment_model

        # Cost delta computation
        cost_delta_pct = _compute_cost_delta_pct(requested_model, selected_model)

        if selected_model != requested_model:
            _log.warning(
                "axon.router.model_substituted",
                original_model=requested_model,
                selected_model=selected_model,
                routing_rule=routing_rule,
                task_type=task_type.value,
                complexity_tier=complexity_tier.value,
                cost_delta_pct=cost_delta_pct,
            )

        return RoutingDecision(
            original_model=requested_model,
            selected_model=selected_model,
            task_type=task_type,
            complexity_score=complexity_score,
            complexity_tier=complexity_tier,
            model_tier=model_tier,
            routing_rule=routing_rule,
            cost_delta_pct=cost_delta_pct,
            ab_test_group=ab_test_group,
        )

    def apply(
        self,
        decision: RoutingDecision,
        client: Any,  # Any: framework-agnostic client; could be OpenAI or Anthropic
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:  # Any: provider response type varies by framework
        """Call the provider client using the model selected by ``route``.

        Detects whether ``client`` is an OpenAI client (has a ``chat``
        attribute) or an Anthropic client and dispatches to the appropriate
        API method.

        Args:
            decision: The ``RoutingDecision`` returned by ``route``.
            client: An initialised provider client instance.  Supported:
                ``openai.OpenAI`` / ``openai.AsyncOpenAI`` (detected via
                ``hasattr(client, 'chat')``) and ``anthropic.Anthropic`` /
                ``anthropic.AsyncAnthropic``.
            messages: The message list to pass to the provider API.
            **kwargs: Additional keyword arguments forwarded verbatim to the
                provider's create method (e.g. ``temperature``, ``max_tokens``).

        Returns:
            The raw provider API response object.
        """
        if hasattr(client, "chat"):
            # OpenAI-style client
            return client.chat.completions.create(
                messages=messages,
                model=decision.selected_model,
                **kwargs,
            )
        # Anthropic-style client
        return client.messages.create(
            messages=messages,
            model=decision.selected_model,
            **kwargs,
        )


def _compute_cost_delta_pct(original_model: str, selected_model: str) -> float:
    """Compute the signed percentage cost change between two models.

    Uses the ``input_cost_per_1m_tokens`` field from
    ``axon.core.pricing.PROVIDER_PRICING`` for both models.  Returns
    ``0.0`` when either model is absent from the pricing table or when the
    original model's price is zero (to avoid division by zero).

    Args:
        original_model: The model identifier originally requested.
        selected_model: The model identifier chosen by the router.

    Returns:
        Signed float percentage: negative means cheaper, positive means
        more expensive, ``0.0`` when data is unavailable or models are
        identical.
    """
    if original_model == selected_model:
        return 0.0
    original_pricing = PROVIDER_PRICING.get(original_model)
    selected_pricing = PROVIDER_PRICING.get(selected_model)
    if original_pricing is None or selected_pricing is None:
        return 0.0
    original_cost = original_pricing.input_cost_per_1m_tokens
    if original_cost == 0:
        return 0.0
    selected_cost = selected_pricing.input_cost_per_1m_tokens
    delta = (selected_cost - original_cost) / original_cost * 100
    return float(delta)
