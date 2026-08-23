"""Semantic near-duplicate detection for TOOL_RESULT segments.

This is a LOSSY, opt-in pass — a separate code path from the lossless
exact-match dedup in ``engine.py``'s ``_compute_dedup``. Where that function
only collapses byte-identical TOOL_RESULT segments (safe at every strategy,
because nothing that ever differed is discarded), this module catches
near-duplicates: the same command or file read producing output that differs
only in a nondeterministic field (a timestamp, a UUID, a PID, a wall-clock
duration). Collapsing those throws away whatever actually differed, so this
must never run at CONSERVATIVE and must never share `_compute_dedup`'s stub
message (see CLAUDE.md, "Lossless vs. lossy").

Uses the same ``all-MiniLM-L6-v2`` singleton as relevance scoring — no
external calls, no second model load (ADR-003).
"""

from __future__ import annotations

import numpy as np

from traject.classifier.artifact_type import ArtifactType
from traject.compression.relevance_scorer import get_embedding_model
from traject.models import Segment

NEAR_DUPLICATE_STUB: str = (
    "[Traject: near-duplicate tool output omitted — nearly identical to a "
    "later, verbatim copy above; differs only in a nondeterministic field.]"
)

DEFAULT_SIMILARITY_THRESHOLD: float = 0.97


def compute_near_duplicates(
    segments: list[Segment],
    exclude_indices: set[int],
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> tuple[set[int], set[int]]:
    """Identify near-duplicate (not byte-identical) TOOL_RESULT segments.

    Args:
        segments: Parsed segments.
        exclude_indices: Segment indices to skip — already handled by the
            exact-match dedup pass, or otherwise protected. Never
            re-collapsed here.
        similarity_threshold: Minimum cosine similarity for two segments to
            be treated as near-duplicates. Defaults to 0.97 — high enough
            that only near-verbatim outputs (differing in a stray field)
            qualify, not merely similar-looking ones.

    Returns:
        ``(stub_indices, keep_verbatim_indices)``, mirroring
        ``_compute_dedup``'s contract: earlier near-duplicate indices to
        replace with a stub, and the last-occurrence indices that must be
        retained verbatim.
    """
    candidates = [
        s
        for s in segments
        if s.artifact_type == ArtifactType.TOOL_RESULT
        and s.content.strip()
        and s.index not in exclude_indices
        and not s.protected
        # Soft-protected segments (actively referenced by a later turn, or
        # carrying high-information content like errors/paths/hashes) must
        # go through the engine's normal scoring/summarization path, which
        # is designed to preserve load-bearing facts — not this blunter,
        # whole-segment collapse.
        and not s.soft_protected
    ]
    if len(candidates) < 2:
        return set(), set()

    model = get_embedding_model()
    embeddings = model.encode(
        [s.content for s in candidates], normalize_embeddings=True
    )

    stub_indices: set[int] = set()
    keep_verbatim: set[int] = set()
    matched: set[int] = set()

    for i in range(len(candidates)):
        if i in matched:
            continue
        group = [i]
        for j in range(i + 1, len(candidates)):
            if j in matched:
                continue
            # Unit-norm embeddings -> dot product == cosine similarity.
            sim = float(np.dot(embeddings[i], embeddings[j]))
            if sim >= similarity_threshold:
                group.append(j)
        if len(group) > 1:
            group.sort(key=lambda pos: candidates[pos].index)
            for pos in group[:-1]:
                stub_indices.add(candidates[pos].index)
                matched.add(pos)
            keep_verbatim.add(candidates[group[-1]].index)
            matched.add(group[-1])

    return stub_indices, keep_verbatim
