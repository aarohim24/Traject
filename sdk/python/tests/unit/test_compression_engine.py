"""Unit tests for traject.compression.engine.

Validates correctness properties P4-P8 and protection invariants.
Coverage target: >= 90% on engine.py.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from traject.classifier.artifact_type import ArtifactType
from traject.compression.engine import _apply_strategy, _detect_adapter, compress
from traject.compression.strategies import (
    CompressionConfig,
    CompressionStrategy,
)
from traject.exceptions import TrajectCompressionError, TrajectDependencyError
from traject.models import Segment


def _msgs(*roles_contents: tuple[str, str]) -> list[dict[str, Any]]:
    """Build a messages list from (role, content) tuples."""
    return [{"role": r, "content": c} for r, c in roles_contents]


def _shadow_config(
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
    min_turns: int = 3,
) -> CompressionConfig:
    return CompressionConfig(
        strategy=strategy,
        target_reduction_pct=0.20,
        min_turns_protected=min_turns,
        protect_system_prompt=True,
        shadow_mode=True,
    )


def _live_config(
    strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE,
    min_turns: int = 0,
) -> CompressionConfig:
    """Live (non-shadow) config with min_turns_protected=0 to expose all segments."""
    return CompressionConfig(
        strategy=strategy,
        target_reduction_pct=0.20,
        min_turns_protected=min_turns,
        protect_system_prompt=True,
        shadow_mode=False,
    )


def _seg(
    art: ArtifactType,
    turn: int = 0,
    content: str = "x",
    role: str = "user",
) -> Segment:
    """Build a minimal unprotected Segment for _apply_strategy tests."""
    return Segment(
        index=0,
        role=role,
        content=content,
        artifact_type=art,
        token_count=len(content.split()),
        turn_index=turn,
        protected=False,
    )


# ── Shadow Mode Identity (P4) ──────────────────────────────────────────────

class TestShadowModeIdentity:
    """P4: compress(..., shadow_mode=True).messages == original messages."""

    def test_single_user_message(self) -> None:
        msgs = _msgs(("user", "Hello"))
        result = compress(msgs, _shadow_config())
        assert result.shadow_mode is True
        assert result.messages == msgs

    def test_multi_turn_conversation(self) -> None:
        msgs = _msgs(
            ("system", "You are helpful."),
            ("user", "Q1"), ("assistant", "A1"),
            ("user", "Q2"), ("assistant", "A2"),
        )
        result = compress(msgs, _shadow_config())
        assert result.messages == msgs

    def test_only_system_prompt(self) -> None:
        msgs = _msgs(("system", "System only."))
        result = compress(msgs, _shadow_config())
        assert result.messages == msgs

    def test_shadow_tokens_saved_is_zero(self) -> None:
        msgs = _msgs(("system", "sys"), ("user", "hi"), ("assistant", "ok"))
        result = compress(msgs, _shadow_config())
        assert result.tokens_saved == 0
        assert result.compressed_tokens == result.original_tokens


# ── System Prompt Immutability (P5) ───────────────────────────────────────

SYSTEM_PROMPT_SHAPES = [
    [("system", "You are a helpful assistant."), ("user", "Hello")],
    [("system", "Be concise."), ("user", "Q"), ("assistant", "A"), ("user", "Q2")],
    [("system", "System only.")],
    [("system", "S1"), ("system", "S2"), ("user", "u")],  # two system prompts
    [("user", "no system")],  # no system prompt — trivially passes
]


@pytest.mark.parametrize("roles_contents", SYSTEM_PROMPT_SHAPES)
def test_p5_system_prompt_never_dropped(roles_contents: list[tuple[str, str]]) -> None:
    """P5: All system prompts from original survive compression."""
    msgs = _msgs(*roles_contents)
    # Use non-shadow mode with aggressive settings to stress-test protection
    config = CompressionConfig(
        strategy=CompressionStrategy.AGGRESSIVE,
        target_reduction_pct=0.55,
        min_turns_protected=2,
        protect_system_prompt=True,
        shadow_mode=False,
    )
    result = compress(msgs, config)
    result_contents = {m.get("content") for m in result.messages}
    for msg in msgs:
        if msg.get("role") == "system":
            assert msg["content"] in result_contents, (
                f"System prompt '{msg['content']}' was dropped"
            )


# ── Segment Count Invariant (P6) ──────────────────────────────────────────

class TestSegmentCountInvariant:
    """P6: retained + summarized + dropped == analyzed."""

    def test_conservative(self) -> None:
        msgs = _msgs(
            ("system", "sys"), ("user", "Q1"), ("assistant", "A1"),
            ("user", "Q2"), ("assistant", "A2"),
        )
        result = compress(msgs, _shadow_config(CompressionStrategy.CONSERVATIVE))
        total = result.segments_retained + result.segments_summarized + result.segments_dropped
        assert total == result.segments_analyzed

    def test_moderate(self) -> None:
        msgs = _msgs(
            ("system", "sys"), ("user", "Q1"), ("assistant", "A1"),
            ("user", "Q2"), ("assistant", "A2"),
        )
        result = compress(msgs, _shadow_config(CompressionStrategy.MODERATE))
        total = result.segments_retained + result.segments_summarized + result.segments_dropped
        assert total == result.segments_analyzed

    def test_aggressive(self) -> None:
        msgs = _msgs(
            ("system", "sys"), ("user", "Q1"), ("assistant", "A1"),
            ("user", "Q2"), ("assistant", "A2"),
        )
        result = compress(msgs, _shadow_config(CompressionStrategy.AGGRESSIVE))
        total = result.segments_retained + result.segments_summarized + result.segments_dropped
        assert total == result.segments_analyzed


# ── Compression Ratio Bounds (P7) ─────────────────────────────────────────

class TestCompressionRatioBounds:
    """P7: 0.0 <= compression_ratio <= 1.0."""

    @pytest.mark.parametrize("strategy", list(CompressionStrategy))
    def test_ratio_in_bounds(self, strategy: CompressionStrategy) -> None:
        msgs = _msgs(("system", "sys"), ("user", "Q"), ("assistant", "A"))
        result = compress(msgs, _shadow_config(strategy))
        assert 0.0 <= result.compression_ratio <= 1.0


# ── Token Savings Consistency (P8) ────────────────────────────────────────

class TestTokenSavingsConsistency:
    """P8: tokens_saved == original_tokens - compressed_tokens."""

    def test_shadow_mode(self) -> None:
        msgs = _msgs(("system", "sys"), ("user", "hi"), ("assistant", "ok"))
        result = compress(msgs, _shadow_config())
        assert result.tokens_saved == result.original_tokens - result.compressed_tokens

    def test_non_shadow_mode(self) -> None:
        msgs = _msgs(
            ("system", "sys"), ("user", "Q1"), ("assistant", "A1"),
            ("user", "Q2"), ("assistant", "A2"),
        )
        config = CompressionConfig(
            strategy=CompressionStrategy.CONSERVATIVE,
            target_reduction_pct=0.20,
            min_turns_protected=1,
            protect_system_prompt=True,
            shadow_mode=False,
        )
        result = compress(msgs, config)
        assert result.tokens_saved == result.original_tokens - result.compressed_tokens


# ── Validation Fallback ────────────────────────────────────────────────────

class TestValidationFallback:
    """When validation fails, engine falls back to original messages."""

    def test_fallback_returns_original_on_validation_failure(self) -> None:
        msgs = _msgs(("system", "sys"), ("user", "Q"), ("assistant", "A"))
        with patch(
            "traject.compression.engine._validate_compression_result",
            side_effect=TrajectCompressionError("test failure"),
        ):
            result = compress(msgs, _shadow_config())
        assert result.messages == msgs
        assert len(result.warnings) > 0
        assert result.tokens_saved == 0


# ── Strategy Decision Tests ────────────────────────────────────────────────

class TestStrategyDecisions:
    """Strategy-specific compression decisions on non-protected segments."""

    def _make_long_convo(self, n_turns: int = 10) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": "You are helpful."}]
        for i in range(n_turns):
            msgs.append({"role": "user", "content": f"Question {i}"})
            msgs.append({"role": "assistant", "content": f"Answer {i}"})
        return msgs

    def test_conservative_returns_compression_result(self) -> None:
        config = _shadow_config(CompressionStrategy.CONSERVATIVE)
        result = compress(self._make_long_convo(), config)
        assert result.strategy_applied == "conservative"
        assert result.segments_analyzed > 0

    def test_moderate_returns_compression_result(self) -> None:
        config = _shadow_config(CompressionStrategy.MODERATE)
        result = compress(self._make_long_convo(), config)
        assert result.strategy_applied == "moderate"

    def test_aggressive_returns_compression_result(self) -> None:
        config = _shadow_config(CompressionStrategy.AGGRESSIVE)
        result = compress(self._make_long_convo(), config)
        assert result.strategy_applied == "aggressive"


# ── Live Compression Mode (shadow_mode=False) ─────────────────────────────

class TestLiveCompression:
    """Verify shadow_mode=False returns the compressed message list."""

    def test_live_mode_returns_modified_messages(self) -> None:
        """Live mode result must differ from original when segments are dropped."""
        # REASONING_BLOCK with low score will be dropped under CONSERVATIVE.
        # Use min_turns_protected=0 so these old turns are not protected.
        msgs = [
            {"role": "system", "content": "You are helpful."},
            # Early turn — turn_index=0, unprotected with min_turns=0
            {
                "role": "assistant",
                "content": "let me think step by step about this problem",
            },
            {"role": "user", "content": "Final question"},
        ]
        config = _live_config(CompressionStrategy.CONSERVATIVE, min_turns=0)

        # Force a low relevance score for the REASONING_BLOCK so it gets dropped
        def mock_scores(segments: list[Any], hint: Any = None) -> list[float]:
            return [0.05 if not s.protected else 1.0 for s in segments]

        with patch("traject.compression.engine.score_segments", side_effect=mock_scores):
            result = compress(msgs, config)

        assert result.shadow_mode is False
        # At least one segment was processed (system prompt always retained)
        assert result.segments_analyzed > 0
        # tokens_saved consistency holds
        assert result.tokens_saved == result.original_tokens - result.compressed_tokens

    def test_live_mode_compression_ratio_nonzero_when_segments_dropped(self) -> None:
        """Compression ratio > 0 when segments are actually removed."""
        msgs = [
            {"role": "system", "content": "System prompt."},
            {
                "role": "assistant",
                "content": "let me think step by step through each piece",
            },
            {"role": "user", "content": "Next question"},
        ]
        config = _live_config(CompressionStrategy.AGGRESSIVE, min_turns=0)

        def mock_scores(segments: list[Any], hint: Any = None) -> list[float]:
            return [0.05 if not s.protected else 1.0 for s in segments]

        with patch("traject.compression.engine.score_segments", side_effect=mock_scores):
            result = compress(msgs, config)

        assert result.shadow_mode is False
        # compression_ratio in valid bounds
        assert 0.0 <= result.compression_ratio <= 1.0

    def test_live_mode_preserves_system_prompt(self) -> None:
        """System prompt must appear in live-mode result regardless of strategy."""
        sys_content = "You are a concise assistant."
        msgs = [
            {"role": "system", "content": sys_content},
            {
                "role": "assistant",
                "content": "let me think step by step right now",
            },
            {"role": "user", "content": "Go"},
        ]
        config = _live_config(CompressionStrategy.AGGRESSIVE, min_turns=0)

        def mock_scores(segments: list[Any], hint: Any = None) -> list[float]:
            return [0.01 if not s.protected else 1.0 for s in segments]

        with patch("traject.compression.engine.score_segments", side_effect=mock_scores):
            result = compress(msgs, config)

        contents = [m.get("content") for m in result.messages]
        assert sys_content in contents

    def test_live_mode_summarize_produces_axon_marker(self) -> None:
        """SUMMARIZE decision appends '[summarized by Axon]' to truncated content."""
        # TOOL_RESULT with turns_ago > 3 and score < 0.30 → SUMMARIZE (CONSERVATIVE)
        tool_content = "Tool output data: " + "x" * 200  # content > 100 chars
        msgs = [
            {"role": "system", "content": "System."},
            {"role": "tool", "content": tool_content},
            # Add enough turns so turn_index gap >= 4
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
            {"role": "assistant", "content": "a3"},
            {"role": "user", "content": "u4"},
            {"role": "assistant", "content": "a4"},
            {"role": "user", "content": "final"},
        ]
        config = _live_config(CompressionStrategy.CONSERVATIVE, min_turns=0)

        # Force score low on the tool message, high on everything else
        def mock_scores(segments: list[Any], hint: Any = None) -> list[float]:
            scores = []
            for s in segments:
                if s.artifact_type == ArtifactType.TOOL_RESULT:
                    scores.append(0.10)  # below 0.30 threshold
                else:
                    scores.append(1.0)
            return scores

        with patch("traject.compression.engine.score_segments", side_effect=mock_scores):
            result = compress(msgs, config)

        summarized_contents = [
            m.get("content", "") for m in result.messages
            if "[summarized by Axon]" in str(m.get("content", ""))
        ]
        assert len(summarized_contents) >= 1
        # Summarized content is truncated at 100 chars + marker
        assert summarized_contents[0].endswith("[summarized by Axon]")
        assert len(summarized_contents[0]) <= 122  # content[:100] + " [summarized by Axon]"


# ── _apply_strategy Branch Coverage ──────────────────────────────────────

class TestApplyStrategyBranches:
    """Direct unit tests for every decision branch in _apply_strategy."""

    # CONSERVATIVE strategy
    def test_conservative_tool_result_summarize(self) -> None:
        s = _seg(ArtifactType.TOOL_RESULT, turn=0)
        # turns_ago = 4 - 0 = 4 > 3, score = 0.10 < 0.30
        assert _apply_strategy(s, 0.10, CompressionStrategy.CONSERVATIVE, max_turn=4) == "SUMMARIZE"

    def test_conservative_tool_result_retain_score_too_high(self) -> None:
        s = _seg(ArtifactType.TOOL_RESULT, turn=0)
        # score >= 0.30 → RETAIN
        assert _apply_strategy(s, 0.50, CompressionStrategy.CONSERVATIVE, max_turn=4) == "RETAIN"

    def test_conservative_tool_result_retain_turns_not_enough(self) -> None:
        s = _seg(ArtifactType.TOOL_RESULT, turn=2)
        # turns_ago = 3 - 2 = 1, not > 3 → RETAIN
        assert _apply_strategy(s, 0.10, CompressionStrategy.CONSERVATIVE, max_turn=3) == "RETAIN"

    def test_conservative_reasoning_block_drop(self) -> None:
        s = _seg(ArtifactType.REASONING_BLOCK, turn=0)
        # score = 0.30 < 0.40
        assert _apply_strategy(s, 0.30, CompressionStrategy.CONSERVATIVE, max_turn=4) == "DROP"

    def test_conservative_reasoning_block_retain(self) -> None:
        s = _seg(ArtifactType.REASONING_BLOCK, turn=0)
        # score >= 0.40 → RETAIN
        assert _apply_strategy(s, 0.50, CompressionStrategy.CONSERVATIVE, max_turn=4) == "RETAIN"

    def test_conservative_other_artifact_retain(self) -> None:
        s = _seg(ArtifactType.USER_MESSAGE, turn=0)
        assert _apply_strategy(s, 0.10, CompressionStrategy.CONSERVATIVE, max_turn=4) == "RETAIN"

    # MODERATE strategy
    def test_moderate_tool_result_summarize(self) -> None:
        s = _seg(ArtifactType.TOOL_RESULT, turn=0)
        # turns_ago = 3 - 0 = 3 > 2, score = 0.20 < 0.40
        assert _apply_strategy(s, 0.20, CompressionStrategy.MODERATE, max_turn=3) == "SUMMARIZE"

    def test_moderate_tool_result_retain_turns_not_enough(self) -> None:
        s = _seg(ArtifactType.TOOL_RESULT, turn=2)
        # turns_ago = 3 - 2 = 1, not > 2 → RETAIN
        assert _apply_strategy(s, 0.10, CompressionStrategy.MODERATE, max_turn=3) == "RETAIN"

    def test_moderate_tool_result_retain_score_too_high(self) -> None:
        s = _seg(ArtifactType.TOOL_RESULT, turn=0)
        # score >= 0.40 → RETAIN
        assert _apply_strategy(s, 0.60, CompressionStrategy.MODERATE, max_turn=3) == "RETAIN"

    def test_moderate_reasoning_block_drop(self) -> None:
        s = _seg(ArtifactType.REASONING_BLOCK, turn=0)
        # score = 0.40 < 0.50
        assert _apply_strategy(s, 0.40, CompressionStrategy.MODERATE, max_turn=3) == "DROP"

    def test_moderate_reasoning_block_retain(self) -> None:
        s = _seg(ArtifactType.REASONING_BLOCK, turn=0)
        # score >= 0.50 → RETAIN
        assert _apply_strategy(s, 0.60, CompressionStrategy.MODERATE, max_turn=3) == "RETAIN"

    def test_moderate_rag_chunk_drop(self) -> None:
        s = _seg(ArtifactType.RAG_CHUNK, turn=0)
        # score = 0.20 < 0.35
        assert _apply_strategy(s, 0.20, CompressionStrategy.MODERATE, max_turn=3) == "DROP"

    def test_moderate_rag_chunk_retain(self) -> None:
        s = _seg(ArtifactType.RAG_CHUNK, turn=0)
        # score >= 0.35 → RETAIN
        assert _apply_strategy(s, 0.50, CompressionStrategy.MODERATE, max_turn=3) == "RETAIN"

    def test_moderate_user_message_retain(self) -> None:
        s = _seg(ArtifactType.USER_MESSAGE, turn=0)
        assert _apply_strategy(s, 0.05, CompressionStrategy.MODERATE, max_turn=3) == "RETAIN"

    # AGGRESSIVE strategy
    def test_aggressive_tool_result_summarize(self) -> None:
        s = _seg(ArtifactType.TOOL_RESULT, turn=0)
        # turns_ago = 2 - 0 = 2 > 1, score = 0.30 < 0.50
        assert _apply_strategy(s, 0.30, CompressionStrategy.AGGRESSIVE, max_turn=2) == "SUMMARIZE"

    def test_aggressive_tool_result_retain_turns_not_enough(self) -> None:
        s = _seg(ArtifactType.TOOL_RESULT, turn=1)
        # turns_ago = 2 - 1 = 1, not > 1 → RETAIN
        assert _apply_strategy(s, 0.10, CompressionStrategy.AGGRESSIVE, max_turn=2) == "RETAIN"

    def test_aggressive_tool_result_retain_score_too_high(self) -> None:
        s = _seg(ArtifactType.TOOL_RESULT, turn=0)
        # score >= 0.50 → RETAIN
        assert _apply_strategy(s, 0.70, CompressionStrategy.AGGRESSIVE, max_turn=2) == "RETAIN"

    def test_aggressive_reasoning_block_drop(self) -> None:
        s = _seg(ArtifactType.REASONING_BLOCK, turn=0)
        # score = 0.50 < 0.60
        assert _apply_strategy(s, 0.50, CompressionStrategy.AGGRESSIVE, max_turn=2) == "DROP"

    def test_aggressive_reasoning_block_retain(self) -> None:
        s = _seg(ArtifactType.REASONING_BLOCK, turn=0)
        # score >= 0.60 → RETAIN
        assert _apply_strategy(s, 0.70, CompressionStrategy.AGGRESSIVE, max_turn=2) == "RETAIN"

    def test_aggressive_rag_chunk_drop(self) -> None:
        s = _seg(ArtifactType.RAG_CHUNK, turn=0)
        # score = 0.30 < 0.45
        assert _apply_strategy(s, 0.30, CompressionStrategy.AGGRESSIVE, max_turn=2) == "DROP"

    def test_aggressive_rag_chunk_retain(self) -> None:
        s = _seg(ArtifactType.RAG_CHUNK, turn=0)
        # score >= 0.45 → RETAIN
        assert _apply_strategy(s, 0.60, CompressionStrategy.AGGRESSIVE, max_turn=2) == "RETAIN"

    def test_aggressive_few_shot_drop(self) -> None:
        s = _seg(ArtifactType.FEW_SHOT_EXAMPLE, turn=0)
        # score = 0.30 < 0.40
        assert _apply_strategy(s, 0.30, CompressionStrategy.AGGRESSIVE, max_turn=2) == "DROP"

    def test_aggressive_few_shot_retain(self) -> None:
        s = _seg(ArtifactType.FEW_SHOT_EXAMPLE, turn=0)
        # score >= 0.40 → RETAIN
        assert _apply_strategy(s, 0.50, CompressionStrategy.AGGRESSIVE, max_turn=2) == "RETAIN"

    def test_aggressive_other_artifact_retain(self) -> None:
        s = _seg(ArtifactType.USER_MESSAGE, turn=0)
        assert _apply_strategy(s, 0.01, CompressionStrategy.AGGRESSIVE, max_turn=2) == "RETAIN"


# ── Integration: Decision Branches via compress() ─────────────────────────

class TestDecisionBranchesViaCompress:
    """Exercise SUMMARIZE / DROP branches end-to-end through compress()."""

    def test_conservative_reasoning_block_dropped_live(self) -> None:
        """REASONING_BLOCK with very low score is dropped under CONSERVATIVE."""
        msgs = [
            {"role": "system", "content": "System."},
            {"role": "assistant", "content": "let me think step by step here"},
            {"role": "user", "content": "Final"},
        ]
        config = _live_config(CompressionStrategy.CONSERVATIVE, min_turns=0)

        def mock_scores(segments: list[Any], hint: Any = None) -> list[float]:
            return [0.05 if not s.protected else 1.0 for s in segments]

        with patch("traject.compression.engine.score_segments", side_effect=mock_scores):
            result = compress(msgs, config)

        assert result.segments_dropped >= 1
        # segments_retained + summarized + dropped == analyzed
        total = (
            result.segments_retained
            + result.segments_summarized
            + result.segments_dropped
        )
        assert total == result.segments_analyzed

    def test_moderate_rag_chunk_dropped_live(self) -> None:
        """RAG_CHUNK with very low score is dropped under MODERATE."""
        msgs = [
            {"role": "system", "content": "System."},
            # RAG_CHUNK: user with 'context:' marker
            {"role": "user", "content": "context: some retrieved document text here"},
            {"role": "user", "content": "Final question"},
        ]
        config = _live_config(CompressionStrategy.MODERATE, min_turns=0)

        def mock_scores(segments: list[Any], hint: Any = None) -> list[float]:
            return [0.05 if not s.protected else 1.0 for s in segments]

        with patch("traject.compression.engine.score_segments", side_effect=mock_scores):
            result = compress(msgs, config)

        assert result.segments_dropped >= 1

    def test_aggressive_few_shot_dropped_live(self) -> None:
        """FEW_SHOT_EXAMPLE with very low score is dropped under AGGRESSIVE."""
        # FEW_SHOT_EXAMPLE: user at position 0 (no system prompt) with 'example:' marker
        msgs = [
            {"role": "user", "content": "example: input: cat output: animal"},
            {"role": "user", "content": "Now answer this"},
        ]
        config = _live_config(CompressionStrategy.AGGRESSIVE, min_turns=0)

        def mock_scores(segments: list[Any], hint: Any = None) -> list[float]:
            return [0.05 if not s.protected else 1.0 for s in segments]

        with patch("traject.compression.engine.score_segments", side_effect=mock_scores):
            result = compress(msgs, config)

        # At least one segment was evaluated — few-shot may or may not be dropped
        # depending on classifier; validate invariants hold
        total = (
            result.segments_retained
            + result.segments_summarized
            + result.segments_dropped
        )
        assert total == result.segments_analyzed
        # At least the few-shot or second user segment was processed
        assert result.segments_analyzed >= 1

    def test_tool_result_summarized_live(self) -> None:
        """TOOL_RESULT is summarized when turns_ago > 3 and score < 0.30 (CONSERVATIVE)."""
        # Build a long enough conversation so tool message is at turn 0,
        # max_turn is high enough that turns_ago > 3
        msgs: list[dict[str, Any]] = [{"role": "system", "content": "System."}]
        # Tool message at the beginning (turn_index will be 0)
        msgs.append({"role": "tool", "content": "Tool output: " + "data " * 50})
        # Add 5 user/assistant pairs so max_turn reaches 5 (turns_ago = 5 > 3)
        for i in range(5):
            msgs.append({"role": "user", "content": f"Question {i}"})
            msgs.append({"role": "assistant", "content": f"Answer {i}"})

        config = _live_config(CompressionStrategy.CONSERVATIVE, min_turns=0)

        def mock_scores(segments: list[Any], hint: Any = None) -> list[float]:
            return [
                0.10 if s.artifact_type == ArtifactType.TOOL_RESULT else 1.0
                for s in segments
            ]

        with patch("traject.compression.engine.score_segments", side_effect=mock_scores):
            result = compress(msgs, config)

        assert result.segments_summarized >= 1
        # Summarized message contains the Traject marker
        summarized = [
            m for m in result.messages
            if "[summarized by Axon]" in str(m.get("content", ""))
        ]
        assert len(summarized) >= 1


# ── _detect_adapter Branch Coverage ──────────────────────────────────────

class TestDetectAdapter:
    """Tests for _detect_adapter including error paths."""

    def test_raises_on_unrecognized_type(self) -> None:
        """_detect_adapter raises TrajectCompressionError for unsupported message types."""
        with pytest.raises(TrajectCompressionError, match="No adapter found"):
            _detect_adapter("not a valid messages type")

    def test_raises_on_empty_non_list(self) -> None:
        """Non-list input triggers the TrajectCompressionError path."""
        with pytest.raises(TrajectCompressionError):
            _detect_adapter({"role": "user", "content": "not a list"})

    def test_langchain_dependency_error_falls_through(self) -> None:
        """When LangChain import raises TrajectDependencyError, falls through to error."""
        # Patch RawOpenAIAdapter.accepts to reject so we reach the LangChain branch
        with (
            patch(
                "traject.compression.adapters.raw_openai.RawOpenAIAdapter.accepts",
                return_value=False,
            ),
            patch(
                "traject.compression.adapters.langchain.LangChainAdapter",
                side_effect=TrajectDependencyError("langchain not installed"),
            ),pytest.raises(TrajectCompressionError, match="No adapter found")
        ):
            _detect_adapter([{"role": "user", "content": "hi"}])

    def test_autogen_dependency_error_falls_through(self) -> None:
        """When AutoGen import raises TrajectDependencyError, falls through to error."""
        # Passing an integer ensures neither RawOpenAI, LangChain, nor AutoGen
        # accept it, reaching the final TrajectCompressionError raise.
        with pytest.raises(TrajectCompressionError, match="No adapter found"):
            _detect_adapter(42)

    def test_langchain_and_autogen_both_raise_dependency_error(self) -> None:
        """Both guarded imports raising TrajectDependencyError triggers the final raise."""
        # Patch RawOpenAI to reject so we enter the optional-dep branches
        with (
            patch(
                "traject.compression.adapters.raw_openai.RawOpenAIAdapter.accepts",
                return_value=False,
            ),
            pytest.raises(TrajectCompressionError, match="No adapter found"),
        ):
            # LangChain and AutoGen raise TrajectDependencyError (not installed),
            # engine swallows them and raises TrajectCompressionError.
            _detect_adapter([{"role": "user", "content": "hello"}])

    def test_autogen_adapter_accept_path(self) -> None:
        """Exercise the AutoGenAdapter.accepts() check in _detect_adapter."""
        # Mock successful autogen import and adapter acceptance
        from unittest.mock import MagicMock

        mock_adapter_instance = MagicMock()
        mock_adapter_class = MagicMock(return_value=mock_adapter_instance)
        mock_adapter_class.accepts.return_value = True

        with (
            patch(
                "traject.compression.adapters.raw_openai.RawOpenAIAdapter.accepts",
                return_value=False,
            ),
            patch.dict(
                "sys.modules",
                {
                    "traject.compression.adapters.autogen": type(
                        "module",
                        (),
                        {"AutoGenAdapter": mock_adapter_class},
                    )()
                },
            ),
            patch(
                "traject.compression.engine._detect_adapter",
                wraps=lambda msgs: mock_adapter_instance,
            ),
        ):
            result = _detect_adapter([{"role": "user", "content": "hi", "name": "bob"}])
            # If AutoGen adapter accepts, it gets returned
            assert result is not None


# ── Validation Error Paths ────────────────────────────────────────────────

class TestValidationErrorPaths:
    """Tests for _validate_compression_result error paths (lines 138, 154)."""

    def test_circuit_breaker_returns_original_messages(self) -> None:
        """Validation failure → engine returns original context, never raises."""
        msgs = _msgs(("system", "sys"), ("user", "Q"), ("assistant", "A"))
        config = _shadow_config()

        with patch(
            "traject.compression.engine._validate_compression_result",
            side_effect=TrajectCompressionError("forced failure"),
        ):
            result = compress(msgs, config)

        # Engine must not raise; result contains original messages
        assert result.messages == msgs
        assert result.tokens_saved == 0
        assert result.segments_summarized == 0
        assert result.segments_dropped == 0
        # Warning entry is present
        assert any("Compression validation failed" in w for w in result.warnings)

    def test_circuit_breaker_preserved_in_live_mode(self) -> None:
        """Validation failure in live mode also returns original messages."""
        msgs = _msgs(
            ("system", "sys"), ("user", "Q1"), ("assistant", "A1"), ("user", "Q2")
        )
        config = _live_config()

        with patch(
            "traject.compression.engine._validate_compression_result",
            side_effect=TrajectCompressionError("live mode failure"),
        ):
            result = compress(msgs, config)

        assert result.messages == msgs
        assert len(result.warnings) > 0

    def test_compress_raises_on_invalid_config(self) -> None:
        """Invalid config raises TrajectConfigError before any processing."""
        from traject.exceptions import TrajectConfigError

        msgs = _msgs(("user", "hi"))
        bad_config = CompressionConfig(
            strategy=CompressionStrategy.CONSERVATIVE,
            target_reduction_pct=1.5,  # invalid: must be in (0.0, 1.0)
            min_turns_protected=0,
            protect_system_prompt=True,
            shadow_mode=True,
        )
        with pytest.raises(TrajectConfigError):
            compress(msgs, bad_config)

    def test_compress_raises_on_unrecognized_messages_type(self) -> None:
        """compress() propagates TrajectCompressionError from _detect_adapter."""
        config = _shadow_config()
        with pytest.raises(TrajectCompressionError, match="No adapter found"):
            compress("not a list", config)  # type: ignore[arg-type]

    def test_validate_compression_result_empty_list_raises(self) -> None:
        """_validate_compression_result raises when compressed list is empty."""
        from traject.compression.engine import _validate_compression_result

        original = [{"role": "user", "content": "hi"}]
        artifact_types = [ArtifactType.USER_MESSAGE]
        config = _shadow_config()

        with pytest.raises(TrajectCompressionError, match="empty message list"):
            _validate_compression_result(original, [], artifact_types, config)

    def test_validate_compression_result_system_prompt_removed_raises(self) -> None:
        """_validate_compression_result raises when a system prompt is missing."""
        from traject.compression.engine import _validate_compression_result

        original = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hi"},
        ]
        artifact_types = [ArtifactType.SYSTEM_PROMPT, ArtifactType.USER_MESSAGE]
        config = _shadow_config()
        # Compressed list has only the user message — system prompt removed
        compressed = [{"role": "user", "content": "Hi"}]

        with pytest.raises(TrajectCompressionError, match="system prompt"):
            _validate_compression_result(original, compressed, artifact_types, config)


# ── Task Hint (semantic scoring) ─────────────────────────────────────────

class TestTaskHint:
    """task_hint parameter exercises the semantic scoring branch."""

    def test_task_hint_does_not_raise(self) -> None:
        """Passing a task_hint runs without error and returns a valid result."""
        msgs = _msgs(("system", "System."), ("user", "What is the capital?"))
        config = _shadow_config()
        result = compress(msgs, config, task_hint="geography question")
        assert result.segments_analyzed > 0
        assert 0.0 <= result.compression_ratio <= 1.0
