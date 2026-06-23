"""Unit tests for traject.providers.vertex.VertexAdapter.

Validates: Requirements 5.3 (VertexAdapter — token extraction, dependency guard).

Tests cover:
- TrajectDependencyError raised when google-cloud-aiplatform is not installed
- Correct token extraction from usage_metadata (prompt_token_count,
  candidates_token_count)
- content and provider label returned correctly
"""

from __future__ import annotations

import importlib
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from traject.exceptions import TrajectDependencyError
from traject.providers import ProviderResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vertex_response(
    text: str = "Hello from Vertex",
    prompt_token_count: int = 20,
    candidates_token_count: int = 10,
) -> MagicMock:
    """Return a mock Vertex AI GenerativeModel response.

    Mimics the shape accessed by VertexAdapter.complete():
        response.text
        response.usage_metadata.prompt_token_count
        response.usage_metadata.candidates_token_count

    Args:
        text: The generated text content.
        prompt_token_count: Simulated input token count.
        candidates_token_count: Simulated output token count.

    Returns:
        A MagicMock resembling a Vertex AI GenerateContentResponse.
    """
    usage_metadata = MagicMock()
    usage_metadata.prompt_token_count = prompt_token_count
    usage_metadata.candidates_token_count = candidates_token_count

    response = MagicMock()
    response.text = text
    response.usage_metadata = usage_metadata
    return response


def _make_vertex_adapter(response: MagicMock) -> Any:
    """Return a VertexAdapter with the vertexai SDK fully mocked.

    Patches both ``vertexai`` and ``vertexai.generative_models`` in sys.modules
    so the adapter's __init__ import guard is bypassed, then replaces the
    adapter's internal GenerativeModel factory with one that returns *response*.

    Args:
        response: Pre-built mock response to return from generate_content().

    Returns:
        A VertexAdapter instance backed entirely by mocks.
    """
    model_mock = MagicMock()
    model_mock.generate_content.return_value = response

    generative_model_cls = MagicMock(return_value=model_mock)

    vertexai_mock = MagicMock()
    generative_models_mock = MagicMock()
    generative_models_mock.GenerativeModel = generative_model_cls

    with patch.dict(
        sys.modules,
        {
            "vertexai": vertexai_mock,
            "vertexai.generative_models": generative_models_mock,
        },
    ):
        if "traject.providers.vertex" in sys.modules:
            del sys.modules["traject.providers.vertex"]
        from traject.providers.vertex import VertexAdapter

        adapter = VertexAdapter(project="test-project", location="us-central1")

    # After construction the adapter holds its own references; replace them
    # with our controlled mocks so generate_content returns the canned response.
    adapter._vertexai = vertexai_mock
    adapter._GenerativeModel = generative_model_cls
    return adapter


# ---------------------------------------------------------------------------
# Tests: dependency guard
# ---------------------------------------------------------------------------


class TestVertexAdapterDependencyGuard:
    """VertexAdapter raises TrajectDependencyError when google-cloud-aiplatform is absent.

    **Validates: Requirements 5.3**
    """

    def test_raises_dependency_error_when_vertexai_missing(self) -> None:
        """Instantiating VertexAdapter without vertexai raises TrajectDependencyError.

        Both ``vertexai`` and ``vertexai.generative_models`` are patched out
        so the import guard inside __init__ fires an ImportError.

        **Validates: Requirements 5.3**
        """
        with patch.dict(
            sys.modules,
            {
                "vertexai": None,
                "vertexai.generative_models": None,
            },
        ):
            if "traject.providers.vertex" in sys.modules:
                del sys.modules["traject.providers.vertex"]

            from traject.providers.vertex import VertexAdapter

            with pytest.raises(TrajectDependencyError, match="google-cloud-aiplatform"):
                VertexAdapter()

        if "traject.providers.vertex" in sys.modules:
            del sys.modules["traject.providers.vertex"]
        importlib.import_module("traject.providers.vertex")

    def test_dependency_error_message_includes_install_hint(self) -> None:
        """The TrajectDependencyError message tells the caller how to install the package.

        **Validates: Requirements 5.3**
        """
        with patch.dict(
            sys.modules,
            {
                "vertexai": None,
                "vertexai.generative_models": None,
            },
        ):
            if "traject.providers.vertex" in sys.modules:
                del sys.modules["traject.providers.vertex"]

            from traject.providers.vertex import VertexAdapter

            with pytest.raises(TrajectDependencyError, match="pip install"):
                VertexAdapter()

        if "traject.providers.vertex" in sys.modules:
            del sys.modules["traject.providers.vertex"]
        importlib.import_module("traject.providers.vertex")


