"""Heuristic artifact-type classifier for LLM message sequences.

Classifies each message in a conversation into one of nine ``ArtifactType``
values using a deterministic, priority-ordered chain of string heuristics.
No ML, no I/O, and no imports beyond the Python standard library are used,
guaranteeing sub-millisecond classification and zero side effects.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ArtifactType(StrEnum):
    """Enumeration of the nine canonical artifact types for message segments.

    Inherits from ``StrEnum`` so that enum values can be used directly as
    JSON-serialisable strings without an explicit ``.value`` access.
    """

    SYSTEM_PROMPT = "system_prompt"
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_RESULT = "tool_result"
    TOOL_CALL = "tool_call"
    RAG_CHUNK = "rag_chunk"
    FEW_SHOT_EXAMPLE = "few_shot_example"
    REASONING_BLOCK = "reasoning_block"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Marker sets
# ---------------------------------------------------------------------------

_RAG_MARKERS: frozenset[str] = frozenset(
    [
        "context:",
        "retrieved:",
        "source:",
        "document:",
        "passage:",
        "[doc]",
        "[context]",
        "[retrieved]",
    ]
)

_FEW_SHOT_MARKERS: frozenset[str] = frozenset(
    [
        "example:",
        "input:",
        "output:",
        "q:",
        "a:",
        "question:",
        "answer:",
        "demonstration:",
    ]
)

_REASONING_MARKERS: frozenset[str] = frozenset(
    [
        "<thinking>",
        "<reasoning>",
        "<scratchpad>",
        "let me think",
        "step by step",
        "chain of thought",
    ]
)


# ---------------------------------------------------------------------------
# Private marker-detection helpers
# ---------------------------------------------------------------------------


def _has_rag_markers(content: str) -> bool:
    """Return True if *content* contains at least one RAG-chunk marker."""
    lower = content.lower()
    return any(marker in lower for marker in _RAG_MARKERS)


def _has_few_shot_markers(content: str) -> bool:
    """Return True if *content* contains at least one few-shot marker."""
    lower = content.lower()
    return any(marker in lower for marker in _FEW_SHOT_MARKERS)


def _has_reasoning_markers(content: str) -> bool:
    """Return True if *content* contains at least one reasoning marker."""
    lower = content.lower()
    return any(marker in lower for marker in _REASONING_MARKERS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify(
    message: dict[str, Any],
    position_index: int,
    total_messages: int,
) -> ArtifactType:
    """Classify a single message into an ArtifactType.

    Args:
        message: Message dict with at minimum a ``'role'`` key.  Missing keys
            are treated as empty strings or empty collections; the function
            never raises regardless of what is passed.
        position_index: Zero-based index of this message in the sequence.
        total_messages: Total number of messages in the sequence.

    Returns:
        ArtifactType enum value determined by the first matching rule in the
        strict 9-priority chain below.  Never raises.

    Notes:
        Heuristic-only — no ML, no I/O.  Completes in < 1 ms per message.
        ``SYSTEM_PROMPT`` classification is unconditional and can never be
        overridden by content heuristics.

        Priority order:
        1. ``role == "system"``               → SYSTEM_PROMPT
        2. ``role == "tool"``                 → TOOL_RESULT
        3. Non-empty ``tool_calls`` field     → TOOL_CALL
        4. ``role == "assistant"`` + reasoning markers → REASONING_BLOCK
        5. ``role == "user"`` + position 0 + few-shot markers → FEW_SHOT_EXAMPLE
        6. ``role == "user"`` + RAG markers   → RAG_CHUNK
        7. ``role == "user"``                 → USER_MESSAGE
        8. ``role == "assistant"``            → ASSISTANT_MESSAGE
        9. Fallback                           → UNKNOWN
    """
    role: str = message.get("role") or ""
    raw_content: Any = message.get("content") or ""
    content: str = raw_content if isinstance(raw_content, str) else ""
    tool_calls: Any = message.get("tool_calls") or []

    # Priority 1: system role — NEVER overridden
    if role == "system":
        return ArtifactType.SYSTEM_PROMPT

    # Priority 2: tool result
    if role == "tool":
        return ArtifactType.TOOL_RESULT

    # Priority 3: has non-empty tool_calls field
    if tool_calls:
        return ArtifactType.TOOL_CALL

    # Priority 4: assistant with reasoning markers
    if role == "assistant" and _has_reasoning_markers(content):
        return ArtifactType.REASONING_BLOCK

    # Priority 5: user at position 0 with few-shot markers
    if role == "user" and position_index == 0 and _has_few_shot_markers(content):
        return ArtifactType.FEW_SHOT_EXAMPLE

    # Priority 6: user with RAG chunk markers
    if role == "user" and _has_rag_markers(content):
        return ArtifactType.RAG_CHUNK

    # Priority 7: plain user message
    if role == "user":
        return ArtifactType.USER_MESSAGE

    # Priority 8: plain assistant message
    if role == "assistant":
        return ArtifactType.ASSISTANT_MESSAGE

    # Priority 9: fallback
    return ArtifactType.UNKNOWN


def classify_sequence(messages: list[dict[str, Any]]) -> list[ArtifactType]:
    """Classify every message in a conversation sequence.

    Args:
        messages: Ordered list of message dicts.  May be empty.

    Returns:
        List of ArtifactType values of the same length as *messages*, where
        each element is the classification of the corresponding message.
        Returns an empty list when *messages* is empty.

    Notes:
        Delegates to :func:`classify` for each message, passing the message's
        zero-based index and the total sequence length.  The result list is
        always the same length as the input list.
    """
    total = len(messages)
    return [classify(msg, i, total) for i, msg in enumerate(messages)]
