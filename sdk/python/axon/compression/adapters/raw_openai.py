"""Framework adapter for raw OpenAI-style list[dict] messages.

Handles the canonical format used by the OpenAI Python SDK: a list of dicts
with 'role' and 'content' keys. This is the always-available default adapter
requiring no optional dependencies.
"""
from __future__ import annotations
from typing import Any
from axon.compression.adapters.base import FrameworkAdapter


class RawOpenAIAdapter(FrameworkAdapter):
    """Adapter for raw OpenAI-style list[dict] message format.

    Since the OpenAI dict format is already the canonical format, both
    normalize() and denormalize() are identity operations.
    """

    @classmethod
    def accepts(cls, messages: Any) -> bool:
        """Return True if messages is a non-empty list[dict] with role+content.

        Args:
            messages: Input to inspect.

        Returns:
            True iff messages is a non-empty list, messages[0] is a dict,
            and messages[0] contains both 'role' and 'content' keys.
        """
        return (
            isinstance(messages, list)
            and len(messages) > 0
            and isinstance(messages[0], dict)
            and "role" in messages[0]
            and "content" in messages[0]
        )

    def normalize(self, messages: Any) -> list[dict[str, Any]]:
        """Return messages unchanged — raw OpenAI format is already canonical.

        Args:
            messages: list[dict] in OpenAI chat format.

        Returns:
            The same list, unmodified.
        """
        result: list[dict[str, Any]] = messages
        return result

    def denormalize(self, messages: list[dict[str, Any]], original: Any) -> Any:
        """Return messages unchanged — canonical format equals OpenAI format.

        Args:
            messages: Canonical list[dict] messages.
            original: Unused for this adapter.

        Returns:
            The same messages list, unmodified.
        """
        return messages