# ---------------------------------------------------------------------------
# Tests: token extraction from usage_metadata
# ---------------------------------------------------------------------------


class TestVertexAdapterTokenExtraction:
    """VertexAdapter correctly extracts token counts from usage_metadata.

    usage_metadata shape:
        response.usage_metadata.prompt_token_count    → input_tokens
        response.usage_metadata.candidates_token_count → output_tokens

    **Validates: Requirements 5.3**
    """

    def test_input_tokens_from_prompt_token_count(self) -> None:
        """complete() maps usage_metadata.prompt_token_count to input_tokens.

        **Validates: Requirements 5.3**
        """
        vertex_response = _make_vertex_response(
            prompt_token_count=75,
            candidates_token_count=30,
        )
        adapter = _make_vertex_adapter(vertex_response)

        result: ProviderResponse = adapter.complete(
            messages=[{"role": "user", "content": "Hello"}],
            model="gemini-1.5-pro",
        )
        assert result.input_tokens == 75

    def test_output_tokens_from_candidates_token_count(self) -> None:
        """complete() maps usage_metadata.candidates_token_count to output_tokens.

        **Validates: Requirements 5.3**
        """
        vertex_response = _make_vertex_response(
            prompt_token_count=75,
            candidates_token_count=30,
        )
        adapter = _make_vertex_adapter(vertex_response)

        result: ProviderResponse = adapter.complete(
            messages=[{"role": "user", "content": "Hello"}],
            model="gemini-1.5-pro",
        )
        assert result.output_tokens == 30

    def test_zero_token_counts_handled(self) -> None:
        """complete() handles zero token counts without error.

        **Validates: Requirements 5.3**
        """
        vertex_response = _make_vertex_response(
            prompt_token_count=0,
            candidates_token_count=0,
        )
        adapter = _make_vertex_adapter(vertex_response)

        result: ProviderResponse = adapter.complete(
            messages=[{"role": "user", "content": "Hello"}],
            model="gemini-1.5-flash",
        )
        assert result.input_tokens == 0
        assert result.output_tokens == 0


# ---------------------------------------------------------------------------
# Tests: content and provider label
# ---------------------------------------------------------------------------


class TestVertexAdapterContentAndLabel:
    """VertexAdapter returns correct content and provider label.

    **Validates: Requirements 5.3**
    """

    def test_content_extracted_from_response_text(self) -> None:
        """complete() returns response.text as content.

        **Validates: Requirements 5.3**
        """
        vertex_response = _make_vertex_response(text="Vertex says hello")
        adapter = _make_vertex_adapter(vertex_response)

        result: ProviderResponse = adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="gemini-1.0-pro",
        )
        assert result.content == "Vertex says hello"

    def test_provider_label_is_vertex(self) -> None:
        """complete() sets provider='vertex'.

        **Validates: Requirements 5.3**
        """
        vertex_response = _make_vertex_response()
        adapter = _make_vertex_adapter(vertex_response)

        result: ProviderResponse = adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="gemini-1.5-pro",
        )
        assert result.provider == "vertex"

    def test_model_label_echoed_from_argument(self) -> None:
        """complete() echoes the model argument in the response model field.

        **Validates: Requirements 5.3**
        """
        vertex_response = _make_vertex_response()
        adapter = _make_vertex_adapter(vertex_response)

        result: ProviderResponse = adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="gemini-1.5-flash",
        )
        assert result.model == "gemini-1.5-flash"

    @pytest.mark.parametrize(
        "model",
        ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"],
        ids=["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"],
    )
    def test_supported_gemini_models(self, model: str) -> None:
        """complete() works for all three supported Gemini model identifiers.

        **Validates: Requirements 5.3**
        """
        vertex_response = _make_vertex_response(
            text=f"reply from {model}",
            prompt_token_count=10,
            candidates_token_count=5,
        )
        adapter = _make_vertex_adapter(vertex_response)

        result: ProviderResponse = adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model=model,
        )
        assert result.model == model
        assert result.input_tokens == 10
        assert result.output_tokens == 5
