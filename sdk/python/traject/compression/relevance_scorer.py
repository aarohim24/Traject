"""Relevance scoring for compression pipeline segments.

Scores each ``Segment`` in a compression analysis using a composite formula
that combines recency decay, semantic similarity against an optional task
hint, and a reference-count heuristic. The underlying embedding model
(``all-MiniLM-L6-v2``) is loaded once at module import time and reused for
the process lifetime — no external API calls are ever made (ADR-003).

This module also provides :class:`CompressionCache`, a call-scoped cache that
avoids re-computing embedding similarity for segments whose content has not
changed between scoring calls within the same agent turn.

Task-aware weight profiles (:class:`TaskAwareWeights`) allow the scoring
formula to be tuned to the active task type (code generation, reasoning,
summarization), improving compression fidelity across diverse workloads.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any  # noqa: F401  # retained for re-export consistency

import numpy as np
from sentence_transformers import SentenceTransformer

from traject.classifier.artifact_type import ArtifactType
from traject.exceptions import TrajectConfigError
from traject.models import Segment

# ---------------------------------------------------------------------------
# Module-level model singleton — loaded ONCE at import time (ADR-003).
# Never reload; never instantiate inside a function.
# ---------------------------------------------------------------------------
_model: SentenceTransformer = SentenceTransformer("all-MiniLM-L6-v2")

# ---------------------------------------------------------------------------
# Scoring constants (fallback when no task-aware weights are available)
# ---------------------------------------------------------------------------
_DECAY_RATE: float = 0.3
_RECENCY_WEIGHT: float = 0.4
_SEMANTIC_WEIGHT: float = 0.4
_REFERENCE_WEIGHT: float = 0.2


# ---------------------------------------------------------------------------
# Task-aware weight profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreWeights:
    """Immutable composite scoring weights that must sum to 1.0.

    Attributes:
        recency: Weight applied to the exponential recency decay component.
        semantic: Weight applied to the cosine similarity against the task hint.
        reference: Weight applied to the normalised reference-count component.
    """

    recency: float
    semantic: float
    reference: float

    def __post_init__(self) -> None:
        """Validate that all three weights sum to 1.0 within floating-point tolerance."""
        total = self.recency + self.semantic + self.reference
        if not abs(total - 1.0) < 1e-6:
            raise TrajectConfigError(
                f"ScoreWeights must sum to 1.0, got {total}. "
                "Adjust recency, semantic, and reference so they total exactly 1.0."
            )


class TaskAwareWeights:
    """Pre-built :class:`ScoreWeights` profiles for common task types.

    Select a profile by inspecting the system prompt of the conversation.
    Use :func:`_detect_task_weights` to auto-detect the appropriate profile.

    Class Attributes:
        CODE_GENERATION: Higher reference weight; code tasks rely heavily on
            prior tool results and file content referenced downstream.
        REASONING: Higher recency weight; reasoning chains depend on the
            most recent context window.
        SUMMARIZATION: Higher semantic weight; summarization quality depends
            on topic alignment between segments and the summarization goal.
        DEFAULT: Balanced weights used when no task type is detected.
    """

    CODE_GENERATION: ScoreWeights = ScoreWeights(
        recency=0.25, semantic=0.35, reference=0.40
    )
    REASONING: ScoreWeights = ScoreWeights(
        recency=0.50, semantic=0.35, reference=0.15
    )
    SUMMARIZATION: ScoreWeights = ScoreWeights(
        recency=0.35, semantic=0.50, reference=0.15
    )
    DEFAULT: ScoreWeights = ScoreWeights(
        recency=0.40, semantic=0.40, reference=0.20
    )


# ---------------------------------------------------------------------------
# Task weight auto-detection
# ---------------------------------------------------------------------------

_CODE_KEYWORDS: frozenset[str] = frozenset(
    ["code", "implement", "fix", "patch", "repository", "function", "class", "engineer"]
)
_REASONING_KEYWORDS: frozenset[str] = frozenset(
    ["reason", "analyze", "think", "explain", "compare"]
)
_SUMMARIZATION_KEYWORDS: frozenset[str] = frozenset(
    ["summarize", "summary", "brief", "condense"]
)


def _detect_task_weights(segments: list[Segment]) -> ScoreWeights:
    """Detect appropriate scoring weights from the conversation's system prompt.

    Scans the system prompt segment (if any) for task-type keywords and
    returns the matching :class:`ScoreWeights` profile. Falls back to
    :attr:`TaskAwareWeights.DEFAULT` when no system prompt is present or when
    no keyword matches.

    Args:
        segments: Ordered list of ``Segment`` objects from the segment parser.

    Returns:
        A :class:`ScoreWeights` profile chosen by keyword matching, or
        :attr:`TaskAwareWeights.DEFAULT` when no task type is detected.
    """
    system_content: str = ""
    for seg in segments:
        if seg.artifact_type == ArtifactType.SYSTEM_PROMPT:
            system_content = seg.content.lower()
            break

    if not system_content:
        return TaskAwareWeights.DEFAULT

    if any(kw in system_content for kw in _CODE_KEYWORDS):
        return TaskAwareWeights.CODE_GENERATION
    if any(kw in system_content for kw in _REASONING_KEYWORDS):
        return TaskAwareWeights.REASONING
    if any(kw in system_content for kw in _SUMMARIZATION_KEYWORDS):
        return TaskAwareWeights.SUMMARIZATION
    return TaskAwareWeights.DEFAULT

# Number of buckets used to discretise task-hint similarity when computing
# cache keys. A higher value gives finer-grained cache separation at the cost
# of lower hit rates. 10 buckets maps 0.0–1.0 cosine similarity to integers
# 0–9, yielding cache reuse whenever the task hint is semantically close but
# not identical to a prior hint within the same call scope.
_TASK_BUCKET_COUNT: int = 10


# ---------------------------------------------------------------------------
# CompressionCache
# ---------------------------------------------------------------------------


class CompressionCache:
    """Call-scoped cache for segment relevance score *semantic components*.

    Avoids re-computing embedding similarity for segments whose content is
    unchanged across successive scoring calls within a single ``compress()``
    invocation. The cache stores only the **semantic similarity** component of
    the composite score — not the full composite — because recency and
    reference-count components depend on segment position, which can differ
    between two segments with the same content.

    The cache is keyed on ``(content_hash, task_bucket)`` where
    ``content_hash`` is the SHA-256 digest of the segment's content and
    ``task_bucket`` is the cosine similarity between the task-hint embedding
    and a fixed reference vector, discretised into ``_TASK_BUCKET_COUNT``
    integer buckets.

    The cache is intentionally **not** shared across ``compress()`` calls —
    each call constructs a fresh instance. This prevents stale scores from
    one agent turn affecting a later turn where task context has shifted.

    Attributes:
        hits: Number of cache hits accumulated since construction.
        misses: Number of cache misses accumulated since construction.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, int], float] = {}
        self.hits: int = 0
        self.misses: int = 0

    @staticmethod
    def _content_hash(content: str) -> str:
        """Return the SHA-256 hex digest of *content*.

        Args:
            content: The segment's text content.

        Returns:
            A 64-character lowercase hex string.
        """
        return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _task_bucket(
        segment_embedding: list[float],
        task_embedding: list[float],
    ) -> int:
        """Discretise cosine similarity into an integer bucket.

        Args:
            segment_embedding: Unit-norm embedding vector for the segment.
            task_embedding: Unit-norm embedding vector for the task hint.

        Returns:
            Integer in ``[0, _TASK_BUCKET_COUNT - 1]``.
        """
        similarity: float = float(np.dot(segment_embedding, task_embedding))
        # Clamp to [0.0, 1.0] before bucketing — cosine similarity can
        # technically be slightly outside this range due to float rounding.
        clamped: float = max(0.0, min(1.0, similarity))
        bucket: int = int(clamped * _TASK_BUCKET_COUNT)
        return min(bucket, _TASK_BUCKET_COUNT - 1)

    def get_semantic(
        self,
        content: str,
        segment_embedding: list[float] | None,
        task_embedding: list[float] | None,
    ) -> float | None:
        """Return a cached semantic similarity score, or ``None`` on a cache miss.

        A cache miss occurs when either embedding is absent (no task hint was
        provided) or when the ``(content_hash, task_bucket)`` key is not yet
        stored.

        Args:
            content: The segment's text content.
            segment_embedding: Unit-norm embedding for the segment, or ``None``
                when semantic scoring is disabled (no task hint).
            task_embedding: Unit-norm embedding for the task hint, or ``None``
                when no task hint is provided.

        Returns:
            The cached semantic similarity value in ``[0.0, 1.0]``, or
            ``None`` on a miss.
        """
        if segment_embedding is None or task_embedding is None:
            # Semantic component is disabled — no cache benefit.
            self.misses += 1
            return None

        key = (
            self._content_hash(content),
            self._task_bucket(segment_embedding, task_embedding),
        )
        result = self._store.get(key)
        if result is None:
            self.misses += 1
        else:
            self.hits += 1
        return result

    def put_semantic(
        self,
        content: str,
        segment_embedding: list[float],
        task_embedding: list[float],
        semantic_score: float,
    ) -> None:
        """Store a semantic similarity score under the ``(content_hash, task_bucket)`` key.

        Args:
            content: The segment's text content.
            segment_embedding: Unit-norm embedding for the segment.
            task_embedding: Unit-norm embedding for the task hint.
            semantic_score: The semantic similarity in ``[0.0, 1.0]`` to cache.
        """
        key = (
            self._content_hash(content),
            self._task_bucket(segment_embedding, task_embedding),
        )
        self._store[key] = semantic_score

    @property
    def hit_rate(self) -> float:
        """Return the cache hit rate as a float in ``[0.0, 1.0]``.

        Returns ``0.0`` when no lookups have been made.
        """
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


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


