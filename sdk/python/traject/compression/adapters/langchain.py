"""LangChain message format adapter for the Traject compression pipeline.

Normalizes LangChain BaseMessage subclasses to the canonical list[dict] format
required by the compression engine, and converts results back. Requires the
langchain-core optional dependency (pip install traject-sdk[langchain]).
"""
from __future__ import annotations

from typing import Any

from traject.exceptions import TrajectDependencyError

try:
    from langchain_core.messages import (
        AIMessage,
        BaseMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )
except ImportError as exc:
    raise TrajectDependencyError(
        "LangChain adapter requires langchain-core. "
        "Install it with: pip install traject-sdk[langchain]"
    ) from exc

from traject.compression.adapters.base import FrameworkAdapter


def _langchain_role(msg: BaseMessage) -> str:
    """Return the canonical role string for a LangChain message."""
    if isinstance(msg, SystemMessage):
        return "system"
    if isinstance(msg, HumanMessage):
        return "user"
    if isinstance(msg, AIMessage):
        return "assistant"
    if isinstance(msg, ToolMessage):
        return "tool"
    return "user"


class LangChainAdapter(FrameworkAdapter):
    """Adapter for LangChain BaseMessage list format.

    Converts LangChain's typed message objects (HumanMessage, AIMessage,
    SystemMessage, ToolMessage) to and from the canonical list[dict] format.
    Requires langchain-core to be installed.
    """

    @classmethod
    def accepts(cls, messages: Any) -> bool:
        """Return True if messages is a non-empty list of BaseMessage instances.

        Args:
            messages: Input to inspect.

        Returns:
            True iff messages is a non-empty list and messages[0] is a
            BaseMessage instance.
        """
        return (
            isinstance(messages, list)
            and len(messages) > 0
            and isinstance(messages[0], BaseMessage)
        )

    def normalize(self, messages: Any) -> list[dict[str, Any]]:
        """Convert LangChain BaseMessage list to canonical list[dict].

        Args:
            messages: List of LangChain BaseMessage subclass instances.

        Returns:
            List of dicts with 'role' and 'content' keys. tool_calls field
            included when present on an AIMessage.
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = _langchain_role(msg)
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            normalized: dict[str, Any] = {"role": role, "content": content}
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                normalized["tool_calls"] = msg.tool_calls
            result.append(normalized)
        return result

    def denormalize(
        self, messages: list[dict[str, Any]], original: Any
    ) -> list[BaseMessage]:
        """Convert canonical list[dict] back to LangChain BaseMessage list.

        Args:
            messages: Canonical list[dict] messages to convert.
            original: Original LangChain messages (unused, for type reference).

        Returns:
            List of LangChain BaseMessage subclass instances.
        """
        result: list[BaseMessage] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                result.append(SystemMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(content=content))
            elif role == "tool":
                result.append(ToolMessage(content=content, tool_call_id=""))
            else:
                result.append(HumanMessage(content=content))
        return result
