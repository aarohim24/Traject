"""Tests for the LOSSY semantic near-duplicate dedup pass.

Covers the standalone `compute_near_duplicates` function plus its wiring
into `compress()`: gated off at CONSERVATIVE, on at MODERATE/AGGRESSIVE,
using its own stub distinct from the lossless exact-match dedup, and
reversible via CCR when a store is configured.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from traject.classifier.artifact_type import ArtifactType
from traject.compression.engine import _DEDUP_STUB, compress
from traject.compression.semantic_dedup import (
    NEAR_DUPLICATE_STUB,
    compute_near_duplicates,
)
from traject.compression.strategies import CompressionConfig, CompressionStrategy
from traject.models import Segment


def _segment(index: int, content: str, protected: bool = False) -> Segment:
    return Segment(
        index=index,
        role="tool",
        content=content,
        artifact_type=ArtifactType.TOOL_RESULT,
        token_count=len(content.split()),
        turn_index=index,
        protected=protected,
    )


def _config(
    strategy: CompressionStrategy = CompressionStrategy.MODERATE,
) -> CompressionConfig:
    return CompressionConfig(
        strategy=strategy,
        target_reduction_pct=0.35,
        min_turns_protected=1,
        protect_system_prompt=True,
        shadow_mode=False,
        near_duplicate_dedup=(strategy != CompressionStrategy.CONSERVATIVE),
    )


def _near_dup_body(nonce: str) -> str:
    """Realistic near-duplicate tool output: identical body, one trailing
    nondeterministic field (mirrors a re-run command whose only diff is a
    timestamp/UUID/PID)."""
    body = "\n".join(f"line {n} of deploy output" for n in range(20))
    return f"{body}\ncompleted at {nonce}"


def _agent_loop_with_near_dup_repeats(repeats: int) -> list[dict[str, Any]]:
    """Same command re-run `repeats` times, each output differing only by a
    trailing nondeterministic timestamp."""
    msgs: list[dict[str, Any]] = [{"role": "system", "content": "You are an agent."}]
    msgs.append({"role": "user", "content": "Poll the deploy status until it's ready."})
    for i in range(repeats):
        msgs.append({"role": "assistant", "content": f"Step {i}: check deploy status."})
        msgs.append(
            {"role": "tool", "content": _near_dup_body(f"2026-08-23T10:0{i}:00Z")}
        )
    msgs.append({"role": "assistant", "content": "Deploy is ready."})
    msgs.append({"role": "tool", "content": "deploy status: ready"})
    return msgs


class TestComputeNearDuplicates:
    def test_no_candidates_returns_empty(self) -> None:
        stubs, keep = compute_near_duplicates([], exclude_indices=set())
        assert stubs == set()
        assert keep == set()

    def test_single_candidate_returns_empty(self) -> None:
        segs = [_segment(0, "some tool output here")]
        stubs, keep = compute_near_duplicates(segs, exclude_indices=set())
        assert stubs == set()
        assert keep == set()

    def test_near_duplicate_pair_detected(self) -> None:
        segs = [
            _segment(0, _near_dup_body("2026-08-23T10:00:00Z")),
            _segment(1, _near_dup_body("2026-08-23T10:05:33Z")),
        ]
        stubs, keep = compute_near_duplicates(segs, exclude_indices=set())
        assert stubs == {0}
        assert keep == {1}

    def test_dissimilar_segments_not_flagged(self) -> None:
        segs = [
            _segment(0, "compiling module foo.py with gcc flags -O2"),
            _segment(1, "network request to https://api.example.com returned 200"),
        ]
        stubs, keep = compute_near_duplicates(segs, exclude_indices=set())
        assert stubs == set()
        assert keep == set()

    def test_excluded_indices_never_reconsidered(self) -> None:
        segs = [
            _segment(0, _near_dup_body("2026-08-23T10:00:00Z")),
            _segment(1, _near_dup_body("2026-08-23T10:05:33Z")),
        ]
        stubs, keep = compute_near_duplicates(segs, exclude_indices={0, 1})
        assert stubs == set()
        assert keep == set()

    def test_protected_segments_never_collapsed(self) -> None:
        segs = [
            _segment(0, _near_dup_body("2026-08-23T10:00:00Z"), protected=True),
            _segment(1, _near_dup_body("2026-08-23T10:05:33Z")),
        ]
        stubs, keep = compute_near_duplicates(segs, exclude_indices=set())
        assert stubs == set()
        assert keep == set()

    def test_soft_protected_segments_never_collapsed(self) -> None:
        # A segment a later turn is actively reasoning about (soft-protected
        # by the engine's semantic-reference pass) must not be silently
        # discarded just because a near-duplicate copy exists elsewhere.
        referenced = _segment(0, _near_dup_body("2026-08-23T10:00:00Z")).model_copy(
            update={"soft_protected": True, "semantically_referenced": True}
        )
        segs = [referenced, _segment(1, _near_dup_body("2026-08-23T10:05:33Z"))]
        stubs, keep = compute_near_duplicates(segs, exclude_indices=set())
        assert stubs == set()
        assert keep == set()


class TestNearDuplicateDedupInEngine:
    def test_disabled_at_conservative(self) -> None:
        msgs = _agent_loop_with_near_dup_repeats(repeats=4)
        result = compress(msgs, _config(CompressionStrategy.CONSERVATIVE))
        assert result.segments_near_duplicate_collapsed == 0
        assert NEAR_DUPLICATE_STUB not in [m.get("content") for m in result.messages]

    def test_enabled_at_moderate_collapses_near_duplicates(self) -> None:
        msgs = _agent_loop_with_near_dup_repeats(repeats=4)
        result = compress(msgs, _config(CompressionStrategy.MODERATE))
        assert result.segments_near_duplicate_collapsed > 0
        stub_count = sum(
            1 for m in result.messages if m.get("content") == NEAR_DUPLICATE_STUB
        )
        assert stub_count == result.segments_near_duplicate_collapsed

    def test_near_dup_stub_distinct_from_exact_dedup_stub(self) -> None:
        assert NEAR_DUPLICATE_STUB != _DEDUP_STUB

    def test_last_near_duplicate_occurrence_kept_verbatim(self) -> None:
        msgs = _agent_loop_with_near_dup_repeats(repeats=3)
        result = compress(msgs, _config(CompressionStrategy.MODERATE))
        # The final tool call's body must still appear verbatim somewhere.
        last_tool_body = msgs[-1]["content"]
        assert any(
            isinstance(m.get("content"), str) and last_tool_body in m["content"]
            for m in result.messages
        )

    def test_ccr_store_makes_collapse_reversible(self) -> None:
        msgs = _agent_loop_with_near_dup_repeats(repeats=4)
        mock_store = MagicMock()
        mock_store.store.return_value = "<<ccr:deadbeefdeadbeef>>"
        result = compress(
            msgs, _config(CompressionStrategy.MODERATE), ccr_store=mock_store
        )
        assert result.segments_near_duplicate_collapsed > 0
        assert mock_store.store.called
        assert NEAR_DUPLICATE_STUB not in [m.get("content") for m in result.messages]
        assert result.segments_ccr_stubbed > 0
