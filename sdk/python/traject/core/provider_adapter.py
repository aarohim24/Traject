"""Provider adapters for normalizing LLM API response shapes.

This module isolates all provider-specific field access behind a uniform
``ProviderAdapter`` ABC.  Each concrete adapter reads the relevant usage fields
from a raw provider response object and returns a ``UsageData`` dataclass with
a consistent interface.  The ``get_adapter`` factory function returns the
correct adapter for a given provider string.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from traject.exceptions import TrajectProviderError


@dataclass
class UsageData:
    """Normalized token usage extracted from a provider response.

    Attributes:
        input_tokens: Number of input/prompt tokens consumed.
        output_tokens: Number of output/completion tokens generated.
        cached_tokens: Number of tokens served from the provider's cache.
        token_count_method: Whether the counts are ``"exact"`` (read directly
            from the response) or ``"estimated"`` (approximated, e.g. during
            streaming when the provider has not yet reported usage).
    """

    input_tokens: int
    output_tokens: int
    cached_tokens: int
    token_count_method: Literal["exact", "estimated"]


class ProviderAdapter(ABC):
    """Abstract base class for provider-specific response adapters.

    Subclasses implement the three abstract methods to extract normalized usage
    data, the model identifier, and streaming status from a raw provider
    response object.  Each method accepts ``Any`` because provider SDKs return
    opaque response types that vary by provider and by call mode (streaming vs.
    non-streaming).

    Example:
        adapter = OpenAIAdapter()
        usage = adapter.extract_usage(openai_response)
        model = adapter.extract_model(openai_response)
    """

    @abstractmethod
    def extract_usage(self, response: Any) -> UsageData:  # noqa: ANN401 — provider response is opaque
        """Extract normalized token usage from a provider response.

        Args:
            response: The raw response object returned by the provider SDK.

        Returns:
            A ``UsageData`` instance with token counts and the count method.
        """

    @abstractmethod
    def extract_model(self, response: Any) -> str:  # noqa: ANN401
        """Extract the model identifier from a provider response.

        Args:
            response: The raw response object returned by the provider SDK.

        Returns:
            The model name as a string.  Returns ``"unknown"`` when the field
            is absent.
        """

    @abstractmethod
    def is_streaming(self, response: Any) -> bool:  # noqa: ANN401
        """Return ``True`` if the response is a streaming response.

        Args:
            response: The raw response object returned by the provider SDK.

        Returns:
            ``True`` when the response represents an in-progress or chunked
            stream; ``False`` for a complete, non-streaming response.
        """


class OpenAIAdapter(ProviderAdapter):
    """Provider adapter for OpenAI API responses.

    Handles both standard ``ChatCompletion`` responses and streaming
    ``ChatCompletionChunk`` / ``Stream`` objects.  Token counts are read from
    ``response.usage`` using the OpenAI SDK field names
    (``prompt_tokens`` / ``completion_tokens``).

    For streaming responses where ``usage`` is ``None``, all token counts are
    returned as zero with ``token_count_method="estimated"``.
    """

    def is_streaming(self, response: Any) -> bool:  # noqa: ANN401
        """Return ``True`` for OpenAI streaming response objects.

        A response is considered streaming when it lacks a ``choices``
        attribute, or when its class name contains ``"Stream"`` or ``"Chunk"``.

        Args:
            response: The raw response object returned by the OpenAI SDK.

        Returns:
            ``True`` for streaming responses, ``False`` otherwise.
        """
        type_name = type(response).__name__
        return (
            not hasattr(response, "choices")
            or "Stream" in type_name
            or "Chunk" in type_name
        )

    def extract_usage(self, response: Any) -> UsageData:  # noqa: ANN401
        """Extract token usage from an OpenAI response.

        For streaming responses, attempts to read ``response.usage``; if
        ``usage`` is ``None`` (most streaming chunks), returns zeros with
        ``token_count_method="estimated"``.  For non-streaming responses,
        reads exact counts from ``response.usage`` with
        ``token_count_method="exact"``.

        Cached token savings are read from
        ``response.usage.prompt_tokens_details.cached_tokens`` when present.

        Args:
            response: The raw response object returned by the OpenAI SDK.

        Returns:
            A ``UsageData`` instance with token counts and count method.
        """
        if self.is_streaming(response):
            usage = getattr(response, "usage", None)
            if usage is None:
                return UsageData(
                    input_tokens=0,
                    output_tokens=0,
                    cached_tokens=0,
                    token_count_method="estimated",
                )
            method: Literal["exact", "estimated"] = "estimated"
        else:
            usage = response.usage
            method = "exact"

        cached: int = (
            getattr(
                getattr(usage, "prompt_tokens_details", None),
                "cached_tokens",
                0,
            )
            or 0
        )
        return UsageData(
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cached_tokens=cached,
            token_count_method=method,
        )

    def extract_model(self, response: Any) -> str:  # noqa: ANN401
        """Extract the model identifier from an OpenAI response.

        Args:
            response: The raw response object returned by the OpenAI SDK.

        Returns:
            The model name string, or ``"unknown"`` if the field is absent.
        """
        return str(getattr(response, "model", "unknown"))


class AnthropicAdapter(ProviderAdapter):
    """Provider adapter for Anthropic API responses.

    Handles both standard ``Message`` responses and streaming
    ``MessageStream`` / event objects.  Token counts are read from
    ``response.usage`` using the Anthropic SDK field names
    (``input_tokens`` / ``output_tokens``).

    Cache read token savings are read from
    ``response.usage.cache_read_input_tokens`` when present.
    """

    def is_streaming(self, response: Any) -> bool:  # noqa: ANN401
        """Return ``True`` for Anthropic streaming response objects.

        A response is considered streaming when its class name contains
        ``"Stream"`` or ``"Event"``.

        Args:
            response: The raw response object returned by the Anthropic SDK.

        Returns:
            ``True`` for streaming responses, ``False`` otherwise.
        """
        type_name = type(response).__name__
        return "Stream" in type_name or "Event" in type_name

    def extract_usage(self, response: Any) -> UsageData:  # noqa: ANN401
        """Extract token usage from an Anthropic response.

        Reads exact token counts from ``response.usage``.  Cache read savings
        are read from ``response.usage.cache_read_input_tokens`` when present.

        Args:
            response: The raw response object returned by the Anthropic SDK.

        Returns:
            A ``UsageData`` instance with ``token_count_method="exact"``.
        """
        usage = response.usage
        cached_read: int = getattr(usage, "cache_read_input_tokens", 0) or 0
        return UsageData(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=cached_read,
            token_count_method="exact",
        )

    def extract_model(self, response: Any) -> str:  # noqa: ANN401
        """Extract the model identifier from an Anthropic response.

        Args:
            response: The raw response object returned by the Anthropic SDK.

        Returns:
            The model name string, or ``"unknown"`` if the field is absent.
        """
        return str(getattr(response, "model", "unknown"))


def get_adapter(provider: str) -> ProviderAdapter:
    """Return the appropriate ``ProviderAdapter`` for the given provider name.

    Args:
        provider: The provider identifier string.  Supported values are
            ``"openai"`` and ``"anthropic"``.

    Returns:
        A concrete ``ProviderAdapter`` instance for the requested provider.

    Raises:
        TrajectProviderError: If ``provider`` is not a supported provider string.

    Example:
        adapter = get_adapter("openai")
        usage = adapter.extract_usage(response)
    """
    if provider == "openai":
        return OpenAIAdapter()
    if provider == "anthropic":
        return AnthropicAdapter()
    raise TrajectProviderError(
        f"Unknown provider {provider!r}. Supported providers are: 'openai',"
        " 'anthropic'. Pass the provider name as a string to get_adapter()."
    )
