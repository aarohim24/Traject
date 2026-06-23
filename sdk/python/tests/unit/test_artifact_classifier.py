"""Unit tests for axon.classifier.artifact_type."""

from __future__ import annotations

import time
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from traject.classifier.artifact_type import ArtifactType, classify, classify_sequence


class TestArtifactTypeEnum:
    def test_nine_members(self) -> None:
        assert len(ArtifactType) == 9

    def test_system_prompt_value(self) -> None:
        assert ArtifactType.SYSTEM_PROMPT == "system_prompt"

    def test_str_subclass(self) -> None:
        assert isinstance(ArtifactType.USER_MESSAGE, str)


class TestClassify:
    def test_system_role_returns_system_prompt(self) -> None:
        assert (
            classify({"role": "system", "content": "hi"}, 0, 1)
            == ArtifactType.SYSTEM_PROMPT
        )

    def test_tool_role_returns_tool_result(self) -> None:
        assert (
            classify({"role": "tool", "content": "result"}, 1, 3)
            == ArtifactType.TOOL_RESULT
        )

    def test_tool_calls_field_returns_tool_call(self) -> None:
        assert (
            classify({"role": "assistant", "tool_calls": [{"id": "1"}]}, 1, 3)
            == ArtifactType.TOOL_CALL
        )

    def test_assistant_reasoning_markers_returns_reasoning_block(self) -> None:
        msg = {
            "role": "assistant",
            "content": "<thinking>Let me think step by step</thinking>",
        }
        assert classify(msg, 1, 5) == ArtifactType.REASONING_BLOCK

    def test_user_at_position_0_with_few_shot_markers_returns_few_shot(self) -> None:
        msg = {"role": "user", "content": "Example: input: foo output: bar"}
        assert classify(msg, 0, 5) == ArtifactType.FEW_SHOT_EXAMPLE

    def test_user_with_rag_markers_returns_rag_chunk(self) -> None:
        msg = {"role": "user", "content": "Context: here is the retrieved document."}
        assert classify(msg, 1, 5) == ArtifactType.RAG_CHUNK

    def test_plain_user_message(self) -> None:
        assert (
            classify({"role": "user", "content": "Hello!"}, 1, 5)
            == ArtifactType.USER_MESSAGE
        )

    def test_plain_assistant_message(self) -> None:
        assert (
            classify({"role": "assistant", "content": "Here you go."}, 2, 5)
            == ArtifactType.ASSISTANT_MESSAGE
        )

    def test_unknown_role_returns_unknown(self) -> None:
        assert (
            classify({"role": "system_admin", "content": "x"}, 0, 1)
            == ArtifactType.UNKNOWN
        )

    def test_empty_dict_returns_unknown(self) -> None:
        assert classify({}, 0, 1) == ArtifactType.UNKNOWN

    def test_missing_role_key_returns_unknown(self) -> None:
        assert classify({"content": "hi"}, 0, 1) == ArtifactType.UNKNOWN

    def test_role_none_returns_unknown(self) -> None:
        assert classify({"role": None}, 0, 1) == ArtifactType.UNKNOWN

    def test_system_prompt_priority_over_all(self) -> None:
        # Even with tool_calls or reasoning content, system role wins
        msg = {"role": "system", "content": "<thinking>", "tool_calls": [{"id": "x"}]}
        assert classify(msg, 0, 1) == ArtifactType.SYSTEM_PROMPT

    @pytest.mark.parametrize(
        "position_index,total_messages,content",
        [
            (i, n, c)
            for i in range(0, 10)
            for n in [1, 5, 10, 20]
            for c in ["", "  ", "hello world", "a" * 500]
            if i < n
        ][:20],  # 20 shapes
    )
    def test_p1_system_prompt_zero_false_negatives(
        self, position_index: int, total_messages: int, content: str
    ) -> None:
        """P1: Any message with role=='system' always returns SYSTEM_PROMPT."""
        msg = {"role": "system", "content": content}
        assert (
            classify(msg, position_index, total_messages) == ArtifactType.SYSTEM_PROMPT
        )

    @given(st.dictionaries(st.text(), st.text()))
    @settings(max_examples=100)
    def test_p3_never_raises(self, message: dict[str, Any]) -> None:
        """P3: classify never raises for any dict input."""
        result = classify(message, 0, 1)
        assert isinstance(result, ArtifactType)

    def test_performance_under_1ms(self) -> None:
        msg = {"role": "user", "content": "hello"}
        times = []
        for _ in range(100):
            t0 = time.perf_counter()
            classify(msg, 0, 1)
            times.append(time.perf_counter() - t0)
        assert max(times) < 0.001


class TestClassifySequence:
    def test_empty_list_returns_empty(self) -> None:
        assert classify_sequence([]) == []

    def test_same_length_as_input(self) -> None:
        msgs = [{"role": "user", "content": "hi"}] * 5
        result = classify_sequence(msgs)
        assert len(result) == 5

    def test_first_message_classified_correctly(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = classify_sequence(msgs)
        assert result[0] == ArtifactType.SYSTEM_PROMPT
        assert result[1] == ArtifactType.USER_MESSAGE
