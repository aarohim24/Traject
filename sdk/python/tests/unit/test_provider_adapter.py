"""Unit tests for axon.core.provider_adapter."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from traject.core.provider_adapter import (
    AnthropicAdapter,
    OpenAIAdapter,
    get_adapter,
)
from traject.exceptions import AxonProviderError


def _openai_response(
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    cached_tokens: int = 0,
    model: str = "gpt-4o",
) -> Any:
    return SimpleNamespace(
        id="chatcmpl-1",
        choices=[],
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
        ),
    )


def _anthropic_response(
    input_tokens: int = 80,
    output_tokens: int = 40,
    cache_read: int = 0,
    model: str = "claude-3-5-sonnet-20241022",
) -> Any:
    return SimpleNamespace(
        model=model,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
        ),
    )


class TestOpenAIAdapter:

    def test_extract_usage_exact(self) -> None:
        adapter = OpenAIAdapter()
        usage = adapter.extract_usage(_openai_response(100, 50))
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.token_count_method == "exact"

    def test_extract_cached_tokens(self) -> None:
        adapter = OpenAIAdapter()
        usage = adapter.extract_usage(_openai_response(100, 50, cached_tokens=30))
        assert usage.cached_tokens == 30

    def test_extract_model(self) -> None:
        adapter = OpenAIAdapter()
        assert adapter.extract_model(_openai_response(model="gpt-4o")) == "gpt-4o"

    def test_not_streaming(self) -> None:
        adapter = OpenAIAdapter()
        assert adapter.is_streaming(_openai_response()) is False

    def test_streaming_no_usage_returns_estimated_zeros(self) -> None:
        adapter = OpenAIAdapter()
        streaming_resp = SimpleNamespace()  # no 'choices', no 'usage'
        usage = adapter.extract_usage(streaming_resp)
        assert usage.token_count_method == "estimated"
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0

    def test_model_unknown_fallback(self) -> None:
        adapter = OpenAIAdapter()
        resp = SimpleNamespace()  # no model attr
        assert adapter.extract_model(resp) == "unknown"


class TestAnthropicAdapter:

    def test_extract_usage_exact(self) -> None:
        adapter = AnthropicAdapter()
        usage = adapter.extract_usage(_anthropic_response(80, 40))
        assert usage.input_tokens == 80
        assert usage.output_tokens == 40
        assert usage.token_count_method == "exact"

    def test_extract_cached_tokens(self) -> None:
        adapter = AnthropicAdapter()
        usage = adapter.extract_usage(_anthropic_response(80, 40, cache_read=20))
        assert usage.cached_tokens == 20

    def test_extract_model(self) -> None:
        adapter = AnthropicAdapter()
        resp = _anthropic_response(model="claude-3-5-sonnet-20241022")
        assert adapter.extract_model(resp) == "claude-3-5-sonnet-20241022"

    def test_not_streaming(self) -> None:
        adapter = AnthropicAdapter()
        assert adapter.is_streaming(_anthropic_response()) is False


class TestGetAdapter:

    def test_openai_returns_openai_adapter(self) -> None:
        assert isinstance(get_adapter("openai"), OpenAIAdapter)

    def test_anthropic_returns_anthropic_adapter(self) -> None:
        assert isinstance(get_adapter("anthropic"), AnthropicAdapter)

    def test_unknown_raises_axon_provider_error(self) -> None:
        with pytest.raises(AxonProviderError, match="Unknown provider"):
            get_adapter("cohere")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(AxonProviderError):
            get_adapter("")
