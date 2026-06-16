"""Unit and property-based tests for traject.router.ml_router.MLRouter.

Covers is_trained(), route() fallback behaviour, training_stats() shape/types,
the 499-sample boundary, ML-path routing when trained, and a Hypothesis
property verifying route() never raises for arbitrary message lists.

Validates: Requirements 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from traject.router.ml_router import FEATURE_NAMES, MLRouter
from traject.router.routing_table import RoutingDecision

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_artifact_dict(
    training_sample_count: int = 500,
    n_classes: int = 3,
) -> dict[str, Any]:  # Any: JSON-serialisable mixed-type dict values
    """Return a minimal valid MLModelArtifact JSON dict.

    Builds a 3-class logistic regression artifact with zero weights.
    Predict() will always return the first class, which is fine for
    routing correctness tests.

    Args:
        training_sample_count: Number of training samples to encode.
        n_classes: Number of output classes (must be <= 3 for ModelTier).

    Returns:
        A dict ready to ``json.dump`` to a file.
    """
    n_features = len(FEATURE_NAMES)
    classes = ["tier_1", "tier_2", "tier_3"][:n_classes]
    coefficients = [[0.0] * n_features for _ in range(n_classes)]
    intercept = [0.0] * n_classes
    return {
        "coefficients": coefficients,
        "intercept": intercept,
        "classes": classes,
        "feature_names": FEATURE_NAMES,
        "training_sample_count": training_sample_count,
        "trained_at": datetime.now(tz=UTC).isoformat(),
    }


def _write_artifact_to_tmp(
    artifact: dict[str, Any],  # Any: JSON dict with mixed value types
    tmp_path: Path,
    filename: str = "artifact.json",
) -> str:
    """Write an artifact dict to a pytest tmp_path file; return the path string."""
    dest = tmp_path / filename
    dest.write_text(json.dumps(artifact))
    return str(dest)


# ---------------------------------------------------------------------------
# Task 7.1 — Unit tests
# ---------------------------------------------------------------------------


def test_is_trained_false_below_min_samples() -> None:
    """is_trained() returns False when no artifact has been loaded.

    A freshly constructed MLRouter("openai") with no model_artifact_path
    must report is_trained() == False.

    **Validates: Requirements 5.1**
    """
    router = MLRouter("openai")
    assert router.is_trained() is False


def test_route_delegates_to_rule_router_when_untrained() -> None:
    """route() on an untrained router delegates to RuleRouter.

    The routing_rule of the returned decision must NOT start with 'ml.'
    because the ML path was never taken.

    **Validates: Requirements 5.2**
    """
    router = MLRouter("openai")
    messages: list[dict[str, Any]] = [  # Any: message content is str
        {"role": "user", "content": "hello"}
    ]
    decision = router.route(messages, "gpt-4")

    assert isinstance(decision, RoutingDecision)
    assert not decision.routing_rule.startswith("ml.")


def test_training_stats_keys_and_types() -> None:
    """training_stats() returns a dict with the required keys and types.

    Keys expected:
      - 'is_trained'            (bool)
      - 'training_sample_count' (int)
      - 'trained_at'            (str)
      - 'feature_count'         (int)

    **Validates: Requirements 5.3**
    """
    router = MLRouter("openai")
    stats = router.training_stats()

    assert isinstance(stats, dict)
    assert isinstance(stats["is_trained"], bool)
    assert isinstance(stats["training_sample_count"], int)
    assert isinstance(stats["trained_at"], str)
    assert isinstance(stats["feature_count"], int)


def test_is_trained_false_with_499_sample_artifact(tmp_path: Path) -> None:
    """is_trained() returns False when loaded artifact has training_sample_count=499.

    The threshold is MIN_TRAINING_SAMPLES == 500, so 499 must keep the
    router in fallback mode.

    **Validates: Requirements 5.1**
    """
    artifact = _make_artifact_dict(training_sample_count=499)
    path = _write_artifact_to_tmp(artifact, tmp_path)

    router = MLRouter("openai", model_artifact_path=path)
    assert router.is_trained() is False


# ---------------------------------------------------------------------------
# Task 7.2 — Property-based test (Hypothesis)
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    messages=st.lists(
        st.fixed_dictionaries(
            {
                "role": st.sampled_from(["user", "assistant", "system"]),
                "content": st.text(),
            }
        ),
        min_size=0,
        max_size=10,
    )
)
def test_route_never_raises(messages: list[dict[str, str]]) -> None:
    """MLRouter.route() never raises for any list of well-formed message dicts.

    Property: For all message lists where each dict has a valid 'role' and
    arbitrary 'content' string, route() returns a RoutingDecision without
    raising any exception.

    **Validates: Requirements 5.2**
    """
    router = MLRouter("openai")
    decision = router.route(messages, "gpt-4")  # type: ignore[arg-type]
    assert isinstance(decision, RoutingDecision)


# ---------------------------------------------------------------------------
# Task 7.3 — Unit test: trained artifact → routing_rule starts with "ml."
# ---------------------------------------------------------------------------


def test_routing_rule_prefixed_ml_when_trained(tmp_path: Path) -> None:
    """routing_rule starts with 'ml.' when a valid artifact with >= 500 samples is loaded.

    Builds a 3-class logistic regression artifact (one class per ModelTier),
    writes it to a temp file, loads it into MLRouter, and asserts that:
      1. is_trained() == True
      2. route().routing_rule.startswith('ml.')

    **Validates: Requirements 5.4**
    """
    # Build a valid 3-class LR artifact with 500 training samples.
    artifact = _make_artifact_dict(training_sample_count=500, n_classes=3)
    path = _write_artifact_to_tmp(artifact, tmp_path)

    router = MLRouter("openai", model_artifact_path=path)
    assert router.is_trained() is True

    messages: list[dict[str, Any]] = [  # Any: message content is str
        {"role": "user", "content": "write a Python function to sort a list"}
    ]
    decision = router.route(messages, "gpt-4")
    assert decision.routing_rule.startswith("ml.")
