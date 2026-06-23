"""ML-based model router using logistic regression for the Traject routing layer.

Defines ``MLModelArtifact`` (the serialized trained model dataclass) and
``_extract_features`` (the 18-dimensional feature extractor used at both
train time and inference time).  The full ``MLRouter`` class lives in this
module as well; this file provides the data structures and helpers that both
the SDK router and the backend training service share.

Feature vector layout (18 dimensions):
    Indices 0-9  : task_type one-hot, order follows ``list(TaskType)``
    Index  10    : complexity_score (raw float from estimate_complexity)
    Index  11    : input_token_count / 8000.0, clipped to [0, 1]
    Index  12    : has_code_blocks (1.0 if any message contains triple backticks)
    Index  13    : has_tool_calls (1.0 if any message has role ``"tool"``)
    Indices 14-15: hour_of_day cyclic encoding [sin(2*pi*h/24), cos(2*pi*h/24)]
    Indices 16-17: day_of_week cyclic encoding [sin(2*pi*d/7), cos(2*pi*d/7)]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import structlog

from traject.exceptions import TrajectDependencyError
from traject.router.routing_table import (
    DEFAULT_MODEL_MAP,
    ComplexityTier,
    ModelTier,
    RoutingDecision,
    complexity_score_to_tier,
)
from traject.router.rule_router import RuleRouter, _compute_cost_delta_pct
from traject.router.task_classifier import TaskType, classify_task, estimate_complexity

_log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Ordered list of all TaskType members — fixed at module load time so that
# the one-hot encoding order is identical at train time and inference time.
_TASK_TYPE_ORDER: list[TaskType] = list(TaskType)

# Number of task-type one-hot dimensions == len(_TASK_TYPE_ORDER).
_TASK_TYPE_COUNT: int = len(_TASK_TYPE_ORDER)

# Total feature vector dimensionality.
FEATURE_VECTOR_SIZE: int = 18

# Ordered feature names aligned with the 18-dim vector.
FEATURE_NAMES: list[str] = [f"task_type_{tt.value}" for tt in _TASK_TYPE_ORDER] + [
    "complexity_score",
    "input_token_count_norm",
    "has_code_blocks",
    "has_tool_calls",
    "hour_of_day_sin",
    "hour_of_day_cos",
    "day_of_week_sin",
    "day_of_week_cos",
]


# ---------------------------------------------------------------------------
# MLModelArtifact dataclass
# ---------------------------------------------------------------------------


@dataclass
class MLModelArtifact:
    """Serialized trained logistic regression routing model.

    This dataclass is the single source of truth for the trained model.
    It is serialized to JSON (never pickle) for persistence and read back
    at inference time to reconstruct a ``sklearn.linear_model.LogisticRegression``
    object by directly setting its ``coef_``, ``intercept_``, and
    ``classes_`` attributes.

    Attributes:
        coefficients: 2D list shape [n_classes, n_features] — the LR weights.
        intercept: 1D list length n_classes — the LR bias terms.
        classes: List of ModelTier string values in the order sklearn assigns.
        feature_names: Ordered list of feature names (length 18).
        training_sample_count: Number of labeled examples used for training.
        trained_at: UTC timestamp of when training completed.
    """

    coefficients: list[list[float]]
    intercept: list[float]
    classes: list[str]
    feature_names: list[str]
    training_sample_count: int
    trained_at: datetime


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def _extract_features(
    messages: list[dict[str, Any]],  # Any: message values may be str, list, or dict
    requested_model: str,
    timestamp: datetime,
) -> np.ndarray[tuple[int], np.dtype[np.float64]]:
    """Extract an 18-dimensional feature vector from a routing request.

    This function is a module-level private helper used at both train time
    (by ``MLTrainingService``) and inference time (by ``MLRouter``).  The
    feature layout and encoding are fixed; any change here must be accompanied
    by a full model retrain.

    Feature layout:
        Indices 0-9  : task_type one-hot (order: ``list(TaskType)``)
        Index  10    : ``complexity_score`` in [0, 1]
        Index  11    : ``input_token_count / 8000.0``, clipped to [0, 1]
        Index  12    : ``has_code_blocks`` - 1.0 if any message contains
            triple backtick fences (`` ``` ``)
        Index  13    : ``has_tool_calls`` - 1.0 if any message has role ``"tool"``
        Indices 14-15: ``hour_of_day`` cyclic [sin(2*pi*h/24), cos(2*pi*h/24)]
        Indices 16-17: ``day_of_week`` cyclic [sin(2*pi*d/7), cos(2*pi*d/7)]

    Args:
        messages: List of message dicts following the OpenAI chat completions
            schema.  Malformed or empty lists are handled gracefully; no
            exception is raised for invalid input.
        requested_model: The model identifier originally requested by the
            caller.  Reserved for future use (not currently encoded as a
            feature but kept in the signature for API stability).
        timestamp: UTC timestamp of the routing request.  Used to derive
            the cyclic time-of-day and day-of-week features.

    Returns:
        A ``numpy.ndarray`` of shape ``(18,)`` and dtype ``float64``.
    """
    features: np.ndarray[tuple[int], np.dtype[np.float64]] = np.zeros(
        FEATURE_VECTOR_SIZE, dtype=np.float64
    )

    # ------------------------------------------------------------------
    # 1. Task-type one-hot (indices 0-9)
    # ------------------------------------------------------------------
    task_type: TaskType = classify_task(messages)
    try:
        tt_index = _TASK_TYPE_ORDER.index(task_type)
    except ValueError:
        tt_index = _TASK_TYPE_ORDER.index(TaskType.UNKNOWN)
    features[tt_index] = 1.0

    # ------------------------------------------------------------------
    # 2. complexity_score (index 10)
    # ------------------------------------------------------------------
    features[10] = estimate_complexity(messages, task_type)

    # ------------------------------------------------------------------
    # 3. input_token_count normalized (index 11)
    # ------------------------------------------------------------------
    total_chars: int = 0
    has_code_blocks: bool = False
    has_tool_calls: bool = False

    safe_messages: list[dict[str, Any]]  # Any: values may be str, list, or dict
    safe_messages = messages if isinstance(messages, list) else []

    for msg in safe_messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        role = msg.get("role")
        if isinstance(content, str):
            total_chars += len(content)
            if "```" in content:
                has_code_blocks = True
        if isinstance(role, str) and role == "tool":
            has_tool_calls = True

    # Rough token estimate: 4 characters ≈ 1 token (matches estimate_complexity)
    token_estimate: float = total_chars / 4.0
    features[11] = min(1.0, token_estimate / 8000.0)

    # ------------------------------------------------------------------
    # 4. has_code_blocks (index 12)
    # ------------------------------------------------------------------
    features[12] = 1.0 if has_code_blocks else 0.0

    # ------------------------------------------------------------------
    # 5. has_tool_calls (index 13)
    # ------------------------------------------------------------------
    features[13] = 1.0 if has_tool_calls else 0.0

    # ------------------------------------------------------------------
    # 6. hour_of_day cyclic encoding (indices 14-15)
    # ------------------------------------------------------------------
    hour: int = timestamp.hour
    features[14] = math.sin(2.0 * math.pi * hour / 24.0)
    features[15] = math.cos(2.0 * math.pi * hour / 24.0)

    # ------------------------------------------------------------------
    # 7. day_of_week cyclic encoding (indices 16-17)
    # ------------------------------------------------------------------
    # datetime.weekday() returns 0=Monday ... 6=Sunday.
    day: int = timestamp.weekday()
    features[16] = math.sin(2.0 * math.pi * day / 7.0)
    features[17] = math.cos(2.0 * math.pi * day / 7.0)

    return features


# ---------------------------------------------------------------------------
# MLRouter class
# ---------------------------------------------------------------------------


class MLRouter:
    """ML-based model router using logistic regression.

    Falls back to ``RuleRouter`` when the training artifact contains fewer
    than ``MIN_TRAINING_SAMPLES`` examples, when no artifact is loaded, or
    when any exception occurs during inference.

    Args:
        provider: Provider name forwarded to the fallback ``RuleRouter``.
        rule_router: Injected ``RuleRouter`` instance used as fallback.
            When ``None`` a default ``RuleRouter`` is created for
            ``provider``.
        model_artifact_path: Optional path to a pre-trained
            ``MLModelArtifact`` JSON file.  When ``None`` the router starts
            in fallback mode immediately.
        routing_table: Optional custom routing table forwarded to the
            internal ``RuleRouter`` when ``rule_router`` is ``None``.
        model_map: Optional custom model map forwarded to the internal
            ``RuleRouter`` when ``rule_router`` is ``None``.

    Raises:
        TrajectDependencyError: If scikit-learn is not installed when this
            class is instantiated.
    """

    MIN_TRAINING_SAMPLES: int = 500

    def __init__(
        self,
        provider: str,
        rule_router: RuleRouter | None = None,
        model_artifact_path: str | None = None,
        routing_table: (dict[TaskType, dict[ComplexityTier, ModelTier]] | None) = None,
        model_map: dict[str, dict[ModelTier, str]] | None = None,
    ) -> None:
        """Initialise the MLRouter, importing sklearn lazily.

        Args:
            provider: Provider name forwarded to the fallback ``RuleRouter``.
            rule_router: Injected ``RuleRouter`` instance used as fallback.
            model_artifact_path: Optional path to a pre-trained artifact JSON.
            routing_table: Optional custom routing table for the fallback router.
            model_map: Optional custom model map for the fallback router.

        Raises:
            TrajectDependencyError: If scikit-learn is not installed.
        """
        # Lazy sklearn import — raises TrajectDependencyError if not installed.
        try:
            import sklearn  # noqa: F401
            from sklearn.linear_model import (
                LogisticRegression,
            )

            self._LogisticRegression = LogisticRegression
        except ImportError as exc:
            raise TrajectDependencyError(
                "ML routing requires scikit-learn. "
                "Install it with: pip install 'traject-sdk[ml]'"
            ) from exc

        self._provider = provider
        self._rule_router: RuleRouter = rule_router or RuleRouter(
            provider=provider,
            routing_table=routing_table,
            model_map=model_map,
        )

        # Trained model state — populated only when a valid artifact is loaded.
        self._artifact: MLModelArtifact | None = None
        self._lr: Any | None = None  # Any: sklearn LogisticRegression instance

        if model_artifact_path is not None:
            self._load_artifact(model_artifact_path)

    def _load_artifact(self, path: str) -> None:
        """Load an ``MLModelArtifact`` from a JSON file and reconstruct the LR.

        On any failure the method logs a warning and leaves the router in
        fallback mode (``self._artifact`` and ``self._lr`` remain ``None``).

        Args:
            path: Filesystem path to the JSON artifact file.
        """
        import json

        try:
            with open(path) as fh:
                raw: dict[str, Any] = json.load(fh)  # Any: arbitrary JSON dict

            artifact = MLModelArtifact(
                coefficients=raw["coefficients"],
                intercept=raw["intercept"],
                classes=raw["classes"],
                feature_names=raw["feature_names"],
                training_sample_count=int(raw["training_sample_count"]),
                trained_at=datetime.fromisoformat(raw["trained_at"]),
            )

            # Reconstruct the sklearn LogisticRegression from stored weights.
            lr = self._LogisticRegression()
            lr.coef_ = np.array(artifact.coefficients)
            lr.intercept_ = np.array(artifact.intercept)
            lr.classes_ = np.array(artifact.classes)

            self._artifact = artifact
            self._lr = lr

        except Exception as exc:  # broad catch is intentional — never raise
            _log.warning(
                "traject.ml_router.artifact_load_failed",
                path=path,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def route(
        self,
        messages: list[dict[str, Any]],  # Any: message values may be str, list, or dict
        requested_model: str,
        override_task_type: TaskType | None = None,
    ) -> RoutingDecision:
        """Route the request using the trained model, or fall back to RuleRouter.

        Delegates to ``RuleRouter`` when the router is untrained (no artifact
        loaded), when the training sample count is below
        ``MIN_TRAINING_SAMPLES``, or when any exception occurs during ML
        inference.  Never raises.

        Args:
            messages: List of message dicts following the OpenAI chat
                completions schema.
            requested_model: The model identifier originally requested by
                the caller.
            override_task_type: When set, forwarded to ``RuleRouter`` if
                fallback is triggered.

        Returns:
            An immutable ``RoutingDecision``.  When ML inference succeeds,
            ``routing_rule`` is prefixed with ``"ml."``.
        """
        try:
            return self._route_impl(messages, requested_model, override_task_type)
        except Exception:  # broad catch is intentional — route() must never raise
            return self._rule_router.route(
                messages, requested_model, override_task_type
            )

    def _route_impl(
        self,
        messages: list[dict[str, Any]],  # Any: message values may be str, list, or dict
        requested_model: str,
        override_task_type: TaskType | None,
    ) -> RoutingDecision:
        """Core ML routing logic.

        Args:
            messages: Raw message list from the caller.
            requested_model: Caller's original model string.
            override_task_type: Optional task-type override forwarded to
                fallback on untrained path.

        Returns:
            A fully populated ``RoutingDecision``.
        """
        # Fall back to RuleRouter when untrained or sample count too low.
        if not self.is_trained():
            return self._rule_router.route(
                messages, requested_model, override_task_type
            )

        # At this point artifact and lr are guaranteed non-None (is_trained() == True).
        assert self._artifact is not None  # mypy narrowing
        assert self._lr is not None  # mypy narrowing

        timestamp = datetime.utcnow()
        feature_vec: np.ndarray[tuple[int], np.dtype[np.float64]] = _extract_features(
            messages, requested_model, timestamp
        )

        # sklearn predict expects a 2-D array; reshape (18,) → (1, 18).
        prediction: np.ndarray[tuple[int], np.dtype[np.object_]] = self._lr.predict(
            feature_vec.reshape(1, -1)
        )
        predicted_class: str = str(prediction[0])

        try:
            model_tier = ModelTier(predicted_class)
        except ValueError:
            # Unknown class from model — defer to RuleRouter.
            return self._rule_router.route(
                messages, requested_model, override_task_type
            )

        task_type: TaskType = override_task_type or classify_task(messages)
        complexity_score: float = estimate_complexity(messages, task_type)
        complexity_tier: ComplexityTier = complexity_score_to_tier(complexity_score)

        # Resolve ModelTier → concrete model string via rule_router's model map.
        model_map = getattr(self._rule_router, "_model_map", DEFAULT_MODEL_MAP)
        provider_map: dict[ModelTier, str] = model_map.get(
            self._provider, DEFAULT_MODEL_MAP.get(self._provider, {})
        )
        selected_model: str = provider_map.get(model_tier, requested_model)

        routing_rule = (
            f"ml.{task_type.value}.{complexity_tier.value} → {model_tier.value}"
        )

        cost_delta_pct: float = _compute_cost_delta_pct(requested_model, selected_model)

        return RoutingDecision(
            original_model=requested_model,
            selected_model=selected_model,
            task_type=task_type,
            complexity_score=complexity_score,
            complexity_tier=complexity_tier,
            model_tier=model_tier,
            routing_rule=routing_rule,
            cost_delta_pct=cost_delta_pct,
            ab_test_group=None,
        )

    def is_trained(self) -> bool:
        """Return whether the router has a usable trained model loaded.

        A router is considered trained when an ``MLModelArtifact`` has been
        loaded successfully **and** its ``training_sample_count`` is at least
        ``MIN_TRAINING_SAMPLES``.

        Returns:
            ``True`` when the router will use ML inference; ``False`` when it
            will fall back to ``RuleRouter``.
        """
        return (
            self._artifact is not None
            and self._lr is not None
            and self._artifact.training_sample_count >= self.MIN_TRAINING_SAMPLES
        )

    def training_stats(self) -> dict[str, Any]:  # Any: dict values are mixed types
        """Return a summary of the current training state.

        Returns a dict with a fixed set of keys regardless of whether an
        artifact has been loaded, so callers can always access the same
        structure.

        Returns:
            A dict with keys:

                - ``"is_trained"`` (bool): Whether the router is currently
                  using ML inference.
                - ``"training_sample_count"`` (int): Number of labeled
                  examples in the loaded artifact, or ``0`` if untrained.
                - ``"trained_at"`` (str): ISO-8601 UTC timestamp of when the
                  model was last trained, or ``""`` if untrained.
                - ``"feature_count"`` (int): Length of the feature names list
                  in the artifact, or ``0`` if untrained.
        """
        if self._artifact is None:
            return {
                "is_trained": False,
                "training_sample_count": 0,
                "trained_at": "",
                "feature_count": 0,
            }
        return {
            "is_trained": self.is_trained(),
            "training_sample_count": self._artifact.training_sample_count,
            "trained_at": self._artifact.trained_at.isoformat(),
            "feature_count": len(self._artifact.feature_names),
        }
