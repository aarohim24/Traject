"""Provider adapter interfaces and shared response types for Traject SDK.

Contains the :class:`ProviderResponse` dataclass that all provider adapters
(``BedrockAdapter``, ``VertexAdapter``) return, plus lazy-import guards so
that adapters are importable from ``traject.providers`` without requiring their
optional cloud-SDK dependencies to be installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ProviderResponse:
    """Normalized response from any supported LLM provider.

    All provider adapters (``BedrockAdapter``, ``VertexAdapter``) return an
    instance of this dataclass so that downstream Traject components can work
    with a single, consistent response type regardless of the underlying
    cloud SDK.

    Attributes:
        content: Extracted text content from the model response.
        input_tokens: Prompt tokens consumed.
        output_tokens: Completion tokens generated.
        model: Model identifier as returned by the provider.
        provider: Provider name (e.g. ``"bedrock"``, ``"vertex"``).
        raw_response: Original provider response as a plain dict.
    """

    content: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
    raw_response: dict[str, Any]  # Any: provider dict structure varies


def __getattr__(name: str) -> Any:  # Any: dynamic module attribute
    """Lazily import provider adapter classes to avoid hard optional dependencies.

    Supports ``from traject.providers import BedrockAdapter`` and
    ``from traject.providers import VertexAdapter`` without requiring ``boto3``
    or ``google-cloud-aiplatform`` to be installed unless the adapter is
    actually used.

    Args:
        name: Attribute name being looked up on this module.

    Returns:
        The requested adapter class.

    Raises:
        AttributeError: If ``name`` is not a known lazy-importable attribute.
    """
    if name == "BedrockAdapter":
        from traject.providers.bedrock import BedrockAdapter

        return BedrockAdapter
    if name == "VertexAdapter":
        from traject.providers.vertex import VertexAdapter

        return VertexAdapter
    raise AttributeError(f"module 'traject.providers' has no attribute {name!r}")
