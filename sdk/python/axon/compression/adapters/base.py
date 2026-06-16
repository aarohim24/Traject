"""Abstract base class for framework message format adapters.

Defines the FrameworkAdapter ABC that normalizes framework-specific message
formats into a canonical list[dict] for the compression engine to process,
and converts results back to the original format.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class FrameworkAdapter(ABC):
    """Abstract base for normalizing framework-specific message formats.

    Each concrete adapter handles one framework's message format. The
    compression engine depends only on this interface — never on a specific
    framework directly (ADR-009).

    Attributes:
        N/A — stateless interface.
    """

    @abstractmethod
    def normalize(self, messages: Any) -> list[dict[str, Any]]:
        """Convert framework messages to canonical list[dict] format.

        Args:
            messages: Messages in the framework's native format.

        Returns:
            List of dicts each containing at minimum 'role' and 'content' keys.
        """
        ...

    @abstractmethod
    def denormalize(self, messages: list[dict[str, Any]], original: Any) -> Any:
        """Convert canonical dicts back to the framework's native format.

        Args:
            messages: Canonical list[dict] messages.
            original: The original framework messages (for type/structure reference).

        Returns:
            Messages in the framework's native format.
        """
        ...

    @classmethod
    @abstractmethod
    def accepts(cls, messages: Any) -> bool:
        """Return True if this adapter can handle the given messages input.

        Args:
            messages: The messages value to inspect.

        Returns:
            True if this adapter should be selected for this input format.
        """
        ...
