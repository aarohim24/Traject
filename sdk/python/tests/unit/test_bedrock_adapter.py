"""Unit tests for axon.providers.bedrock.BedrockAdapter.

Validates: Requirements 5.2 (BedrockAdapter — model-family dispatch, token extraction,
dependency guard).

Tests cover:
- AxonDependencyError raised when boto3 is absent (sys.modules patch)
- Titan response shape: inputTextTokenCount / results[0].tokenCount
- Claude-via-Bedrock response shape: usage.input_tokens / usage.output_tokens / content[0].text
- Llama response shape: prompt_token_count / generation_token_count / generation
"""
from __future__ import annotations

import importlib
import json
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from axon.exceptions import AxonDependencyError
from axon.providers import ProviderResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bedrock_client(response_body: dict[str, Any]) -> MagicMock:
    """Return a mock boto3 bedrock-runtime client.

    The ``invoke_model`` method returns a response whose ``body`` attribute
    behaves like a file-like object returning JSON-encoded *response_body*.

    Args:
        response_body: The parsed JSON that would appear in the Bedrock
            InvokeModel response body.

    Returns:
        A MagicMock that mimics a boto3 bedrock-runtime client.
    """
    body_bytes = json.dumps(response_body).encode()
    body_stream = MagicMock()
    body_stream.read.return_value = body_bytes

    invoke_response: dict[str, Any] = {"body": body_stream}

    client = MagicMock()
    client.invoke_model.return_value = invoke_response
    return client


def _make_boto3_mock(client: MagicMock) -> MagicMock:
    """Return a mock boto3 module whose ``.client()`` returns *client*.

    Args:
        client: Pre-configured mock bedrock-runtime client.

    Returns:
        A MagicMock that behaves like the boto3 module.
    """
    boto3_mock = MagicMock()
    boto3_mock.client.return_value = client
    return boto3_mock


# ---------------------------------------------------------------------------
# Tests: dependency guard
# ---------------------------------------------------------------------------


class TestBedrockAdapterDependencyGuard:
    """BedrockAdapter raises AxonDependencyError when boto3 is not installed.

    **Validates: Requirements 5.2**
    """

    def test_raises_dependency_error_when_boto3_missing(self) -> None:
        """Instantiating BedrockAdapter without boto3 raises AxonDependencyError.

        boto3 is patched out of sys.modules so the import guard fires.

        **Validates: Requirements 5.2**
        """
        with patch.dict(sys.modules, {"boto3": None}):
            # Force a fresh import so the patched sys.modules is seen
            if "axon.providers.bedrock" in sys.modules:
                del sys.modules["axon.providers.bedrock"]

            from axon.providers.bedrock import BedrockAdapter

            with pytest.raises(AxonDependencyError, match="boto3"):
                BedrockAdapter()

        # Restore the module for subsequent tests
        if "axon.providers.bedrock" in sys.modules:
            del sys.modules["axon.providers.bedrock"]
        importlib.import_module("axon.providers.bedrock")

    def test_dependency_error_message_includes_install_hint(self) -> None:
        """The AxonDependencyError message tells the caller how to install boto3.

        **Validates: Requirements 5.2**
        """
        with patch.dict(sys.modules, {"boto3": None}):
            if "axon.providers.bedrock" in sys.modules:
                del sys.modules["axon.providers.bedrock"]

            from axon.providers.bedrock import BedrockAdapter

            with pytest.raises(AxonDependencyError, match="pip install"):
                BedrockAdapter()

        if "axon.providers.bedrock" in sys.modules:
            del sys.modules["axon.providers.bedrock"]
        importlib.import_module("axon.providers.bedrock")


# ---------------------------------------------------------------------------
# Tests: Amazon Titan response extraction
# ---------------------------------------------------------------------------


