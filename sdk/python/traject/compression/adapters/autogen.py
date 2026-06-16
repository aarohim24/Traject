"""AutoGen message format adapter for the Axon compression pipeline.

Normalizes AutoGen-style message dicts (which include a 'name' field in
addition to 'role' and 'content') to the canonical list[dict] format, and
converts results back. Requires the pyautogen optional dependency
(pip install axon-sdk[autogen]).
"""
from __future__ import annotations

from typing import Any

from traject.exceptions import AxonDependencyError

try:
    import autogen  # noqa: F401  # optional dep — stubs handled via mypy override
except ImportError as exc:
    raise AxonDependencyError(
        "AutoGen adapter requires pyautogen. "
        "Install it with: pip install axon-sdk[autogen]"
    ) from exc

from traject.compression.adapters.base import FrameworkAdapter


class AutoGenAdapter(FrameworkAdapter):
    """Adapter for AutoGen-style message dict format.

    AutoGen messages are dicts with 'role', 'content', and 'name' keys.
    The adapter strips the 'name' field on normalize and re-adds it on
    denormalize using the corresponding original message.
    """

    @classmethod
    def accepts(cls, messages: Any) -> bool:
        """Return True if messages looks like an AutoGen message list.

        Args:
            messages: Input to inspect.

        Returns:
            True iff messages is a non-empty list, messages[0] is a dict,
            and messages[0] contains 'role', 'content', AND 'name' keys
            (the 'name' field distinguishes AutoGen from raw OpenAI format).
        """
        return (
            isinstance(messages, list)
            and len(messages) > 0
            and isinstance(messages[0], dict)
            and "role" in messages[0]
            and "content" in messages[0]
            and "name" in messages[0]
        )

    def normalize(self, messages: Any) -> list[dict[str, Any]]:
        """Strip the 'name' field and return canonical role/content dicts.

        Args:
            messages: List of AutoGen-style message dicts.

        Returns:
            List of canonical dicts with 'role' and 'content' keys only.
        """
        return [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages
        ]

    def denormalize(
        self, messages: list[dict[str, Any]], original: Any
    ) -> list[dict[str, Any]]:
        """Re-add the 'name' field from the original messages where available.

        Args:
            messages: Canonical list[dict] messages to convert.
            original: Original AutoGen-style messages (for 'name' field lookup).

        Returns:
            List of AutoGen-style message dicts with 'name' restored where
            possible.
        """
        result: list[dict[str, Any]] = []
        for i, msg in enumerate(messages):
            entry: dict[str, Any] = {
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            }
            if isinstance(original, list) and i < len(original):
                orig = original[i]
                if isinstance(orig, dict) and "name" in orig:
                    entry["name"] = orig["name"]
            result.append(entry)
        return result
