"""ML training service for the Traject backend.

Queries ``InferenceSpanRecord`` rows with non-null ``routing_decision``
labels, extracts 18-dimensional feature vectors, fits a logistic regression
model, and persists the trained ``MLModelArtifact`` to the filesystem.

The training job is intended to run weekly via the APScheduler
``ml_weekly_training`` job registered in ``workers/scheduler.py``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from traject_backend.models.span import InferenceSpanRecord

if TYPE_CHECKING:
    from traject.router.ml_router import MLModelArtifact

_log = structlog.get_logger(__name__)

_DEFAULT_ARTIFACT_PATH = os.environ.get("TRAJECT_ML_MODEL_PATH", "/tmp/axon_ml_model.json")  # nosec B108


class MLTrainingService:
    """Trains and persists the logistic regression routing model.

    Reads labeled ``InferenceSpanRecord`` rows from the database, extracts
    features using the same ``_extract_features`` function used at inference
    time, fits a ``sklearn.linear_model.LogisticRegression``, and writes the
    result to a JSON artifact file.

    Args:
        artifact_path: Filesystem path where the trained artifact is saved.
            Defaults to ``settings.ml_model_path`` or
            ``/tmp/axon_ml_model.json``.
    """

    def __init__(
        self,
        artifact_path: str = _DEFAULT_ARTIFACT_PATH,
    ) -> None:
        self._artifact_path = artifact_path

    async def train(self, db: AsyncSession) -> MLModelArtifact:
        """Query labeled spans, extract features, fit LR, return artifact.

        Args:
            db: An active async SQLAlchemy session connected to the database
                with ``InferenceSpanRecord`` rows.

        Returns:
            The trained ``MLModelArtifact`` (not yet persisted to disk;
            call :meth:`_save_artifact` or await
            :meth:`run_weekly_training_job` to persist).

        Raises:
            InsufficientDataError: If zero training rows with a non-null
                ``routing_decision`` are found in the database.
        """
        from traject.exceptions import InsufficientDataError  # noqa: PLC0415
        from traject.router.ml_router import FEATURE_NAMES, MLModelArtifact, _extract_features  # noqa: PLC0415
        from traject.router.routing_table import ModelTier  # noqa: PLC0415

        try:
            from sklearn.linear_model import (  # type: ignore[import-untyped]  # noqa: PLC0415
                LogisticRegression,
            )
        except ImportError as exc:
            raise ImportError(
                "ML training requires scikit-learn. "
                "Install it with: pip install scikit-learn"
            ) from exc

        result = await db.execute(
            select(InferenceSpanRecord).where(
                InferenceSpanRecord.routing_decision.isnot(None)
            )
        )
        rows: list[InferenceSpanRecord] = list(result.scalars().all())

        if not rows:
            raise InsufficientDataError(
                "Cannot train ML routing model: no labeled InferenceSpanRecord rows "
                "found (routing_decision is NULL for all records). "
                "Ensure the router is configured and spans are being collected before training."
            )

        now = datetime.now(tz=UTC)
        X: list[Any] = []  # Any: numpy arrays aggregated into a 2D array
        y: list[str] = []

        for row in rows:
            # routing_decision is not None here (filtered above)
            assert row.routing_decision is not None
            routing_decision: str = row.routing_decision

            # Derive the ModelTier label from the routing_decision string.
            # The routing_decision format is "task_type.complexity → tier_value"
            # or "ml.task_type.complexity → tier_value"; the label is the tier.
            tier_str: str | None = None
            for tier in ModelTier:
                if routing_decision.endswith(tier.value):
                    tier_str = tier.value
                    break

            if tier_str is None:
                # Skip rows with unrecognised routing_decision format
                continue

            # Build a minimal messages list from stored span data for feature extraction.
            messages: list[dict[str, Any]] = [  # Any: message content varies
                {"role": "user", "content": ""},
            ]
            features = _extract_features(messages, row.model, row.timestamp)
            X.append(features)
            y.append(tier_str)

        if not X:
            raise InsufficientDataError(
                "Cannot train ML routing model: no labeled rows with a recognisable "
                "ModelTier in their routing_decision could be extracted from the database."
            )

        X_array = np.array(X, dtype=np.float64)

        lr = LogisticRegression(max_iter=1000, random_state=42)
        lr.fit(X_array, y)

        artifact = MLModelArtifact(
            coefficients=lr.coef_.tolist(),
            intercept=lr.intercept_.tolist(),
            classes=list(lr.classes_),
            feature_names=FEATURE_NAMES,
            training_sample_count=len(X),
            trained_at=now,
        )

        _log.info(
            "traject.ml_training.complete",
            sample_count=len(X),
            classes=list(lr.classes_),
        )
        return artifact

    def _save_artifact(self, artifact: MLModelArtifact) -> None:
        """Serialize and write an ``MLModelArtifact`` to the artifact path.

        Args:
            artifact: The trained model artifact to persist.
        """
        payload: dict[str, Any] = {  # Any: JSON-serialisable values of mixed types
            "coefficients": artifact.coefficients,
            "intercept": artifact.intercept,
            "classes": artifact.classes,
            "feature_names": artifact.feature_names,
            "training_sample_count": artifact.training_sample_count,
            "trained_at": artifact.trained_at.isoformat(),
        }
        with open(self._artifact_path, "w") as fh:
            json.dump(payload, fh)

        _log.info("traject.ml_training.artifact_saved", path=self._artifact_path)

    async def run_weekly_training_job(self, db: AsyncSession) -> None:
        """Run training, persist artifact, log result. Never re-raises.

        Intended for use as a scheduled APScheduler job. Any exception
        (including ``InsufficientDataError``) is caught and logged so the
        scheduler cannot be disrupted by training failures.

        Args:
            db: An active async SQLAlchemy session.
        """
        try:
            artifact = await self.train(db)
            self._save_artifact(artifact)
            _log.info(
                "traject.ml_training.weekly_job.success",
                sample_count=artifact.training_sample_count,
                trained_at=artifact.trained_at.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001 — scheduled job must never re-raise
            _log.error(
                "traject.ml_training.weekly_job.failed",
                error=str(exc),
                exc_info=True,
            )