class TestBedrockAdapterTitanResponse:
    """BedrockAdapter correctly extracts content and tokens from Titan responses.

    Titan response shape:
        {"inputTextTokenCount": N, "results": [{"outputText": "...", "tokenCount": M}]}

    **Validates: Requirements 5.2**
    """

    @pytest.fixture()
    def titan_adapter(self) -> Any:
        """Return a BedrockAdapter backed by a mock boto3 client (no AWS needed).

        The client is injected by patching ``boto3.client`` during init.
        """

        titan_response_body: dict[str, Any] = {
            "inputTextTokenCount": 42,
            "results": [
                {"outputText": "Hello from Titan", "tokenCount": 17},
            ],
        }
        mock_client = _make_bedrock_client(titan_response_body)
        boto3_mock = _make_boto3_mock(mock_client)

        with patch.dict(sys.modules, {"boto3": boto3_mock}):
            if "axon.providers.bedrock" in sys.modules:
                del sys.modules["axon.providers.bedrock"]
            from axon.providers.bedrock import (
                BedrockAdapter as BA,
            )
            adapter = BA()

        # Swap the real client for our controlled mock after construction
        adapter._client = mock_client
        return adapter

    def test_titan_content_extracted(self, titan_adapter: Any) -> None:
        """complete() returns the outputText field for Titan models.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = titan_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="amazon.titan-text-express-v1",
        )
        assert result.content == "Hello from Titan"

    def test_titan_input_tokens_extracted(self, titan_adapter: Any) -> None:
        """complete() maps inputTextTokenCount to input_tokens for Titan.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = titan_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="amazon.titan-text-express-v1",
        )
        assert result.input_tokens == 42

    def test_titan_output_tokens_extracted(self, titan_adapter: Any) -> None:
        """complete() maps results[0].tokenCount to output_tokens for Titan.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = titan_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="amazon.titan-text-express-v1",
        )
        assert result.output_tokens == 17

    def test_titan_provider_label(self, titan_adapter: Any) -> None:
        """complete() sets provider='bedrock' for Titan models.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = titan_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="amazon.titan-text-express-v1",
        )
        assert result.provider == "bedrock"


# ---------------------------------------------------------------------------
# Tests: Anthropic Claude-via-Bedrock response extraction
# ---------------------------------------------------------------------------


class TestBedrockAdapterClaudeResponse:
    """BedrockAdapter correctly extracts content and tokens from Claude responses.

    Claude-via-Bedrock response shape:
        {"usage": {"input_tokens": N, "output_tokens": M},
         "content": [{"text": "...", "type": "text"}]}

    **Validates: Requirements 5.2**
    """

    @pytest.fixture()
    def claude_adapter(self) -> Any:
        """Return a BedrockAdapter wired to return a mock Claude response body."""
        claude_response_body: dict[str, Any] = {
            "usage": {"input_tokens": 100, "output_tokens": 55},
            "content": [{"type": "text", "text": "Hello from Claude"}],
        }
        mock_client = _make_bedrock_client(claude_response_body)
        boto3_mock = _make_boto3_mock(mock_client)

        with patch.dict(sys.modules, {"boto3": boto3_mock}):
            if "axon.providers.bedrock" in sys.modules:
                del sys.modules["axon.providers.bedrock"]
            from axon.providers.bedrock import (
                BedrockAdapter as BA,
            )
            adapter = BA()

        adapter._client = mock_client
        return adapter

    def test_claude_content_extracted(self, claude_adapter: Any) -> None:
        """complete() returns content[0].text for Claude-via-Bedrock models.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = claude_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="anthropic.claude-3-sonnet-20240229-v1:0",
        )
        assert result.content == "Hello from Claude"

    def test_claude_input_tokens_extracted(self, claude_adapter: Any) -> None:
        """complete() maps usage.input_tokens to input_tokens for Claude.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = claude_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="anthropic.claude-3-sonnet-20240229-v1:0",
        )
        assert result.input_tokens == 100

    def test_claude_output_tokens_extracted(self, claude_adapter: Any) -> None:
        """complete() maps usage.output_tokens to output_tokens for Claude.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = claude_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="anthropic.claude-3-sonnet-20240229-v1:0",
        )
        assert result.output_tokens == 55

    def test_claude_provider_label(self, claude_adapter: Any) -> None:
        """complete() sets provider='bedrock' for Claude-via-Bedrock models.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = claude_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="anthropic.claude-3-sonnet-20240229-v1:0",
        )
        assert result.provider == "bedrock"


