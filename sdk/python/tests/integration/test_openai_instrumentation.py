"""Integration tests for OpenAI instrumentation.

Tests the full pipeline: @instrument() -> response -> span emission.
No real API calls — provider response is mocked via SimpleNamespace.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import traject
from traject.telemetry import otel_exporter


@pytest.fixture(autouse=True)
def reset_otel() -> Any:
    """Reset OTEL provider state between tests."""
    otel_exporter._tracer_provider = None  # type: ignore[attr-defined]
    yield
    otel_exporter._tracer_provider = None  # type: ignore[attr-defined]


def _mock_response(
    model: str = "gpt-4o",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> Any:
    return SimpleNamespace(
        id="chatcmpl-test",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Paris", role="assistant"),
                finish_reason="stop",
            )
        ],
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        ),
    )


class TestOpenAIInstrumentation:
    """Integration tests for the @instrument() decorator with OpenAI-style responses."""

    def test_returns_original_response(self) -> None:
        resp = _mock_response()

        @traject.instrument(feature_tag="test", shadow_mode=True)
        def call(messages: list) -> Any:
            return resp

        with patch("axon.core.instrumentor.emit_span"):
            result = call(messages=[{"role": "user", "content": "Hi"}])
        assert result is resp

    def test_emits_exactly_one_span(self) -> None:
        spans: list[Any] = []

        @traject.instrument(feature_tag="test", shadow_mode=True)
        def call(messages: list) -> Any:
            return _mock_response()

        with patch(
            "axon.core.instrumentor.emit_span",
            side_effect=lambda s: spans.append(s),
        ):
            call(messages=[{"role": "user", "content": "Hi"}])
        assert len(spans) == 1

    def test_span_has_correct_feature_tag(self) -> None:
        spans: list[Any] = []

        @traject.instrument(feature_tag="my-feature", shadow_mode=True)
        def call(messages: list) -> Any:
            return _mock_response()

        with patch(
            "axon.core.instrumentor.emit_span",
            side_effect=lambda s: spans.append(s),
        ):
            call(messages=[{"role": "user", "content": "Hi"}])
        assert spans[0].feature_tag == "my-feature"

    def test_caller_exception_propagates(self) -> None:
        @traject.instrument(feature_tag="error", shadow_mode=True)
        def call(messages: list) -> Any:
            raise ValueError("boom")

        with (
            patch("axon.core.instrumentor.emit_span"),
            pytest.raises(ValueError, match="boom"),
        ):
            call(messages=[{"role": "user", "content": "Hi"}])

    def test_shadow_mode_recorded_in_span(self) -> None:
        spans: list[Any] = []

        @traject.instrument(feature_tag="sm", shadow_mode=True)
        def call(messages: list) -> Any:
            return _mock_response()

        with patch(
            "axon.core.instrumentor.emit_span",
            side_effect=lambda s: spans.append(s),
        ):
            call(messages=[{"role": "user", "content": "Hi"}])
        assert spans[0].shadow_mode is True

    def test_patch_wraps_client_create_method(self) -> None:
        spans: list[Any] = []
        resp = _mock_response()
        mock_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kw: resp)
            )
        )
        traject.patch(mock_client, feature_tag="patch-test", shadow_mode=True)

        with patch(
            "axon.core.instrumentor.emit_span",
            side_effect=lambda s: spans.append(s),
        ):
            result = mock_client.chat.completions.create(
                messages=[{"role": "user", "content": "Hi"}], model="gpt-4o"
            )
        assert result is resp
        assert len(spans) == 1
        assert spans[0].feature_tag == "patch-test"
