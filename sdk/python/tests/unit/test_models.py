"""Unit tests for axon.models."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from axon.classifier.artifact_type import ArtifactType
from axon.models import CompressionResult, InferenceSpan, Segment


def _valid_span(**overrides: object) -> InferenceSpan:
    defaults: dict = {
        "id": uuid4(), "trace_id": "trace-1", "parent_span_id": None,
        "span_name": "gen_ai.openai.gpt-4o", "timestamp": datetime.utcnow(),
        "duration_ms": 100, "provider": "openai", "model": "gpt-4o",
        "api_version": None, "input_tokens": 50, "output_tokens": 25,
        "cached_tokens": 0, "token_count_method": "exact",
        "cost_usd": Decimal("0.001"), "feature_tag": "test",
        "prompt_hash": "a" * 64, "artifact_type": ArtifactType.USER_MESSAGE,
        "compression_applied": False, "shadow_mode": True,
        "pre_compression_tokens": None, "tokens_saved": None,
        "cache_hit": False, "environment": "test",
    }
    defaults.update(overrides)
    return InferenceSpan(**defaults)  # type: ignore[arg-type]


class TestInferenceSpan:

    def test_valid_construction(self) -> None:
        span = _valid_span()
        assert span.provider == "openai"

    def test_duration_ms_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            _valid_span(duration_ms=-1)

    def test_input_tokens_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            _valid_span(input_tokens=-1)

    def test_output_tokens_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            _valid_span(output_tokens=-1)

    def test_cached_tokens_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            _valid_span(cached_tokens=-1)

    def test_prompt_hash_63_chars_raises(self) -> None:
        with pytest.raises(ValidationError):
            _valid_span(prompt_hash="a" * 63)

    def test_prompt_hash_64_hex_passes(self) -> None:
        span = _valid_span(prompt_hash="b" * 64)
        assert len(span.prompt_hash) == 64

    def test_prompt_hash_uppercase_raises(self) -> None:
        with pytest.raises(ValidationError):
            _valid_span(prompt_hash="A" * 64)

    def test_negative_cost_usd_raises(self) -> None:
        with pytest.raises(ValidationError):
            _valid_span(cost_usd=Decimal("-0.01"))

    def test_none_cost_usd_allowed(self) -> None:
        span = _valid_span(cost_usd=None)
        assert span.cost_usd is None


class TestSegment:

    def test_valid_construction(self) -> None:
        seg = Segment(
            index=0, role="user", content="hello",
            artifact_type=ArtifactType.USER_MESSAGE,
            token_count=5, turn_index=0, protected=False,
        )
        assert seg.token_count == 5

    def test_token_count_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            Segment(index=0, role="user", content="hi",
                    artifact_type=ArtifactType.USER_MESSAGE,
                    token_count=-1, turn_index=0, protected=False)

    def test_turn_index_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            Segment(index=0, role="user", content="hi",
                    artifact_type=ArtifactType.USER_MESSAGE,
                    token_count=1, turn_index=-1, protected=False)

    def test_embedding_wrong_length_raises(self) -> None:
        with pytest.raises(ValidationError):
            Segment(index=0, role="user", content="hi",
                    artifact_type=ArtifactType.USER_MESSAGE,
                    token_count=1, turn_index=0, protected=False,
                    embedding=[0.1] * 383)

    def test_embedding_384_passes(self) -> None:
        seg = Segment(index=0, role="user", content="hi",
                      artifact_type=ArtifactType.USER_MESSAGE,
                      token_count=1, turn_index=0, protected=False,
                      embedding=[0.0] * 384)
        assert seg.embedding is not None
        assert len(seg.embedding) == 384

    def test_embedding_none_passes(self) -> None:
        seg = Segment(index=0, role="user", content="hi",
                      artifact_type=ArtifactType.USER_MESSAGE,
                      token_count=1, turn_index=0, protected=False)
        assert seg.embedding is None


class TestCompressionResult:

    def _valid_result(self, **overrides: object) -> CompressionResult:
        defaults: dict = {
            "original_tokens": 100, "compressed_tokens": 80,
            "tokens_saved": 20, "compression_ratio": 0.2,
            "segments_analyzed": 5, "segments_retained": 3,
            "segments_summarized": 1, "segments_dropped": 1,
            "shadow_mode": True, "strategy_applied": "conservative",
            "messages": [], "warnings": [],
        }
        defaults.update(overrides)
        return CompressionResult(**defaults)  # type: ignore[arg-type]

    def test_valid_construction(self) -> None:
        result = self._valid_result()
        assert result.compression_ratio == 0.2

    def test_compression_ratio_above_1_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._valid_result(compression_ratio=1.1)

    def test_compression_ratio_below_0_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._valid_result(compression_ratio=-0.1)

    def test_inconsistent_tokens_saved_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._valid_result(original_tokens=100, compressed_tokens=80, tokens_saved=99)

    def test_inconsistent_segment_counts_raises(self) -> None:
        with pytest.raises(ValidationError):
            self._valid_result(
                segments_analyzed=5, segments_retained=3,
                segments_summarized=1, segments_dropped=0  # 3+1+0=4 != 5
            )
