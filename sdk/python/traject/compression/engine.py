"""Compression engine for the Traject SDK trajectory compression pipeline.

Orchestrates the full 8-step compression pipeline: config validation,
adapter detection, message normalization, artifact classification, segment
parsing, turn-based protection, relevance scoring, strategy-driven compression
decisions, result validation, and optional shadow-mode passthrough.

The public entry point is :func:`compress`. All helper functions are private
and intended for use only within this module.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
import tiktoken

from traject.classifier.artifact_type import ArtifactType, classify_sequence
from traject.compression.adapters.base import FrameworkAdapter
from traject.compression.adapters.raw_openai import RawOpenAIAdapter
from traject.compression.relevance_scorer import score_segments
from traject.compression.segment_parser import parse
from traject.compression.strategies import (
    CompressionConfig,
    CompressionStrategy,
    validate_config,
)
from traject.exceptions import TrajectCompressionError, TrajectDependencyError
from traject.models import CompressionResult, Segment

logger = structlog.get_logger(__name__)


def _detect_adapter(messages: Any) -> FrameworkAdapter:  # noqa: ANN401
    """Return the first adapter that accepts *messages*, or raise TrajectCompressionError.

    Any is unavoidable here — this function accepts messages from any supported
    framework (OpenAI, LangChain, AutoGen) before the adapter is selected.
    """
    if RawOpenAIAdapter.accepts(messages):
        return RawOpenAIAdapter()

    # Guarded import for LangChain adapter (optional dependency)
    try:
        from traject.compression.adapters.langchain import LangChainAdapter

        if LangChainAdapter.accepts(messages):
            return LangChainAdapter()
    except TrajectDependencyError:
        pass

    # Guarded import for AutoGen adapter (optional dependency)
    try:
        from traject.compression.adapters.autogen import AutoGenAdapter

        if AutoGenAdapter.accepts(messages):
            return AutoGenAdapter()
    except TrajectDependencyError:
        pass

    raise TrajectCompressionError(
        f"No adapter found for messages of type {type(messages).__name__}. "
        "Supported formats: raw OpenAI list[dict], LangChain BaseMessage list, "
        "AutoGen message list. Install the appropriate optional dependency: "
        "pip install traject-sdk[langchain] or traject-sdk[autogen]."
    )


def _apply_strategy(
    segment: Segment,
    score: float,
    strategy: CompressionStrategy,
    max_turn: int,
) -> Literal["RETAIN", "SUMMARIZE", "DROP"]:
    """Return the compression decision for a single unprotected segment.

    Applies the decision table for the given strategy. Protected segments must
    not be passed to this function — they are always retained by the caller.

    Args:
        segment: The segment to evaluate. Must not be protected.
        score: Relevance score in ``[0.0, 1.0]`` from the relevance scorer.
        strategy: The active :class:`~traject.compression.strategies.CompressionStrategy`.
        max_turn: The highest ``turn_index`` across all segments in the batch,
            used to compute how many turns ago this segment occurred.

    Returns:
        ``"RETAIN"`` to keep the segment verbatim,
        ``"SUMMARIZE"`` to replace it with a short summary, or
        ``"DROP"`` to remove it entirely.
    """
    art = segment.artifact_type
    turns_ago = max_turn - segment.turn_index

    if strategy == CompressionStrategy.CONSERVATIVE:
        if art == ArtifactType.TOOL_RESULT and turns_ago > 3 and score < 0.30:
            return "SUMMARIZE"
        if art == ArtifactType.REASONING_BLOCK and score < 0.40:
            return "DROP"
        return "RETAIN"

    if strategy == CompressionStrategy.MODERATE:
        if art == ArtifactType.TOOL_RESULT and turns_ago > 2 and score < 0.40:
            return "SUMMARIZE"
        if art == ArtifactType.REASONING_BLOCK and score < 0.50:
            return "DROP"
        if art == ArtifactType.RAG_CHUNK and score < 0.35:
            return "DROP"
        return "RETAIN"

    # AGGRESSIVE
    if art == ArtifactType.TOOL_RESULT and turns_ago > 1 and score < 0.50:
        return "SUMMARIZE"
    if art == ArtifactType.REASONING_BLOCK and score < 0.60:
        return "DROP"
    if art == ArtifactType.RAG_CHUNK and score < 0.45:
        return "DROP"
    if art == ArtifactType.FEW_SHOT_EXAMPLE and score < 0.40:
        return "DROP"
    return "RETAIN"


def _validate_compression_result(
    original: list[dict[str, Any]],
    compressed: list[dict[str, Any]],
    artifact_types: list[ArtifactType],
    config: CompressionConfig,  # reserved for future last-turn validation
) -> None:
    """Validate the compressed message list for structural invariants.

    Raises:
        TrajectCompressionError: If any system prompt from *original* is absent
            from *compressed* (checked by content equality on ``["content"]``).
        TrajectCompressionError: If *compressed* is empty.
    """
    if len(compressed) < 1:
        raise TrajectCompressionError(
            "Compression produced an empty message list. "
            "At least one message must be retained."
        )

    # Collect system prompt contents from the original message list.
    system_contents: list[Any] = [
        msg.get("content")
        for msg, art in zip(original, artifact_types, strict=False)
        if art == ArtifactType.SYSTEM_PROMPT
    ]

    compressed_contents: set[Any] = {msg.get("content") for msg in compressed}

    for sys_content in system_contents:
        if sys_content not in compressed_contents:
            raise TrajectCompressionError(
                "Compression removed a system prompt. "
                "System prompts must always be preserved in the compressed output."
            )


def compress(
    messages: list[dict[str, Any]],
    config: CompressionConfig,
    task_hint: str | None = None,
    adapter: FrameworkAdapter | None = None,
) -> CompressionResult:
    """Run the full 8-step Traject compression pipeline on *messages*.

    The pipeline normalizes the input into canonical ``list[dict]`` form,
    classifies each message, parses segments with token counts, protects the
    most recent turns and all system prompts, scores segment relevance,
    applies the strategy's decision table, validates the result, and then
    optionally discards the compressed output in shadow mode.

    Args:
        messages: Input message list in any supported format (raw OpenAI
            ``list[dict]``, LangChain ``BaseMessage`` list, or AutoGen dicts).
            The original list is never mutated.
        config: Immutable compression configuration produced by
            :func:`~traject.compression.strategies.get_config` or constructed
            directly.  Validated at the start of the pipeline.
        task_hint: Optional natural-language description of the active task.
            When provided, the relevance scorer uses semantic similarity
            against this hint to weight segment scores.  When ``None``,
            the semantic component defaults to ``1.0`` for all segments.
        adapter: Optional pre-constructed
            :class:`~traject.compression.adapters.base.FrameworkAdapter`.
            When ``None``, the adapter is auto-detected from the *messages*
            type via :func:`_detect_adapter`.

    Returns:
        A :class:`~traject.models.CompressionResult` populated with token counts,
        segment statistics, and the final message list.  In shadow mode,
        ``messages`` in the result is the original unmodified input and
        ``tokens_saved`` is ``0``.  If result validation fails, the pipeline
        falls back to returning the original messages with a warning entry.

    Raises:
        TrajectCompressionError: Propagated from :func:`_detect_adapter` when
            no adapter accepts the *messages* type.
        TrajectConfigError: If *config* fails validation.
    """
    # ------------------------------------------------------------------ #
    # Step 1: VALIDATE CONFIG                                              #
    # ------------------------------------------------------------------ #
    validate_config(config)

    # ------------------------------------------------------------------ #
    # Step 1 (cont.): NORMALIZE                                           #
    # ------------------------------------------------------------------ #
    if adapter is None:
        adapter = _detect_adapter(messages)
    normalized: list[dict[str, Any]] = adapter.normalize(messages)

    # ------------------------------------------------------------------ #
    # Step 2: CLASSIFY                                                     #
    # ------------------------------------------------------------------ #
    artifact_types: list[ArtifactType] = classify_sequence(normalized)

    # ------------------------------------------------------------------ #
    # Step 3: PARSE — build Segment objects with token counts             #
    # ------------------------------------------------------------------ #
    segments: list[Segment] = parse(normalized, artifact_types)
    original_tokens: int = sum(s.token_count for s in segments)

    # ------------------------------------------------------------------ #
    # Step 4: PROTECT — mark the last N turns as protected                #
    # ------------------------------------------------------------------ #
    max_turn: int = max((s.turn_index for s in segments), default=0)
    protected_turn_threshold: int = max_turn - config.min_turns_protected + 1
    segments = [
        s.model_copy(update={"protected": True})
        if (s.turn_index >= protected_turn_threshold or s.protected)
        else s
        for s in segments
    ]

    # ------------------------------------------------------------------ #
    # Step 5: SCORE                                                        #
    # ------------------------------------------------------------------ #
    scores: list[float] = score_segments(segments, task_hint)

    # ------------------------------------------------------------------ #
    # Step 6: COMPRESS — apply per-segment strategy decisions             #
    # ------------------------------------------------------------------ #
    retained: list[Segment] = []
    summarized: list[Segment] = []
    dropped: list[Segment] = []
    compressed_messages: list[dict[str, Any]] = []

    enc = tiktoken.get_encoding("cl100k_base")

    for seg, score in zip(segments, scores, strict=False):
        if seg.protected:
            retained.append(seg)
            compressed_messages.append(normalized[seg.index])
            continue

        decision = _apply_strategy(seg, score, config.strategy, max_turn)

        if decision == "RETAIN":
            retained.append(seg)
            compressed_messages.append(normalized[seg.index])
        elif decision == "SUMMARIZE":
            summarized.append(seg)
            summary = seg.content[:100] + " [summarized by Axon]"
            compressed_messages.append({"role": seg.role, "content": summary})
        else:  # DROP
            dropped.append(seg)

    compressed_tokens: int = sum(
        len(
            enc.encode(
                m.get("content", "")
                if isinstance(m.get("content"), str)
                else ""
            )
        )
        for m in compressed_messages
    )
    tokens_saved_raw: int = original_tokens - compressed_tokens

    # ------------------------------------------------------------------ #
    # Step 7: VALIDATE                                                     #
    # ------------------------------------------------------------------ #
    try:
        _validate_compression_result(
            normalized, compressed_messages, artifact_types, config
        )
    except TrajectCompressionError as exc:
        logger.warning("traject.compression.validation_failed", error=str(exc))
        return CompressionResult(
            original_tokens=original_tokens,
            compressed_tokens=original_tokens,
            tokens_saved=0,
            compression_ratio=0.0,
            segments_analyzed=len(segments),
            segments_retained=len(segments),
            segments_summarized=0,
            segments_dropped=0,
            shadow_mode=config.shadow_mode,
            strategy_applied=config.strategy.value,
            messages=list(messages),
            warnings=[
                f"Compression validation failed: {exc}. "
                "Original messages returned."
            ],
        )

    # ------------------------------------------------------------------ #
    # Step 8: SHADOW MODE — return original messages when enabled         #
    # ------------------------------------------------------------------ #
    if config.shadow_mode:
        final_messages: Any = list(messages)
        final_tokens: int = original_tokens
        final_saved: int = 0
        ratio: float = 0.0
    else:
        final_messages = adapter.denormalize(compressed_messages, messages)
        final_tokens = compressed_tokens
        final_saved = tokens_saved_raw
        ratio = (
            1.0 - (final_tokens / original_tokens) if original_tokens > 0 else 0.0
        )

    return CompressionResult(
        original_tokens=original_tokens,
        compressed_tokens=final_tokens,
        tokens_saved=final_saved,
        compression_ratio=ratio,
        segments_analyzed=len(segments),
        segments_retained=len(retained),
        segments_summarized=len(summarized),
        segments_dropped=len(dropped),
        shadow_mode=config.shadow_mode,
        strategy_applied=config.strategy.value,
        messages=final_messages,
        warnings=[],
    )
