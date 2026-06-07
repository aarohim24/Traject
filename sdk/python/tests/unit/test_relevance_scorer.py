"""Unit tests for axon.compression.relevance_scorer."""
from __future__ import annotations

from axon.classifier.artifact_type import ArtifactType
from axon.compression.relevance_scorer import score_segments
from axon.models import Segment


def _seg(
    index: int,
    content: str,
    turn_index: int,
    protected: bool = False,
    art_type: ArtifactType = ArtifactType.USER_MESSAGE,
) -> Segment:
    return Segment(
        index=index, role="user", content=content,
        artifact_type=art_type, token_count=len(content.split()),
        turn_index=turn_index, protected=protected,
    )


class TestScoreSegments:

    def test_empty_input_returns_empty(self) -> None:
        assert score_segments([]) == []

    def test_output_length_equals_input_length(self) -> None:
        segs = [_seg(i, f"message {i}", i) for i in range(5)]
        scores = score_segments(segs)
        assert len(scores) == 5

    def test_all_scores_in_bounds(self) -> None:
        segs = [_seg(i, f"msg {i}", i) for i in range(5)]
        for s in score_segments(segs):
            assert 0.0 <= s <= 1.0

    def test_protected_segment_scores_1_0(self) -> None:
        segs = [_seg(0, "system", 0, protected=True, art_type=ArtifactType.SYSTEM_PROMPT)]
        scores = score_segments(segs)
        assert scores[0] == 1.0

    def test_recent_segment_scores_higher_than_old(self) -> None:
        old = _seg(0, "old message", turn_index=0)
        recent = _seg(1, "recent message", turn_index=5)
        scores = score_segments([old, recent])
        assert scores[1] > scores[0]

    def test_deterministic_same_inputs(self) -> None:
        segs = [_seg(i, f"msg {i}", i) for i in range(3)]
        first = score_segments(segs)
        second = score_segments(segs)
        assert first == second

    def test_with_task_hint(self) -> None:
        segs = [_seg(0, "paris is the capital of france", 0)]
        scores = score_segments(segs, task_hint="What is the capital of France?")
        assert len(scores) == 1
        assert 0.0 <= scores[0] <= 1.0

    def test_without_task_hint_all_valid_floats(self) -> None:
        segs = [_seg(i, f"msg {i}", i) for i in range(4)]
        scores = score_segments(segs, task_hint=None)
        for s in scores:
            assert isinstance(s, float)
            assert 0.0 <= s <= 1.0
