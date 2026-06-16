"""Segment parser for the Traject compression pipeline.

Converts a flat list of message dicts (already classified by
:func:`traject.classifier.artifact_type.classify_sequence`) into a list of
:class:`~traject.models.Segment` objects enriched with token counts, turn
indices, and protection flags.  Token counting uses ``tiktoken``'s
``cl100k_base`` encoding, which is cached internally by ``tiktoken`` and
therefore safe to call repeatedly without performance penalties.
"""

from __future__ import annotations

from typing import Any

import tiktoken

from traject.classifier.artifact_type import ArtifactType
from traject.exceptions import TrajectCompressionError
from traject.models import Segment


def parse(
    messages: list[dict[str, Any]],
    artifact_types: list[ArtifactType],
) -> list[Segment]:
    """Parse a message list into enriched Segment objects.

    Iterates over each message alongside its pre-computed artifact type,
    computes a tiktoken token count, tracks conversational turn index, and
    applies protection flags.

    Args:
        messages: Ordered list of message dicts.  Each dict should contain
            at minimum a ``"role"`` key and a ``"content"`` key.  Missing
            keys are handled gracefully without raising.
        artifact_types: Ordered list of
            :class:`~traject.classifier.artifact_type.ArtifactType`
            values, one per message.  Must be produced by calling
            :func:`~traject.classifier.artifact_type.classify_sequence` on the
            *same* ``messages`` list to guarantee index alignment.

    Returns:
        List of :class:`~traject.models.Segment` objects of the same length as
        ``messages``, in the same order.  Returns an empty list when
        ``messages`` is empty.

    Raises:
        TrajectCompressionError: If ``len(messages) != len(artifact_types)``.
            This typically indicates that ``classify_sequence`` was called on
            a different messages array.  Ensure both lists share the same
            origin before calling ``parse``.
    """
    if len(messages) != len(artifact_types):
        raise TrajectCompressionError(
            f"messages length {len(messages)} != artifact_types length "
            f"{len(artifact_types)}. Ensure classify_sequence was called on "
            f"the same messages array."
        )

    enc = tiktoken.get_encoding("cl100k_base")  # tiktoken caches internally
    segments: list[Segment] = []
    turn_index = 0
    last_role: str | None = None

    for i, (msg, art_type) in enumerate(zip(messages, artifact_types, strict=False)):
        role: str = msg.get("role") or ""
        content = msg.get("content", "")

        # Increment turn when transitioning from assistant to user
        if last_role == "assistant" and role == "user":
            turn_index += 1
        last_role = role

        # Token count: str content encoded directly; list content sums text parts
        if isinstance(content, str):
            token_count = len(enc.encode(content))
        elif isinstance(content, list):
            token_count = sum(
                len(enc.encode(part.get("text", "")))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            token_count = 0

        # System prompts are always protected; also honor axon_preserve metadata
        protected = (
            art_type == ArtifactType.SYSTEM_PROMPT
            or msg.get("axon_preserve") is True
        )

        content_str = content if isinstance(content, str) else str(content)

        segments.append(
            Segment(
                index=i,
                role=role,
                content=content_str,
                artifact_type=art_type,
                token_count=token_count,
                turn_index=turn_index,
                protected=protected,
            )
        )

    return segments