def compute_semantic_reference_scores(
    segments: list[Segment],
    window: int = 5,
) -> list[float]:
    """Compute a semantic reference score for each segment.

    For segment *i*, the reference score is the maximum cosine similarity
    between that segment and any of the ``window`` segments that immediately
    follow it. A high score means later messages are semantically close to
    this segment — i.e. the agent is still actively reasoning about its
    content, even if the wording has changed.

    Only non-protected segments are scored; protected segments receive 0.0
    (they are already preserved unconditionally and do not need soft
    protection).

    Uses the module-level ``all-MiniLM-L6-v2`` embedding singleton — no
    external API calls (ADR-003).

    Args:
        segments: Ordered list of ``Segment`` objects. Must not be empty.
        window: Maximum number of later segments to compare against.
            Defaults to 5.

    Returns:
        A list of floats of the same length as ``segments``. Values are in
        ``[0.0, 1.0]``. Returns an empty list when ``segments`` is empty.
    """
    if not segments:
        return []

    n = len(segments)

    # Batch-encode all segments in one pass (cheap — 384-dim model).
    all_embeddings: list[list[float]] = _model.encode(
        [s.content for s in segments],
        normalize_embeddings=True,
    ).tolist()

    scores: list[float] = []
    for i, seg in enumerate(segments):
        if seg.protected:
            scores.append(0.0)
            continue

        # Look at up to `window` segments after position i — but only
        # compare against ASSISTANT messages. Tool-to-tool similarity is
        # dominated by shared code structure and is not a reliable signal
        # for active reasoning dependency.
        end = min(i + 1 + window, n)
        max_sim: float = 0.0
        for j in range(i + 1, end):
            if segments[j].role not in ("assistant", "user"):
                continue
            sim: float = float(np.dot(all_embeddings[i], all_embeddings[j]))
            # Unit-norm embeddings → dot product == cosine similarity.
            sim = max(0.0, min(1.0, sim))
            if sim > max_sim:
                max_sim = sim

        scores.append(max_sim)

    return scores


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_segments(
    segments: list[Segment],
    task_hint: str | None = None,
    cache: CompressionCache | None = None,
    weights: ScoreWeights | None = None,
) -> list[float]:
    """Score each segment's relevance using recency, semantic, and reference scoring.

    When *cache* is provided, scores for segments whose content and task-hint
    similarity bucket have been seen before in this call scope are served from
    the cache, bypassing embedding computation for those segments.

    When *weights* is ``None``, the scoring weights are auto-detected from the
    system prompt of *segments* via :func:`_detect_task_weights`, selecting
    a task-appropriate profile (:class:`TaskAwareWeights`).

    Args:
        segments: Ordered list of ``Segment`` objects produced by the segment
            parser. Protected segments always receive a score of ``1.0``.
        task_hint: Optional natural-language description of the current task.
            When provided, the semantic similarity between each segment and
            the task hint is incorporated into the composite score. When
            ``None``, the semantic component defaults to ``1.0``.
        cache: Optional :class:`CompressionCache` instance. When provided,
            computed scores are stored in the cache and future calls for the
            same ``(content_hash, task_bucket)`` pair return the cached value.
            Pass ``None`` to disable caching (default, backward-compatible).
        weights: Optional :class:`ScoreWeights` override. When ``None``,
            weights are auto-detected from the conversation system prompt via
            :func:`_detect_task_weights`.

    Returns:
        A list of floats of the same length as ``segments``, where each value
        is in the range ``[0.0, 1.0]`` inclusive. Returns an empty list when
        ``segments`` is empty.

    Notes:
        Composite formula: ``w.recency * recency + w.semantic * semantic + w.reference * reference``

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

    # Resolve scoring weights: use provided weights or auto-detect from system prompt.
    active_weights: ScoreWeights = weights if weights is not None else _detect_task_weights(segments)

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

        seg_emb: list[float] | None = segment_embeddings.get(i)

        # --- Recency (always position-dependent, not cached) ---
        turns_since: int = max_turn - seg.turn_index
        recency: float = math.exp(-_DECAY_RATE * turns_since)

        # --- Semantic: check cache first (content + task → same similarity) ---
        if task_embedding is not None and seg_emb is not None:
            cached_semantic = (
                cache.get_semantic(seg.content, seg_emb, task_embedding)
                if cache is not None
                else None
            )
            if cached_semantic is not None:
                semantic: float = cached_semantic
            else:
                raw_semantic: float = float(np.dot(seg_emb, task_embedding))
                semantic = max(0.0, min(1.0, raw_semantic))
                if cache is not None:
                    cache.put_semantic(seg.content, seg_emb, task_embedding, semantic)
        else:
            semantic = 1.0

        # --- Reference: normalized count of later segments that reference this ---
        reference: float = min(1.0, reference_counts[i] / 3.0)

        composite: float = (
            active_weights.recency * recency
            + active_weights.semantic * semantic
            + active_weights.reference * reference
        )
        score: float = max(0.0, min(1.0, composite))
        scores.append(score)

    return scores
