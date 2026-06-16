# Adaptive Model Router Guide

## What the Router Does

The Traject Adaptive Model Router classifies every LLM call by task type and estimated complexity, then maps that pair to the cheapest capable model tier using a configurable routing table. Classification is heuristic-only (keyword matching) and runs in under 1 ms with no network calls, so it adds negligible overhead to every request. The result is a `RoutingDecision` dataclass that records the original model, the selected model, the routing rule applied, and the estimated cost delta — giving you full visibility into every substitution.

The router is purely advisory by default: when integrated with the Traject instrumentor via `configure(router=...)`, it logs routing decisions through structlog before each LLM call. If you want the router to actually substitute the model, call `router.apply(decision, client, messages)` instead of the provider client directly. This separation lets you audit routing behaviour in shadow mode before committing to automatic substitution.

---

## Routing Table

| TaskType | LOW (0.0–0.39) | MEDIUM (0.40–0.69) | HIGH (0.70–1.0) |
|---|---|---|---|
| SUMMARIZATION | TIER_1 | TIER_1 | TIER_2 |
| CLASSIFICATION | TIER_1 | TIER_1 | TIER_2 |
| EXTRACTION | TIER_1 | TIER_1 | TIER_2 |
| TRANSLATION | TIER_1 | TIER_1 | TIER_2 |
| QUESTION_ANSWERING | TIER_1 | TIER_2 | TIER_2 |
| CODE_REVIEW | TIER_1 | TIER_2 | TIER_2 |
| CODE_GENERATION | TIER_1 | TIER_2 | TIER_3 |
| REASONING | TIER_1 | TIER_2 | TIER_3 |
| CREATIVE_WRITING | TIER_1 | TIER_2 | TIER_3 |
| UNKNOWN | TIER_2 | TIER_2 | TIER_2 |

**Default model map:**

| Provider | TIER_1 | TIER_2 | TIER_3 |
|---|---|---|---|
| openai | gpt-4o-mini | gpt-4o | gpt-4o |
| anthropic | claude-3-5-haiku-20241022 | claude-3-5-sonnet-20241022 | claude-3-opus-20240229 |

---

## Basic Usage

```python
import traject
from traject.router.rule_router import RuleRouter

router = RuleRouter(provider="anthropic")
traject.configure(router=router)

# All subsequent patch()/instrument() calls now log routing decisions
client = anthropic.Anthropic()
traject.patch(client, feature_tag="summariser")
```

---

## Customization

Override the routing table or model map at construction time:

```python
from traject.router.routing_table import (
    ModelTier, ComplexityTier, DEFAULT_ROUTING_TABLE, DEFAULT_MODEL_MAP
)
from traject.router.task_classifier import TaskType

# Send ALL summarization to the cheapest model regardless of complexity
custom_table = {
    **DEFAULT_ROUTING_TABLE,
    TaskType.SUMMARIZATION: {
        ComplexityTier.LOW: ModelTier.TIER_1,
        ComplexityTier.MEDIUM: ModelTier.TIER_1,
        ComplexityTier.HIGH: ModelTier.TIER_1,
    },
}

router = RuleRouter(provider="openai", routing_table=custom_table)
```

Use `override_task_type` when you already know the task:

```python
from traject.router.task_classifier import TaskType

decision = router.route(
    messages,
    requested_model="gpt-4o",
    override_task_type=TaskType.SUMMARIZATION,
)
```

---

## A/B Testing

```python
from traject.router.ab_test import ABTestConfig
from traject.router.rule_router import RuleRouter

ab = ABTestConfig(
    treatment_model="gpt-4o-mini",
    treatment_pct=0.10,   # 10% of traffic goes to cheaper model
    feature_tag=None,     # applies to all task types
    seed=42,              # deterministic splits — same request_id always same group
)

router = RuleRouter(provider="openai", ab_test=ab)
```

**Interpreting results:** Check `decision.ab_test_group` — `"treatment"` means the cheaper model was used, `"control"` means the standard routing applied. Compare downstream quality metrics between groups before promoting the treatment to 100%.

---

## Cost Savings Estimation

`RoutingDecision.cost_delta_pct` is the signed percentage change in input-token cost versus the requested model. Negative values indicate savings:

```python
decision = router.route(messages, "gpt-4o")
if decision.cost_delta_pct < 0:
    print(f"Saving {abs(decision.cost_delta_pct):.1f}% on this call")
    print(f"  {decision.original_model} → {decision.selected_model}")
    print(f"  Rule: {decision.routing_rule}")
```

Aggregate `cost_delta_pct` across all calls in a feature tag to estimate monthly savings before enabling live substitution.
