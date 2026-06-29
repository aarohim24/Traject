"""Unit tests for traject.core.instrumentor.

Validates: Requirements R1.1-R1.6, R2.3, R14.1-R14.4
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import traject
from traject.core.instrumentor import _hash_prompt
from traject.telemetry import otel_exporter


@pytest.fixture(autouse=True)
def reset_otel() -> Any:
    """Reset OTEL provider state between tests."""
    otel_exporter._tracer_provider = None  # type: ignore[attr-defined]
    yield
    otel_exporter._tracer_provider = None  # type: ignore[attr-defined]


def _mock_response(model: str = "gpt-4o") -> Any:
    return SimpleNamespace(
        id="chatcmpl-test",
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="ok", role="assistant"))
        ],
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=50,
            completion_tokens=25,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        ),
    )


class TestHashPrompt:
    """Tests for the _hash_prompt privacy helper."""

    def test_empty_messages_returns_sha256_of_empty_string(self) -> None:
        expected = hashlib.sha256(b"").hexdigest()
        assert _hash_prompt([]) == expected

    def test_returns_64_char_hex_string(self) -> None:
        result = _hash_prompt([{"role": "user", "content": "hello"}])
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_identical_normalized_content_produces_same_hash(self) -> None:
        msgs1 = [{"role": "user", "content": "  HELLO  "}]
        msgs2 = [{"role": "user", "content": "hello"}]
        assert _hash_prompt(msgs1) == _hash_prompt(msgs2)

    def test_different_content_produces_different_hash(self) -> None:
        h1 = _hash_prompt([{"role": "user", "content": "hello"}])
        h2 = _hash_prompt([{"role": "user", "content": "goodbye"}])
        assert h1 != h2

    def test_list_format_content_extracts_text_parts(self) -> None:
        msgs = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
        result = _hash_prompt(msgs)
        assert len(result) == 64


class TestInstrumentDecorator:
    """Tests for the @traject.instrument() decorator."""

    def test_sync_decorator_returns_original_response(self) -> None:
        resp = _mock_response()

        @traject.instrument(feature_tag="test", shadow_mode=True)
        def call(messages: list) -> Any:
            return resp

        with patch("traject.core.instrumentor.emit_span"):
            result = call(messages=[{"role": "user", "content": "hi"}])
        assert result is resp

    @pytest.mark.asyncio
    async def test_async_decorator_returns_original_response(self) -> None:
        resp = _mock_response()

        @traject.instrument(feature_tag="async-test", shadow_mode=True)
        async def call_async(messages: list) -> Any:
            return resp

        with patch("traject.core.instrumentor.emit_span"):
            result = await call_async(messages=[{"role": "user", "content": "hi"}])
        assert result is resp

    def test_caller_exception_not_suppressed(self) -> None:
        @traject.instrument(feature_tag="error-test", shadow_mode=True)
        def call(messages: list) -> Any:
            raise ValueError("provider blew up")

        with (
            patch("traject.core.instrumentor.emit_span"),
            pytest.raises(ValueError, match="provider blew up"),
        ):
            call(messages=[{"role": "user", "content": "hi"}])

    def test_axon_error_does_not_suppress_response(self) -> None:
        """TrajectError during pipeline still returns original response."""
        from traject.exceptions import TrajectCompressionError

        resp = _mock_response()

        @traject.instrument(feature_tag="axon-error-test", shadow_mode=True)
        def call(messages: list) -> Any:
            return resp

        with (
            patch(
                "traject.core.instrumentor.compress",
                side_effect=TrajectCompressionError("oops"),
            ),
            patch("traject.core.instrumentor.emit_span"),
        ):
            result = call(messages=[{"role": "user", "content": "hi"}])
        assert result is resp

    def test_generic_compress_exception_fails_open(self) -> None:
        """A NON-TrajectError from compress() must NOT break the user's call.

        Regression for the fail-closed bug: tiktoken's first-use download,
        KeyError/ValueError in parsing/scoring, etc. previously escaped the
        TrajectError-only guard and aborted the request before it was made.
        """
        resp = _mock_response()

        @traject.instrument(feature_tag="fail-open-test", shadow_mode=False)
        def call(messages: list) -> Any:
            return resp

        for exc in (RuntimeError("network"), ValueError("bad"), KeyError("k")):
            with (
                patch("traject.core.instrumentor.compress", side_effect=exc),
                patch("traject.core.instrumentor.emit_span"),
            ):
                result = call(messages=[{"role": "user", "content": "hi"}])
            assert result is resp, f"call broke on {type(exc).__name__}"

    def test_emits_span_after_call(self) -> None:
        spans: list[Any] = []
        resp = _mock_response()

        @traject.instrument(feature_tag="span-test", shadow_mode=True)
        def call(messages: list) -> Any:
            return resp

        with patch(
            "traject.core.instrumentor.emit_span",
            side_effect=lambda s: spans.append(s),
        ):
            call(messages=[{"role": "user", "content": "hi"}])
        assert len(spans) == 1

    def test_feature_tag_recorded_in_span(self) -> None:
        spans: list[Any] = []
        resp = _mock_response()

        @traject.instrument(feature_tag="my-tag", shadow_mode=True)
        def call(messages: list) -> Any:
            return resp

        with patch(
            "traject.core.instrumentor.emit_span",
            side_effect=lambda s: spans.append(s),
        ):
            call(messages=[{"role": "user", "content": "hi"}])
        assert spans[0].feature_tag == "my-tag"

    def test_shadow_mode_true_in_span(self) -> None:
        spans: list[Any] = []
        resp = _mock_response()

        @traject.instrument(feature_tag="sm", shadow_mode=True)
        def call(messages: list) -> Any:
            return resp

        with patch(
            "traject.core.instrumentor.emit_span",
            side_effect=lambda s: spans.append(s),
        ):
            call(messages=[{"role": "user", "content": "hi"}])
        assert spans[0].shadow_mode is True


class TestPatch:
    """Tests for traject.patch()."""

    def test_patch_wraps_openai_chat_completions_create(self) -> None:
        spans: list[Any] = []
        resp = _mock_response()
        mock_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: resp))
        )
        traject.patch(mock_client, feature_tag="patch-test", shadow_mode=True)

        with patch(
            "traject.core.instrumentor.emit_span",
            side_effect=lambda s: spans.append(s),
        ):
            result = mock_client.chat.completions.create(
                messages=[{"role": "user", "content": "hi"}], model="gpt-4o"
            )
        assert result is resp
        assert len(spans) == 1
        assert spans[0].feature_tag == "patch-test"

    def test_patch_wraps_anthropic_messages_create(self) -> None:
        spans: list[Any] = []
        resp = SimpleNamespace(
            model="claude-3-5-sonnet-20241022",
            usage=SimpleNamespace(
                input_tokens=30, output_tokens=15, cache_read_input_tokens=0
            ),
        )
        mock_client = SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kw: resp)
        )
        traject.patch(mock_client, feature_tag="anthropic-patch", shadow_mode=True)

        with patch(
            "traject.core.instrumentor.emit_span",
            side_effect=lambda s: spans.append(s),
        ):
            result = mock_client.messages.create(
                messages=[{"role": "user", "content": "hi"}],
                model="claude-3-5-sonnet-20241022",
            )
        assert result is resp
        assert len(spans) == 1


class TestRouterApplication:
    """Tests for FIX H1 — router decisions must be applied to the outbound call."""

    @staticmethod
    def _decision(selected: str, original: str) -> Any:
        from traject.router.routing_table import (
            ComplexityTier,
            ModelTier,
            RoutingDecision,
        )
        from traject.router.task_classifier import TaskType

        return RoutingDecision(
            original_model=original,
            selected_model=selected,
            task_type=TaskType.SUMMARIZATION,
            complexity_score=0.1,
            complexity_tier=ComplexityTier.LOW,
            model_tier=ModelTier.TIER_1,
            routing_rule="summarization.low → tier_1",
            cost_delta_pct=-50.0,
            ab_test_group=None,
        )

    def test_selected_model_substituted_into_kwargs(self) -> None:
        """When the router picks a different model, fn must receive it in kwargs."""
        received: dict[str, Any] = {}
        resp = _mock_response()

        @traject.instrument(feature_tag="router-test", shadow_mode=True)
        def call(messages: list, model: str) -> Any:
            received["model"] = model
            return resp

        fake_router = SimpleNamespace(
            route=lambda messages, requested: self._decision(
                "gpt-4o-mini", requested
            )
        )
        with (
            patch("traject.core.instrumentor._router", fake_router),
            patch("traject.core.instrumentor.emit_span"),
        ):
            call(messages=[{"role": "user", "content": "hi"}], model="gpt-4o")

        assert received["model"] == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_selected_model_substituted_async(self) -> None:
        received: dict[str, Any] = {}
        resp = _mock_response()

        @traject.instrument(feature_tag="router-async", shadow_mode=True)
        async def call_async(messages: list, model: str) -> Any:
            received["model"] = model
            return resp

        fake_router = SimpleNamespace(
            route=lambda messages, requested: self._decision(
                "gpt-4o-mini", requested
            )
        )
        with (
            patch("traject.core.instrumentor._router", fake_router),
            patch("traject.core.instrumentor.emit_span"),
        ):
            await call_async(
                messages=[{"role": "user", "content": "hi"}], model="gpt-4o"
            )

        assert received["model"] == "gpt-4o-mini"

    def test_router_error_does_not_break_call(self) -> None:
        """A router that raises must fail OPEN — original model is used."""
        received: dict[str, Any] = {}
        resp = _mock_response()

        @traject.instrument(feature_tag="router-fail", shadow_mode=True)
        def call(messages: list, model: str) -> Any:
            received["model"] = model
            return resp

        def boom(messages: Any, requested: Any) -> Any:
            raise RuntimeError("router exploded")

        fake_router = SimpleNamespace(route=boom)
        with (
            patch("traject.core.instrumentor._router", fake_router),
            patch("traject.core.instrumentor.emit_span"),
        ):
            result = call(
                messages=[{"role": "user", "content": "hi"}], model="gpt-4o"
            )

        assert result is resp
        assert received["model"] == "gpt-4o"

    def test_positional_model_not_substituted(self) -> None:
        """Model passed positionally must not be overridden (no position guessing)."""
        received: dict[str, Any] = {}
        resp = _mock_response()

        @traject.instrument(feature_tag="router-positional", shadow_mode=True)
        def call(messages: list, model: str) -> Any:
            received["model"] = model
            return resp

        fake_router = SimpleNamespace(
            route=lambda messages, requested: self._decision(
                "gpt-4o-mini", requested
            )
        )
        with (
            patch("traject.core.instrumentor._router", fake_router),
            patch("traject.core.instrumentor.emit_span"),
        ):
            call([{"role": "user", "content": "hi"}], "gpt-4o")

        assert received["model"] == "gpt-4o"