# ---------------------------------------------------------------------------
# Tests: Meta Llama response extraction
# ---------------------------------------------------------------------------


class TestBedrockAdapterLlamaResponse:
    """BedrockAdapter correctly extracts content and tokens from Llama responses.

    Llama response shape:
        {"generation": "...", "prompt_token_count": N, "generation_token_count": M}

    **Validates: Requirements 5.2**
    """

    @pytest.fixture()
    def llama_adapter(self) -> Any:
        """Return a BedrockAdapter wired to return a mock Llama response body."""
        llama_response_body: dict[str, Any] = {
            "generation": "Hello from Llama",
            "prompt_token_count": 30,
            "generation_token_count": 12,
        }
        mock_client = _make_bedrock_client(llama_response_body)
        boto3_mock = _make_boto3_mock(mock_client)

        with patch.dict(sys.modules, {"boto3": boto3_mock}):
            if "axon.providers.bedrock" in sys.modules:
                del sys.modules["axon.providers.bedrock"]
            from axon.providers.bedrock import (
                BedrockAdapter as BA,
            )
            adapter = BA()

        adapter._client = mock_client
        return adapter

    def test_llama_content_extracted(self, llama_adapter: Any) -> None:
        """complete() returns the generation field for Llama models.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = llama_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="meta.llama3-8b-instruct-v1:0",
        )
        assert result.content == "Hello from Llama"

    def test_llama_input_tokens_extracted(self, llama_adapter: Any) -> None:
        """complete() maps prompt_token_count to input_tokens for Llama.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = llama_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="meta.llama3-8b-instruct-v1:0",
        )
        assert result.input_tokens == 30

    def test_llama_output_tokens_extracted(self, llama_adapter: Any) -> None:
        """complete() maps generation_token_count to output_tokens for Llama.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = llama_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="meta.llama3-8b-instruct-v1:0",
        )
        assert result.output_tokens == 12

    def test_llama_provider_label(self, llama_adapter: Any) -> None:
        """complete() sets provider='bedrock' for Llama models.

        **Validates: Requirements 5.2**
        """
        result: ProviderResponse = llama_adapter.complete(
            messages=[{"role": "user", "content": "Hi"}],
            model="meta.llama3-8b-instruct-v1:0",
        )
        assert result.provider == "bedrock"


# ---------------------------------------------------------------------------
# Tests: unsupported model raises ValueError
# ---------------------------------------------------------------------------


class TestBedrockAdapterUnsupportedModel:
    """BedrockAdapter raises ValueError for unrecognised model prefixes.

    **Validates: Requirements 5.2**
    """

    @pytest.fixture()
    def adapter(self) -> Any:
        """Return a generic BedrockAdapter with a mock client."""
        mock_client = _make_bedrock_client({})
        boto3_mock = _make_boto3_mock(mock_client)

        with patch.dict(sys.modules, {"boto3": boto3_mock}):
            if "axon.providers.bedrock" in sys.modules:
                del sys.modules["axon.providers.bedrock"]
            from axon.providers.bedrock import (
                BedrockAdapter as BA,
            )
            adapter = BA()

        adapter._client = mock_client
        return adapter

    def test_unsupported_model_raises_value_error(self, adapter: Any) -> None:
        """complete() raises ValueError for a model not matching any prefix.

        **Validates: Requirements 5.2**
        """
        with pytest.raises(ValueError, match="Unsupported Bedrock model prefix"):
            adapter.complete(
                messages=[{"role": "user", "content": "Hi"}],
                model="cohere.command-r-v1:0",
            )
