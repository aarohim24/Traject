"""Unit tests for segment parser and framework adapters."""
from __future__ import annotations

import pytest

from traject.classifier.artifact_type import ArtifactType
from traject.compression.adapters.raw_openai import RawOpenAIAdapter
from traject.compression.segment_parser import parse
from traject.exceptions import TrajectCompressionError


class TestRawOpenAIAdapter:

    def test_accepts_valid_list_of_dicts(self) -> None:
        msgs = [{"role": "user", "content": "hi"}]
        assert RawOpenAIAdapter.accepts(msgs) is True

    def test_rejects_empty_list(self) -> None:
        assert RawOpenAIAdapter.accepts([]) is False

    def test_rejects_non_list(self) -> None:
        assert RawOpenAIAdapter.accepts("not a list") is False

    def test_rejects_list_without_role(self) -> None:
        assert RawOpenAIAdapter.accepts([{"content": "hi"}]) is False

    def test_rejects_list_without_content(self) -> None:
        assert RawOpenAIAdapter.accepts([{"role": "user"}]) is False

    def test_normalize_identity(self) -> None:
        msgs = [{"role": "user", "content": "hi"}]
        adapter = RawOpenAIAdapter()
        result = adapter.normalize(msgs)
        assert result is msgs

    def test_denormalize_identity(self) -> None:
        msgs = [{"role": "user", "content": "hi"}]
        adapter = RawOpenAIAdapter()
        result = adapter.denormalize(msgs, msgs)
        assert result is msgs


class TestSegmentParser:

    def test_basic_three_message_conversation(self) -> None:
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        art_types = [ArtifactType.SYSTEM_PROMPT, ArtifactType.USER_MESSAGE, ArtifactType.ASSISTANT_MESSAGE]
        segments = parse(messages, art_types)
        assert len(segments) == 3
        assert segments[0].role == "system"
        assert segments[0].protected is True  # system prompt always protected
        assert segments[1].protected is False

    def test_turn_index_increments_on_assistant_to_user(self) -> None:
        messages = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
        ]
        art_types = [
            ArtifactType.USER_MESSAGE, ArtifactType.ASSISTANT_MESSAGE,
            ArtifactType.USER_MESSAGE, ArtifactType.ASSISTANT_MESSAGE,
        ]
        segments = parse(messages, art_types)
        assert segments[0].turn_index == 0
        assert segments[1].turn_index == 0
        assert segments[2].turn_index == 1
        assert segments[3].turn_index == 1

    def test_traject_preserve_sets_protected(self) -> None:
        messages = [{"role": "user", "content": "hi", "traject_preserve": True}]
        art_types = [ArtifactType.USER_MESSAGE]
        segments = parse(messages, art_types)
        assert segments[0].protected is True

    def test_token_count_positive_for_non_empty_content(self) -> None:
        messages = [{"role": "user", "content": "Hello world"}]
        art_types = [ArtifactType.USER_MESSAGE]
        segments = parse(messages, art_types)
        assert segments[0].token_count > 0

    def test_raises_on_mismatched_lengths(self) -> None:
        messages = [{"role": "user", "content": "hi"}]
        art_types: list[ArtifactType] = []
        with pytest.raises(TrajectCompressionError):
            parse(messages, art_types)

    def test_empty_messages_returns_empty(self) -> None:
        assert parse([], []) == []

    def test_list_content_counted(self) -> None:
        messages = [{"role": "user", "content": [{"type": "text", "text": "hello world"}]}]
        art_types = [ArtifactType.USER_MESSAGE]
        segments = parse(messages, art_types)
        assert segments[0].token_count > 0
