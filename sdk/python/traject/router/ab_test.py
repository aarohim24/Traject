"""A/B test configuration and deterministic group assignment for the Traject router.

Provides ``ABTestConfig``, a dataclass that encapsulates treatment model,
traffic split percentage, an optional feature tag, and a seed for
reproducible, hash-based request-to-group assignment with no runtime
randomness.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from traject.exceptions import TrajectConfigError


@dataclass
class ABTestConfig:
    """Configuration for a deterministic A/B model routing experiment.

    Group assignment is computed by hashing ``"{seed}:{request_id}"`` with
    SHA-256, interpreting the first four bytes as a big-endian uint32, and
    dividing by 2^32 to produce a float in [0.0, 1.0).  Requests
    whose hash-derived float is strictly less than ``treatment_pct`` are
    assigned to the ``"treatment"`` group; all others go to ``"control"``.

    The same ``request_id`` always produces the same group for a given
    ``seed`` and ``treatment_pct``, making experiments reproducible and
    auditable.

    Attributes:
        treatment_model: The model identifier to use for requests in the
            ``"treatment"`` group (e.g. ``"gpt-4o"``).
        treatment_pct: Fraction of traffic to assign to the treatment
            group.  Must be in the closed interval [0.0, 1.0].
        feature_tag: Optional tag used to scope this experiment to a
            specific feature.  When set on the router, only requests whose
            task type matches this tag participate in the experiment.
            ``None`` means the experiment applies to all requests.
        seed: Integer seed mixed into the hash to isolate experiments and
            prevent cross-experiment correlation. Defaults to 42.

    Raises:
        TrajectConfigError: If ``treatment_pct`` is outside [0.0, 1.0].
    """

    treatment_model: str
    treatment_pct: float
    feature_tag: str | None
    seed: int = field(default=42)

    def __post_init__(self) -> None:
        """Validate that ``treatment_pct`` is within [0.0, 1.0].

        Raises:
            TrajectConfigError: If ``treatment_pct`` is less than 0.0 or
                greater than 1.0.
        """
        if not (0.0 <= self.treatment_pct <= 1.0):
            raise TrajectConfigError(
                f"ABTestConfig.treatment_pct must be in [0.0, 1.0], "
                f"got {self.treatment_pct!r}. "
                "Set treatment_pct to a value between 0.0 (no treatment traffic) "
                "and 1.0 (all treatment traffic)."
            )

    def assign_group(self, request_id: str) -> str:
        """Deterministically assign a request to a treatment or control group.

        Computes ``SHA-256("{seed}:{request_id}")``, takes the first four
        bytes as a big-endian unsigned 32-bit integer, divides by 2^32
        to obtain a float in [0.0, 1.0), and returns ``"treatment"`` when
        that float is strictly less than ``treatment_pct``, otherwise
        ``"control"``.

        Args:
            request_id: An arbitrary string that uniquely identifies this
                request. Using the same ``request_id`` always returns the
                same group, making the assignment fully reproducible.

        Returns:
            ``"treatment"`` or ``"control"``.
        """
        digest = hashlib.sha256(f"{self.seed}:{request_id}".encode()).digest()
        value = int.from_bytes(digest[:4], "big") / (2**32)
        return "treatment" if value < self.treatment_pct else "control"
