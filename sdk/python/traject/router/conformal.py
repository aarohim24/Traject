"""Conformal prediction wrappers for quality-coverage guarantees in Traject routing.

Implements ``ConformalPredictor`` (split conformal calibration following Angelopoulos &
Bates, 2021) and ``ConformalRouter`` (a transparent router wrapper that escalates the
model tier when the conformal prediction set does not cover the quality threshold).

Mathematical foundation:
    Given ``n`` calibration examples with quality scores ``q_1, ..., q_n`` and a desired
    miscoverage rate ``alpha``:

    1. Non-conformity scores: ``s_i = threshold - q_i``
    2. Corrected quantile level: ``q_level = ceil((n+1) * (1-alpha)) / n``
    3. ``q_hat = np.quantile(scores, q_level, method="higher")``
    4. Coverage guarantee: ``P(quality >= threshold - q_hat) >= 1 - alpha``
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import structlog

from traject.router.routing_table import ModelTier, RoutingDecision

_log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Router protocol
# ---------------------------------------------------------------------------


class _RouterProtocol(Protocol):
    """Structural protocol for any object that implements ``route()``."""

    def route(
        self,
        messages: list[dict[str, Any]],  # Any: message values may be str, list, or dict
        requested_model: str,
        override_task_type: object = ...,
    ) -> RoutingDecision:
        """Return a routing decision for the given messages."""
        ...

# ---------------------------------------------------------------------------
# ConformalPredictionResult
# ---------------------------------------------------------------------------


@dataclass
class ConformalPredictionResult:
    """Result of a single conformal prediction evaluation.

    Attributes:
        covered: Whether the conformal prediction set covers the quality threshold.
            ``True`` when ``predicted_quality_lb >= 0``, meaning the model is
            expected to meet the threshold with probability ``>= 1 - alpha``.
        q_hat: The calibrated quantile threshold computed during ``calibrate()``.
        alpha: The miscoverage rate used during calibration.
        predicted_quality_lb: Lower bound on predicted quality, equal to
            ``threshold - q_hat``.  Non-negative values indicate coverage.
    """

    covered: bool
    q_hat: float
    alpha: float
    predicted_quality_lb: float


# ---------------------------------------------------------------------------
# ConformalPredictor
# ---------------------------------------------------------------------------


class ConformalPredictor:
    """Split conformal predictor for quality coverage guarantees.

    Implements the Angelopoulos & Bates (2021) algorithm for computing a
    statistically valid coverage threshold from a held-out calibration set.
    The resulting ``q_hat`` value provides a finite-sample marginal coverage
    guarantee without distributional assumptions.

    This class is fully pickle-serializable (uses only standard Python
    primitives and numpy scalars for state).

    Args:
        threshold: The quality threshold to cover (e.g. ``3.5`` on a 1-5 scale).
            Non-conformity scores are computed as ``threshold - quality``.
    """

    def __init__(self, threshold: float = 3.5) -> None:
        """Initialise the predictor with a quality threshold.

        Args:
            threshold: The quality score value the caller wants to exceed with
                probability ``>= 1 - alpha`` after calibration.
        """
        self._threshold: float = threshold
        self._q_hat: float = 0.0
        self._alpha: float = 0.0
        self._calibrated: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def calibrate(
        self,
        calibration_data: list[tuple[np.ndarray[Any, np.dtype[np.float64]], float]],
        alpha: float,
    ) -> None:
        """Fit the conformal predictor on a calibration dataset.

        Computes the non-conformity scores for each calibration example and
        derives ``q_hat`` — the corrected quantile threshold that guarantees
        empirical coverage ``>= 1 - alpha`` on the calibration set.

        Args:
            calibration_data: List of ``(features, quality_score)`` pairs.
                The ``features`` array is retained for API consistency with
                feature-dependent non-conformity scores but is not used in
                this implementation (quality-only scoring).
            alpha: Miscoverage rate in the open interval ``(0, 1)``.
                For 90% coverage use ``alpha=0.1``.

        Raises:
            ValueError: If ``calibration_data`` is empty.
            ValueError: If ``alpha`` is not strictly in the open interval
                ``(0, 1)`` (i.e., ``alpha <= 0`` or ``alpha >= 1``).
        """
        if len(calibration_data) == 0:
            raise ValueError(
                "calibration_data must not be empty. "
                "Provide at least one (features, quality_score) pair."
            )
        if not (0.0 < alpha < 1.0):
            raise ValueError(
                f"alpha must be strictly in (0, 1), got {alpha!r}. "
                "Use e.g. alpha=0.1 for 90% coverage."
            )

        n: int = len(calibration_data)

        # Non-conformity scores: higher → less conforming.
        scores: list[float] = [
            self._threshold - quality for (_, quality) in calibration_data
        ]

        # Corrected quantile level per the split-conformal formula.
        q_level: float = math.ceil((n + 1) * (1.0 - alpha)) / n

        # Clamp q_level to [0, 1] to keep np.quantile happy on small n.
        q_level = min(1.0, q_level)

        scores_arr: np.ndarray[Any, np.dtype[np.float64]] = np.array(
            scores, dtype=np.float64
        )
        self._q_hat = float(np.quantile(scores_arr, q_level, method="higher"))
        self._alpha = alpha
        self._calibrated = True

    def predict_set(
        self,
        features: np.ndarray[Any, np.dtype[np.float64]],
    ) -> ConformalPredictionResult:
        """Evaluate whether the coverage guarantee holds for a given feature vector.

        The ``features`` argument is accepted for API consistency with
        feature-dependent non-conformity score functions, but this
        implementation uses a quality-only scoring rule and does not use
        ``features`` in the computation.

        Args:
            features: Feature vector for the routing request (ignored in
                this quality-only implementation).

        Returns:
            A ``ConformalPredictionResult`` with:
                - ``covered``: ``True`` when ``predicted_quality_lb >= 0``.
                - ``q_hat``: The calibrated threshold from ``calibrate()``.
                - ``alpha``: The miscoverage rate from ``calibrate()``.
                - ``predicted_quality_lb``: ``threshold - q_hat``.

        Raises:
            RuntimeError: If called before ``calibrate()`` has been invoked.
        """
        if not self._calibrated:
            raise RuntimeError(
                "ConformalPredictor has not been calibrated. "
                "Call calibrate() with a calibration dataset before predict_set()."
            )

        predicted_quality_lb: float = self._threshold - self._q_hat
        covered: bool = predicted_quality_lb >= 0.0

        return ConformalPredictionResult(
            covered=covered,
            q_hat=self._q_hat,
            alpha=self._alpha,
            predicted_quality_lb=predicted_quality_lb,
        )

    @property
    def is_calibrated(self) -> bool:
        """Return whether this predictor has been calibrated.

        Returns:
            ``True`` after a successful call to ``calibrate()``.
        """
        return self._calibrated


# ---------------------------------------------------------------------------
# Tier escalation helper
# ---------------------------------------------------------------------------

_TIER_ESCALATION: dict[ModelTier, ModelTier] = {
    ModelTier.TIER_1: ModelTier.TIER_2,
    ModelTier.TIER_2: ModelTier.TIER_3,
    ModelTier.TIER_3: ModelTier.TIER_3,
}


def _escalate_tier(tier: ModelTier) -> ModelTier:
    """Return the next model tier above ``tier``, or ``TIER_3`` if already at max.

    Args:
        tier: The current ``ModelTier`` to escalate from.

    Returns:
        The escalated ``ModelTier``.
    """
    return _TIER_ESCALATION[tier]


# ---------------------------------------------------------------------------
# ConformalRouter
# ---------------------------------------------------------------------------


class ConformalRouter:
    """Router wrapper that enforces the conformal coverage guarantee.

    Wraps any object with a ``route()`` method compatible with ``RuleRouter``
    and escalates the selected ``ModelTier`` by one step when the conformal
    prediction set does not cover the quality threshold.

    When the ``ConformalPredictor`` is uncalibrated, a structlog warning is
    emitted and the inner router's decision is returned unchanged.

    Args:
        inner_router: Any object with a ``route()`` method that returns a
            ``RoutingDecision``.  Typically an ``MLRouter`` or ``RuleRouter``.
        conformal_predictor: A ``ConformalPredictor`` instance.  May be
            uncalibrated, in which case the inner decision passes through
            unchanged.
        model_map: Optional custom model map used for tier escalation.
            When provided, the ``selected_model`` field is updated to
            reflect the escalated tier.  When ``None``, ``selected_model``
            is left unchanged and only ``model_tier`` and ``routing_rule``
            are updated.
    """

    def __init__(
        self,
        inner_router: _RouterProtocol,
        conformal_predictor: ConformalPredictor,
        model_map: dict[str, dict[ModelTier, str]] | None = None,
    ) -> None:
        """Initialise the ConformalRouter.

        Args:
            inner_router: Inner router instance implementing ``route()``.
            conformal_predictor: Calibrated or uncalibrated predictor.
            model_map: Optional provider → tier → model-string mapping used
                to resolve the escalated model identifier.
        """
        self._inner_router: _RouterProtocol = inner_router
        self._predictor: ConformalPredictor = conformal_predictor
        self._model_map: dict[str, dict[ModelTier, str]] | None = model_map

    def route(
        self,
        messages: list[dict[str, Any]],  # Any: message values may be str, list, or dict
        requested_model: str,
        override_task_type: object = None,
    ) -> RoutingDecision:
        """Route a request, escalating the model tier if coverage is not guaranteed.

        Delegates the primary routing decision to ``inner_router.route()``.
        Then evaluates the conformal prediction set:

        - If the predictor is **uncalibrated**: logs a structlog warning and
          returns the inner decision unchanged.
        - If ``covered=True``: returns the inner decision unchanged.
        - If ``covered=False``: escalates ``model_tier`` one step and prefixes
          ``routing_rule`` with ``"conformal_escalation."``.

        Args:
            messages: List of message dicts following the OpenAI chat
                completions schema.
            requested_model: The model identifier originally requested by
                the caller.
            override_task_type: Forwarded verbatim to ``inner_router.route()``.

        Returns:
            An immutable ``RoutingDecision``.  When escalation occurs,
            ``routing_rule`` is prefixed with ``"conformal_escalation."``
            and ``model_tier`` is incremented by one step.
        """
        inner_decision: RoutingDecision = self._inner_router.route(
            messages, requested_model, override_task_type
        )

        if not self._predictor.is_calibrated:
            _log.warning(
                "traject.conformal_router.uncalibrated",
                message=(
                    "ConformalPredictor is not calibrated; "
                    "returning inner router decision unchanged."
                ),
            )
            return inner_decision

        # Build a dummy feature vector — predict_set() ignores features in
        # this quality-only implementation.
        dummy_features: np.ndarray[Any, np.dtype[np.float64]] = np.zeros(
            1, dtype=np.float64
        )
        result: ConformalPredictionResult = self._predictor.predict_set(dummy_features)

        if result.covered:
            return inner_decision

        # Escalate one tier.
        escalated_tier: ModelTier = _escalate_tier(inner_decision.model_tier)
        escalated_rule: str = "conformal_escalation." + inner_decision.routing_rule

        # Resolve escalated model string from model_map if available.
        escalated_model: str = inner_decision.selected_model
        if self._model_map is not None:
            provider_map = self._model_map.get(inner_decision.original_model, {})
            resolved = provider_map.get(escalated_tier)
            if resolved is not None:
                escalated_model = resolved

        return dataclasses.replace(
            inner_decision,
            model_tier=escalated_tier,
            selected_model=escalated_model,
            routing_rule=escalated_rule,
        )
