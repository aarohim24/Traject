"""Abstract base classes for the Axon plugin system.

Defines the three plugin ABCs — :class:`CompressionPlugin`,
:class:`RoutingPlugin`, and :class:`ArtifactClassifierPlugin` — that
third-party packages implement to extend Axon's compression, routing, and
artifact-classification pipelines without modifying the core SDK.

All ABCs use :mod:`abc` so that instantiating an incomplete subclass raises
``TypeError`` immediately at construction time rather than at call time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from axon.classifier.artifact_type import ArtifactType
from axon.router.routing_table import RoutingDecision


class CompressionPlugin(ABC):
    """Abstract base class for custom compression plugins.

    Implement this interface to inject custom segment-level compression logic
    into the Axon compression pipeline.  Registered plugins are invoked in
    registration order; the output of plugin *N* is passed as input to
    plugin *N+1* before the standard strategy engine runs.
    """

    @abstractmethod
    def compress(
        self,
        segments: list[str],
        **kwargs: Any,  # Any: provider-specific kwargs
    ) -> list[str]:
        """Apply custom compression to a list of segment strings.

        Args:
            segments: List of message content strings to compress.
            **kwargs: Provider-specific parameters (reserved for future use).

        Returns:
            Transformed list of segment strings (same or shorter length).
        """
        ...


class RoutingPlugin(ABC):
    """Abstract base class for custom routing plugins.

    Implement this interface to override or supplement Axon's default
    routing logic.  When a ``RoutingPlugin`` returns a non-``None``
    :class:`~axon.router.routing_table.RoutingDecision`, the default router
    is **not** invoked for that request.
    """

    @abstractmethod
    def route(
        self,
        messages: list[dict[str, Any]],  # Any: message value types vary by provider
        requested_model: str,
        **kwargs: Any,  # Any: provider-specific kwargs
    ) -> RoutingDecision | None:
        """Optionally override the routing decision.

        Args:
            messages: Ordered list of message dicts following the OpenAI
                chat completions schema.
            requested_model: The model identifier originally requested by
                the caller.
            **kwargs: Provider-specific parameters (reserved for future use).

        Returns:
            A :class:`~axon.router.routing_table.RoutingDecision` to
            override the default router, or ``None`` to defer to the
            default router.
        """
        ...


class ArtifactClassifierPlugin(ABC):
    """Abstract base class for custom artifact classifier plugins.

    Implement this interface to override or supplement Axon's built-in
    heuristic artifact-type classification.  When a plugin returns a
    non-``None`` :class:`~axon.classifier.artifact_type.ArtifactType`,
    the default classifier is **not** invoked for that message.
    """

    @abstractmethod
    def classify(
        self,
        content: str,
        **kwargs: Any,  # Any: provider-specific kwargs
    ) -> ArtifactType | None:
        """Optionally override artifact type classification.

        Args:
            content: The raw text content of the message to classify.
            **kwargs: Provider-specific parameters (reserved for future use).

        Returns:
            An :class:`~axon.classifier.artifact_type.ArtifactType` to
            override the default classifier, or ``None`` to defer to the
            default classifier.
        """
        ...
