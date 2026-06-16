"""AWS Bedrock provider adapter for the Axon SDK.

Translates the Axon message format into Bedrock InvokeModel request bodies
for three model families (Amazon Titan, Anthropic Claude, Meta Llama) and
normalises the response into a :class:`~axon.providers.ProviderResponse`.

boto3 is an optional dependency; an :class:`~axon.exceptions.AxonDependencyError`
is raised at construction time if it is not installed.
"""
from __future__ import annotations

import json
from typing import Any

from traject.exceptions import AxonDependencyError
from traject.providers import ProviderResponse

_logger_name = __name__


class BedrockAdapter:
    """AWS Bedrock provider adapter.

    Translates Axon message format → Bedrock InvokeModel request body
    for three model families.

    Args:
        region_name: AWS region for the Bedrock endpoint.  Defaults to
            the ``AWS_DEFAULT_REGION`` environment variable when ``None``.

    Raises:
        AxonDependencyError: If boto3 is not installed.
    """

    # Supported model-family prefixes
    _TITAN_PREFIX: str = "amazon.titan"
    _CLAUDE_PREFIX: str = "anthropic.claude"
    _LLAMA_PREFIX: str = "meta.llama"

    def __init__(self, region_name: str | None = None) -> None:
        """Initialise the adapter, guarding the boto3 import.

        Args:
            region_name: AWS region passed to the Bedrock Runtime client.
                When ``None``, boto3 falls back to the ``AWS_DEFAULT_REGION``
                environment variable or the active AWS profile.

        Raises:
            AxonDependencyError: If boto3 is not installed.
        """
        try:
            import boto3
            self._client: Any = boto3.client(  # Any: boto3 client has no stubs
                "bedrock-runtime", region_name=region_name
            )
        except ImportError as exc:
            raise AxonDependencyError(
                "AWS Bedrock support requires boto3. "
                "Install it with: pip install 'axon-sdk[bedrock]'"
            ) from exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_request_body(
        self,
        messages: list[dict[str, Any]],  # Any: message content type varies
        model: str,
        **kwargs: Any,  # Any: forwarded as extra model parameters
    ) -> dict[str, Any]:  # Any: body shape differs per model family
        """Build the Bedrock InvokeModel request body for the given model family.

        Args:
            messages: Axon-format message list (``{"role": ..., "content": ...}``).
            model: Bedrock model identifier used to select the body shape.
            **kwargs: Extra parameters forwarded into the request body.

        Returns:
            A dict ready for JSON serialisation as the Bedrock request body.

        Raises:
            ValueError: If the model prefix is not recognised.
        """
        if model.startswith(self._TITAN_PREFIX):
            text = "\n".join(
                str(m.get("content", "")) for m in messages
            )
            body: dict[str, Any] = {"inputText": text}  # Any: Titan body
            body.update(kwargs)
            return body

        if model.startswith(self._CLAUDE_PREFIX):
            max_tokens: int = int(kwargs.pop("max_tokens", 4096))
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "messages": messages,
                "max_tokens": max_tokens,
            }
            body.update(kwargs)
            return body

        if model.startswith(self._LLAMA_PREFIX):
            prompt_parts = []
            for m in messages:
                role = m.get("role", "user")
                content = str(m.get("content", ""))
                prompt_parts.append(f"[{role}]: {content}")
            prompt = "\n".join(prompt_parts)
            max_gen_len: int = int(kwargs.pop("max_gen_len", 512))
            body = {"prompt": prompt, "max_gen_len": max_gen_len}
            body.update(kwargs)
            return body

        raise ValueError(
            f"Unsupported Bedrock model prefix for model {model!r}. "
            f"Supported prefixes: {self._TITAN_PREFIX!r}, "
            f"{self._CLAUDE_PREFIX!r}, {self._LLAMA_PREFIX!r}."
        )

    @staticmethod
    def _extract_content_and_tokens(
        response_body: dict[str, Any],  # Any: response shape varies per family
        model: str,
    ) -> tuple[str, int, int]:
        """Extract generated text and token counts from a Bedrock response body.

        Args:
            response_body: Parsed JSON response body from Bedrock InvokeModel.
            model: Bedrock model identifier used to select the extraction path.

        Returns:
            A 3-tuple of ``(content, input_tokens, output_tokens)``.

        Raises:
            ValueError: If the model prefix is not recognised.
        """
        if model.startswith(BedrockAdapter._TITAN_PREFIX):
            # Any: Titan results list contains dicts with provider-specific keys
            results: list[dict[str, Any]] = response_body.get("results", [{}])
            content = str(results[0].get("outputText", "")) if results else ""
            input_tokens = int(response_body.get("inputTextTokenCount", 0))
            output_tokens = int(results[0].get("tokenCount", 0)) if results else 0
            return content, input_tokens, output_tokens

        if model.startswith(BedrockAdapter._CLAUDE_PREFIX):
            # Any: Claude content list contains dicts with provider-specific keys
            contents: list[dict[str, Any]] = response_body.get("content", [{}])
            content = str(contents[0].get("text", "")) if contents else ""
            usage: dict[str, Any] = response_body.get("usage", {})  # Any: usage shape
            input_tokens = int(usage.get("input_tokens", 0))
            output_tokens = int(usage.get("output_tokens", 0))
            return content, input_tokens, output_tokens

        if model.startswith(BedrockAdapter._LLAMA_PREFIX):
            content = str(response_body.get("generation", ""))
            input_tokens = int(response_body.get("prompt_token_count", 0))
            output_tokens = int(response_body.get("generation_token_count", 0))
            return content, input_tokens, output_tokens

        raise ValueError(
            f"Unsupported Bedrock model prefix for model {model!r}. "
            f"Supported prefixes: {BedrockAdapter._TITAN_PREFIX!r}, "
            f"{BedrockAdapter._CLAUDE_PREFIX!r}, {BedrockAdapter._LLAMA_PREFIX!r}."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(
        self,
        messages: list[dict[str, Any]],  # Any: message content type varies
        model: str,
        **kwargs: Any,  # Any: forwarded to boto3 invoke_model as extra params
    ) -> ProviderResponse:
        """Invoke a Bedrock model and return a normalised provider response.

        Selects the request body shape by checking the ``model`` prefix
        against the three supported model families (Titan, Claude, Llama),
        calls ``bedrock-runtime:InvokeModel``, and extracts the generated
        text and token counts from the family-specific response structure.

        Args:
            messages: Axon-format message list, each entry a dict with at
                least ``"role"`` and ``"content"`` keys.
            model: Bedrock model identifier, e.g.
                ``"anthropic.claude-3-sonnet-20240229-v1:0"``.
            **kwargs: Additional parameters forwarded into the request body
                (e.g. ``max_tokens`` for Claude, ``max_gen_len`` for Llama).

        Returns:
            A :class:`~axon.providers.ProviderResponse` with
            ``provider="bedrock"``.

        Raises:
            ValueError: If the model prefix is not one of the three supported
                families.
            botocore.exceptions.BotoCoreError: For underlying AWS SDK errors
                (network failures, auth errors, throttling, etc.).
        """
        body = self._build_request_body(messages, model, **kwargs)

        raw: Any = self._client.invoke_model(  # Any: boto3 response has no stubs
            body=json.dumps(body),
            modelId=model,
            contentType="application/json",
            accept="application/json",
        )

        response_body: dict[str, Any] = json.loads(  # Any: response body shape varies
            raw["body"].read()
        )

        content, input_tokens, output_tokens = self._extract_content_and_tokens(
            response_body, model
        )

        return ProviderResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            provider="bedrock",
            raw_response=response_body,
        )
