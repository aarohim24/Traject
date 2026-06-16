"""Relevance scoring for compression pipeline segments.

Scores each ``Segment`` in a compression analysis using a composite formula
that combines recency decay, semantic similarity against an optional task
hint, and a reference-count heuristic. The underlying embedding model
(``all-MiniLM-L6-v2``) is loaded once at module import time and reused for
the process lifetime — no external API calls are ever made (ADR-003).
"""

from __future__ import annotations

import math
from typing import Any  # noqa: F401  # retained for re-export consistency

import numpy as np
from sentence_transformers import SentenceTransformer

from axon.models import Segment

# ---------------------------------------------------------------------------
# Module-level model singleton — loaded ONCE at import time (ADR-003).
# Never reload; never instantiate inside a function.
# ---------------------------------------------------------------------------
_model: SentenceTransformer = SentenceTransformer("all-MiniLM-L6-v2")

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------
_DECAY_RATE: float = 0.3
_RECENCY_WEIGHT: float = 0.4
_SEMANTIC_WEIGHT: float = 0.4
_REFERENCE_WEIGHT: float = 0.2


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compute_reference_counts(segments: list[Segment]) -> list[int]:
    """Return, for each segment i, the count of later segments that reference it."""
    counts: list[int] = []
    for i, seg in enumerate(segments):
        words: set[str] = set(seg.content.split())
        count = 0
        for j in range(i + 1, len(segments)):
            later_content = segments[j].content
            if any(word in later_content for word in words):
                count += 1
        counts.append(count)
    return counts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_segments(
    segments: list[Segment],
    task_hint: str | None = None,
) -> list[float]:
    """Score each segment's relevance using recency, semantic, and reference scoring.

    Args:
        segments: Ordered list of ``Segment`` objects produced by the segment
            parser. Protected segments always receive a score of ``1.0``.
        task_hint: Optional natural-language description of the current task.
            When provided, the semantic similarity between each segment and
            the task hint is incorporated into the composite score. When
            ``None``, the semantic component defaults to ``1.0``.

    Returns:
        A list of floats of the same length as ``segments``, where each value
        is in the range ``[0.0, 1.0]`` inclusive. Returns an empty list when
        ``segments`` is empty.

    Notes:
        Composite formula: ``0.4 * recency + 0.4 * semantic + 0.2 * reference``

        - **Recency**: ``exp(-0.3 * (max_turn - segment.turn_index))``
        - **Semantic**: cosine similarity of segment embedding vs. task hint
          embedding (normalized embeddings, so dot product equals cosine).
          Defaults to ``1.0`` when no task hint is provided.
        - **Reference**: ``min(1.0, reference_count / 3.0)`` where
          ``reference_count`` is the number of later segments whose content
          contains at least one word from this segment's content.

        The embedding model runs entirely in-process; no network calls are
        made (ADR-003).
    """
    if not segments:
        return []

    max_turn: int = max(s.turn_index for s in segments)

    # Encode the task hint once, if provided.
    task_embedding: list[float] | None = None
    if task_hint:
        task_embedding = _model.encode(
            task_hint, normalize_embeddings=True
        ).tolist()

    # Batch-encode content for all non-protected segments (only when a task
    # hint is present, since semantic scoring is only meaningful then).
    segment_embeddings: dict[int, list[float]] = {}
    if task_embedding is not None:
        non_protected_indices: list[int] = [
            i for i, s in enumerate(segments) if not s.protected
        ]
        if non_protected_indices:
            contents: list[str] = [
                segments[idx].content for idx in non_protected_indices
            ]
            embeddings = _model.encode(contents, normalize_embeddings=True)
            for idx, emb in zip(non_protected_indices, embeddings, strict=False):
                segment_embeddings[idx] = emb.tolist()

    reference_counts: list[int] = _compute_reference_counts(segments)

    scores: list[float] = []
    for i, seg in enumerate(segments):
        if seg.protected:
            scores.append(1.0)
            continue

        # Recency: exponential decay from the most recent turn.
        turns_since: int = max_turn - seg.turn_index
        recency: float = math.exp(-_DECAY_RATE * turns_since)

        # Semantic: cosine similarity via dot product of unit-norm embeddings.
        if task_embedding is not None and i in segment_embeddings:
            raw_semantic: float = float(
                np.dot(segment_embeddings[i], task_embedding)
            )
            semantic: float = max(0.0, min(1.0, raw_semantic))
        else:
            semantic = 1.0

        # Reference: normalized count of later segments that reference this one.
        reference: float = min(1.0, reference_counts[i] / 3.0)

        composite: float = (
            _RECENCY_WEIGHT * recency
            + _SEMANTIC_WEIGHT * semantic
            + _REFERENCE_WEIGHT * reference
        )
        scores.append(max(0.0, min(1.0, composite)))

    return scores
