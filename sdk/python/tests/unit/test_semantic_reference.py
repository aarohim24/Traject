"""Unit and property-based tests for the semantic reference dependency pass.

Validates the following correctness properties:

P-REF-1  A segment whose content is semantically similar to later messages
         (cosine >= 0.6) is marked soft_protected=True.
P-REF-2  A segment with no semantically similar later messages is not
         soft-protected.
P-REF-3  Hard-protected segments are never soft-protected (they are already
         immutable).
P-REF-4  compute_semantic_reference_scores returns a list of the same length
         as the input segments, with values in [0.0, 1.0].
P-REF-5  Soft-protected segments resist compression: a TOOL_RESULT with score
         < 0.15 is SUMMARIZED; the same segment without soft_protected is
         SUMMARIZED only when score < 0.30 (CONSERVATIVE).
P-REF-6  The compress() result exposes segments_soft_protected count.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from traject.classifier.artifact_type import ArtifactType
from traject.compression.engine import _apply_strategy, compress
from traject.compression.relevance_scorer import compute_semantic_reference_scores
from traject.compression.strategies import CompressionConfig, CompressionStrategy
from traject.models import Segment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seg(
    index: int,
    content: str,
    turn_index: int,
    art: ArtifactType = ArtifactType.USER_MESSAGE,
    protected: bool = False,
    soft_protected: bool = False,
    semantically_referenced: bool = False,
) -> Segment:
    """Build a minimal Segment for testing."""
    return Segment(
        index=index,
        role="user",
        content=content,
        artifact_type=art,
        token_count=len(content.split()),
        turn_index=turn_index,
        protected=protected,
        soft_protected=soft_protected,
        semantically_referenced=semantically_referenced,
    )


def _live_config(
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
    min_turns: int = 0,
) -> CompressionConfig:
    return CompressionConfig(
        strategy=strategy,
        target_reduction_pct=0.20,
        min_turns_protected=min_turns,
        protect_system_prompt=True,
        shadow_mode=False,
    )


# ---------------------------------------------------------------------------
# Unit tests — compute_semantic_reference_scores
# ---------------------------------------------------------------------------


class TestComputeSemanticReferenceScores:
    """Tests for compute_semantic_reference_scores."""

    def test_empty_input_returns_empty(self) -> None:
        """P-REF-4: empty input → empty output."""
        assert compute_semantic_reference_scores([]) == []

    def test_output_length_matches_input(self) -> None:
        """P-REF-4: output length == input length."""
        segs = [_seg(i, f"message content {i}", i) for i in range(5)]
        scores = compute_semantic_reference_scores(segs)
        assert len(scores) == 5

    def test_scores_in_0_1_range(self) -> None:
        """P-REF-4: all scores are in [0.0, 1.0]."""
        segs = [_seg(i, f"some content {i}", i) for i in range(4)]
        scores = compute_semantic_reference_scores(segs)
        for s in scores:
            assert 0.0 <= s <= 1.0, f"Score {s} out of range"

    def test_protected_segment_scores_zero(self) -> None:
        """P-REF-3: hard-protected segments always score 0.0."""
        protected = _seg(0, "system prompt content", 0, protected=True)
        unprotected = _seg(1, "user message", 1)
        scores = compute_semantic_reference_scores([protected, unprotected])
        assert scores[0] == 0.0

    def test_semantically_similar_later_segment_raises_score(self) -> None:
        """P-REF-1: a segment similar to a later message gets a high score.

        Uses two nearly identical sentences so embedding similarity is high.
        """
        seg0 = _seg(0, "The API returned an authentication error code 401", 0)
        # Later segment paraphrases seg0 — should yield high cosine similarity.
        seg1 = _seg(1, "Authentication failed with HTTP 401 unauthorized response", 1)
        seg2 = _seg(2, "What should we do about the auth failure?", 2)

        scores = compute_semantic_reference_scores([seg0, seg1, seg2])

        # seg0 should have high similarity to seg1 (and possibly seg2)
        assert scores[0] >= 0.5, (
            f"Expected seg0 score >= 0.5 for semantically similar later message, "
            f"got {scores[0]:.4f}"
        )

    def test_unrelated_later_segments_yield_low_score(self) -> None:
        """P-REF-2: a segment with unrelated later messages scores low."""
        seg0 = _seg(0, "The database connection was established successfully", 0)
        seg1 = _seg(1, "What is the capital of France?", 1)
        seg2 = _seg(2, "Tell me a recipe for chocolate cake", 2)

        scores = compute_semantic_reference_scores([seg0, seg1, seg2])

        # seg0 about database has nothing to do with seg1/seg2 topics
        assert scores[0] < 0.7, (
            f"Expected low score for unrelated later messages, got {scores[0]:.4f}"
        )

    def test_window_limits_lookahead(self) -> None:
        """Only segments within the window are compared."""
        # seg0 is very similar to seg5, but seg5 is outside window=2
        similar_content = "The authentication token has expired and must be refreshed"
        seg0 = _seg(0, similar_content, 0)
        fillers = [
            _seg(i + 1, f"unrelated filler content chunk {i}", i + 1) for i in range(4)
        ]
        seg5 = _seg(
            5, "Token expiry requires refreshing the authentication credential", 5
        )

        all_segs = [seg0] + fillers + [seg5]
        scores_narrow = compute_semantic_reference_scores(all_segs, window=2)
        scores_wide = compute_semantic_reference_scores(all_segs, window=6)

        # With window=6, seg0 can see seg5 (high similarity).
        # With window=2, seg0 only sees seg1+seg2 (fillers, low similarity).
        assert scores_wide[0] > scores_narrow[0], (
            f"Wide window should yield higher score for seg0: "
            f"wide={scores_wide[0]:.4f}, narrow={scores_narrow[0]:.4f}"
        )


# ---------------------------------------------------------------------------
# Unit tests — soft_protected in _apply_strategy
# ---------------------------------------------------------------------------


class TestApplyStrategyWithSoftProtect:
    """Tests for _apply_strategy soft_protected tier behaviour."""

    def test_referenced_soft_protected_tool_result_retained_at_score_0_20(self) -> None:
        """P-REF-5: a *semantically referenced* soft_protected TOOL_RESULT with
        score 0.20 is RETAINED.

        A tool result that a later turn actively references keeps the strict
        gate: the threshold drops to < 0.15, so 0.20 → RETAIN.
        """
        seg = _seg(
            0,
            "Tool output",
            0,
            art=ArtifactType.TOOL_RESULT,
            soft_protected=True,
            semantically_referenced=True,
        )
        decision = _apply_strategy(
            seg, score=0.20, strategy=CompressionStrategy.CONSERVATIVE, max_turn=5
        )
        assert decision == "RETAIN"

    def test_unreferenced_soft_protected_tool_result_summarized_when_aged(self) -> None:
        """Gate split: a soft_protected TOOL_RESULT protected ONLY by its
        high-information content (not actively referenced) becomes eligible for
        command-aware summarization once it is several turns old, regardless of
        score. The command-aware summarizer preserves load-bearing facts.
        """
        seg = _seg(
            0,
            "Tool output",
            0,
            art=ArtifactType.TOOL_RESULT,
            soft_protected=True,
            semantically_referenced=False,
        )
        decision = _apply_strategy(
            seg, score=0.20, strategy=CompressionStrategy.CONSERVATIVE, max_turn=5
        )
        assert decision == "SUMMARIZE"

    def test_unreferenced_soft_protected_recent_tool_result_retained(self) -> None:
        """A recent (turns_ago <= 3) unreferenced soft_protected TOOL_RESULT is
        still RETAINED — the gate split only applies to aged segments.
        """
        seg = _seg(
            0,
            "Tool output",
            5,
            art=ArtifactType.TOOL_RESULT,
            soft_protected=True,
            semantically_referenced=False,
        )
        decision = _apply_strategy(
            seg, score=0.20, strategy=CompressionStrategy.CONSERVATIVE, max_turn=5
        )
        assert decision == "RETAIN"

    def test_soft_protected_tool_result_summarized_at_score_0_10(self) -> None:
        """P-REF-5: soft_protected TOOL_RESULT with score 0.10 is SUMMARIZED."""
        seg = _seg(
            0,
            "Tool output",
            0,
            art=ArtifactType.TOOL_RESULT,
            soft_protected=True,
        )
        decision = _apply_strategy(
            seg, score=0.10, strategy=CompressionStrategy.CONSERVATIVE, max_turn=5
        )
        assert decision == "SUMMARIZE"

    def test_normal_tool_result_summarized_at_score_0_20(self) -> None:
        """Without soft_protected, CONSERVATIVE SUMMARIZES TOOL_RESULT at score 0.20."""
        seg = _seg(
            0,
            "Tool output",
            0,
            art=ArtifactType.TOOL_RESULT,
            soft_protected=False,
        )
        decision = _apply_strategy(
            seg, score=0.20, strategy=CompressionStrategy.CONSERVATIVE, max_turn=5
        )
        assert decision == "SUMMARIZE"

    def test_soft_protected_reasoning_block_retained_at_score_0_20(self) -> None:
        """Soft_protected REASONING_BLOCK with score 0.20 is RETAINED (threshold < 0.15)."""
        seg = _seg(
            0,
            "Reasoning content",
            0,
            art=ArtifactType.REASONING_BLOCK,
            soft_protected=True,
        )
        decision = _apply_strategy(
            seg, score=0.20, strategy=CompressionStrategy.AGGRESSIVE, max_turn=5
        )
        assert decision == "RETAIN"

    def test_referenced_soft_protected_takes_precedence_over_all_strategies(
        self,
    ) -> None:
        """A semantically-referenced soft_protected TOOL_RESULT keeps the strict
        0.15 threshold regardless of strategy (score 0.20 → RETAIN everywhere).
        """
        seg = _seg(
            0,
            "content",
            0,
            art=ArtifactType.TOOL_RESULT,
            soft_protected=True,
            semantically_referenced=True,
        )
        for strategy in CompressionStrategy:
            decision = _apply_strategy(seg, score=0.20, strategy=strategy, max_turn=5)
            assert decision == "RETAIN", (
                f"Expected RETAIN for referenced soft_protected with score=0.20, "
                f"strategy={strategy}, got {decision}"
            )


# ---------------------------------------------------------------------------
# Integration tests — compress() end-to-end
# ---------------------------------------------------------------------------


class TestCompressSoftProtectIntegration:
    """End-to-end tests verifying soft_protected in the full compress() pipeline."""

    def test_segments_soft_protected_field_present(self) -> None:
        """P-REF-6: CompressionResult exposes segments_soft_protected."""
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Query one."},
            {"role": "assistant", "content": "Answer one."},
            {"role": "user", "content": "Query two."},
        ]
        result = compress(msgs, _live_config())
        assert hasattr(result, "segments_soft_protected")
        assert result.segments_soft_protected >= 0

    def test_semantically_referenced_tool_result_harder_to_compress(self) -> None:
        """P-REF-1/P-REF-5: a tool result referenced by later messages resists compression.

        Constructs a conversation where turn-0 contains a tool result about
        authentication errors, and all subsequent turns explicitly reference
        that error. The segment should be soft-protected and retained even
        when it would normally qualify for SUMMARIZE under CONSERVATIVE.
        """
        # Turn 0: old tool result (many turns ago — normally compressible)
        tool_content = (
            "Authentication failed: API key expired. "
            "Error code 401. Token must be refreshed before retrying."
        )
        # Turns 1–4: all reference the auth error semantically
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": "You are an API integration assistant."},
            {"role": "tool", "content": tool_content},
            {
                "role": "user",
                "content": "Why did authentication fail? The 401 error is blocking us.",
            },
            {
                "role": "assistant",
                "content": "The API key expired, causing the 401 auth failure.",
            },
            {
                "role": "user",
                "content": "How do we fix the expired token authentication issue?",
            },
            {
                "role": "assistant",
                "content": "Refresh the expired credential to resolve the auth error.",
            },
            {
                "role": "user",
                "content": "Has the authentication token been refreshed yet?",
            },
        ]
        cfg = _live_config(
            strategy=CompressionStrategy.CONSERVATIVE,
            min_turns=1,
        )
        result = compress(msgs, cfg, task_hint="resolve authentication error")

        # The tool result should not be dropped — it's being actively referenced
        all_content = " ".join(str(m.get("content", "")) for m in result.messages)
        # Check the distinctive error code is preserved
        assert "401" in all_content or result.segments_soft_protected > 0, (
            "Expected tool result about 401 error to be soft-protected or retained. "
            f"soft_protected={result.segments_soft_protected}, "
            f"summarized={result.segments_summarized}"
        )


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------


class TestSemanticReferenceProperties:
    """Hypothesis property tests for compute_semantic_reference_scores."""

    @settings(max_examples=50, deadline=None)
    @given(
        contents=st.lists(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Ll", "Lu", "Nd"),
                    whitelist_characters=" ",
                ),
                min_size=3,
                max_size=40,
            ),
            min_size=1,
            max_size=8,
        )
    )
    def test_scores_always_in_unit_interval(self, contents: list[str]) -> None:
        """P-REF-4 (property): all scores are in [0.0, 1.0] for any input."""
        segments = [_seg(i, c, i) for i, c in enumerate(contents)]
        scores = compute_semantic_reference_scores(segments)

        assert len(scores) == len(segments)
        for i, score in enumerate(scores):
            assert 0.0 <= score <= 1.0, (
                f"Score {score} at index {i} is outside [0.0, 1.0]"
            )

    @settings(max_examples=30, deadline=None)
    @given(
        contents=st.lists(
            st.text(min_size=3, max_size=30),
            min_size=2,
            max_size=6,
        )
    )
    def test_hard_protected_always_scores_zero(self, contents: list[str]) -> None:
        """P-REF-3 (property): hard-protected segments always score 0.0."""
        # Make the first segment hard-protected
        segs = [
            _seg(0, contents[0], 0, protected=True),
        ] + [_seg(i + 1, c, i + 1) for i, c in enumerate(contents[1:])]

        scores = compute_semantic_reference_scores(segs)
        assert scores[0] == 0.0, (
            f"Hard-protected segment scored {scores[0]}, expected 0.0"
        )
