"""Compression engine for the Traject SDK trajectory compression pipeline.

Orchestrates the full 8-step compression pipeline: config validation,
adapter detection, message normalization, artifact classification, segment
parsing, turn-based protection, relevance scoring, strategy-driven compression
decisions, result validation, and optional shadow-mode passthrough.

Improvements in this version:
- Adaptive target-driven candidate selection (replaces per-segment fixed threshold).
- Structured tool result summarization (extracts file paths, errors, code blocks).
- Dynamic turn protection via substring matching against the active task.
- Task-aware scoring weight auto-detection is delegated to the relevance scorer.

The public entry point is :func:`compress`. All helper functions are private
and intended for use only within this module.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import structlog

from traject.classifier.artifact_type import ArtifactType, classify_sequence
from traject.compression import (
    json_columnarizer,
    prose_filter,
    tool_result_classifier,
)
from traject.compression.adapters.base import FrameworkAdapter
from traject.compression.adapters.raw_openai import RawOpenAIAdapter
from traject.compression.ccr import CCRStore
from traject.compression.relevance_scorer import (
    CompressionCache,
    compute_semantic_reference_scores,
    score_segments,
)
from traject.compression.segment_parser import _encoding_for_model, parse
from traject.compression.strategies import (
    CompressionConfig,
    CompressionStrategy,
    validate_config,
)
from traject.exceptions import TrajectCompressionError, TrajectDependencyError
from traject.models import CompressionResult, Segment

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# High-information content detector
# ---------------------------------------------------------------------------

_HIGH_INFO_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'File "[^"]+\.py", line \d+'),
    re.compile(r"\.py:\d+"),
    re.compile(r"(?:Error|Exception|Traceback)[:\s]"),
    re.compile(r"exit code[:\s]+\d+", re.I),
    re.compile(r"FAILED|PASSED|ERROR", re.M),
    re.compile(r"assert\w*.*(?:Error|Fail)", re.I),
    re.compile(r"\b(?:raise|raised)\s+\w+Error"),
    re.compile(r"https?://\S+"),
    re.compile(r"\b[0-9a-f]{7,40}\b"),
    re.compile(r"(?:commit|sha|hash)[\s:]+[0-9a-f]{7}", re.I),
]

_CODE_EXTENSIONS: frozenset[str] = frozenset(
    [".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".sh"]
)


def _has_high_information_content(content: str) -> bool:
    """Return True if *content* contains unique load-bearing information.

    Detects stack traces, error messages, file:line references, test results,
    git hashes, and URLs that cannot be reconstructed from context if dropped.

    Args:
        content: The segment's text content.

    Returns:
        ``True`` when the content matches any high-information pattern.
    """
    for pattern in _HIGH_INFO_PATTERNS:
        if pattern.search(content):
            return True
    return False


# ---------------------------------------------------------------------------
# Message preprocessing — prose filter + JSON columnarizer
# ---------------------------------------------------------------------------


def _sum_message_tokens(messages: list[dict[str, Any]], enc: Any) -> int:  # noqa: ANN401
    """Sum tiktoken token counts over a message list.

    Mirrors the per-message counting logic in the segment parser: string
    content is encoded directly, list content sums its text parts, and any
    other content type contributes zero.

    Args:
        messages: Message dicts to count.
        enc: A tiktoken encoding (from ``_encoding_for_model``).

    Returns:
        Total token count across all messages.
    """
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += len(enc.encode(content))
        elif isinstance(content, list):
            total += sum(
                len(enc.encode(part.get("text", "")))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
    return total


def _preprocess_messages(
    messages: list[dict[str, Any]],
    artifact_types: list[ArtifactType],
) -> list[dict[str, Any]]:
    """Apply content-aware preprocessing to messages before token counting.

    - ASSISTANT_MESSAGE segments: prose filler is stripped.
    - TOOL_RESULT segments: JSON arrays are columnarized when doing so is
      strictly shorter.

    Args:
        messages: Normalized message list.
        artifact_types: Parallel artifact classifications (same length).

    Returns:
        A new list with preprocessed content for eligible segments.
        Original messages are never mutated.
    """
    result: list[dict[str, Any]] = []
    for msg, art in zip(messages, artifact_types, strict=False):
        content = msg.get("content", "")
        if isinstance(content, str):
            if art == ArtifactType.ASSISTANT_MESSAGE:
                filtered = prose_filter.strip_filler(content)
                if filtered != content:
                    msg = {**msg, "content": filtered}
            elif art == ArtifactType.TOOL_RESULT:
                columnarized = json_columnarizer.columnarize(content)
                if columnarized != content:
                    msg = {**msg, "content": columnarized}
        result.append(msg)
    return result


# ---------------------------------------------------------------------------
# Adaptive compression candidate selection
# ---------------------------------------------------------------------------


def _select_compression_candidates(
    segments: list[Segment],
    scores: list[float],
    strategy: CompressionStrategy,
    max_turn: int,
    target_reduction_pct: float,
    original_tokens: int,
    score_ceiling: float,
) -> dict[int, Literal["RETAIN", "SUMMARIZE", "DROP"]]:
    """Select compression candidates greedily to meet the token reduction target.

    Replaces the per-segment fixed-threshold decision table for non-soft-protected
    segments. Candidates are sorted by score ascending (lowest = most compressible)
    and greedily selected until cumulative token savings reach the target.

    Args:
        segments: All segments in the compression batch.
        scores: Parallel list of relevance scores in ``[0.0, 1.0]``.
        strategy: Active compression strategy (controls artifact eligibility).
        max_turn: Highest turn index in the batch.
        target_reduction_pct: Desired fraction of total tokens to eliminate.
        original_tokens: Total token count before compression.
        score_ceiling: Hard upper bound — segments with score > score_ceiling
            are never selected regardless of target.

    Returns:
        Mapping from ``segment.index`` to ``"RETAIN"``, ``"SUMMARIZE"``, or ``"DROP"``.
    """
    target_tokens: int = int(original_tokens * target_reduction_pct)
    decisions: dict[int, Literal["RETAIN", "SUMMARIZE", "DROP"]] = {}

    candidates: list[tuple[float, int, Segment]] = []
    for seg, score in zip(segments, scores, strict=False):
        if seg.protected or seg.soft_protected:
            continue
        if score > score_ceiling:
            continue
        art = seg.artifact_type
        turns_ago = max_turn - seg.turn_index
        eligible = False
        if (
            (art == ArtifactType.TOOL_RESULT and turns_ago > 3)
            or art == ArtifactType.REASONING_BLOCK
            or (
                art == ArtifactType.RAG_CHUNK
                and strategy
                in (
                    CompressionStrategy.MODERATE,
                    CompressionStrategy.AGGRESSIVE,
                )
            )
            or (
                art == ArtifactType.FEW_SHOT_EXAMPLE
                and strategy == CompressionStrategy.AGGRESSIVE
            )
        ):
            eligible = True
        if eligible:
            candidates.append((score, seg.index, seg))

    candidates.sort(key=lambda t: t[0])

    tokens_saved_so_far = 0
    selected: set[int] = set()
    for _score, seg_index, seg in candidates:
        if tokens_saved_so_far >= target_tokens:
            break
        selected.add(seg_index)
        tokens_saved_so_far += seg.token_count

    for _score, seg_index, seg in candidates:
        if seg_index in selected:
            if seg.artifact_type == ArtifactType.TOOL_RESULT:
                decisions[seg_index] = "SUMMARIZE"
            else:
                decisions[seg_index] = "DROP"
        else:
            decisions[seg_index] = "RETAIN"

    return decisions


# ---------------------------------------------------------------------------
# Dynamic substring protection
# ---------------------------------------------------------------------------


def _compute_substring_protection(
    segments: list[Segment],
    current_task: str,
    min_token_len: int = 6,
) -> set[int]:
    """Return indices of non-protected segments that share unique tokens with *current_task*.

    Extracts words of at least *min_token_len* characters from *current_task*
    that look like technical identifiers (contain a digit, underscore, dot, or
    slash) and hard-protects segments whose content contains at least one such
    token. Tokens that appear in more than half of the non-protected segments are
    excluded — they are too common to be meaningful protection signals.

    Args:
        segments: Ordered list of segments from the parser.
        current_task: The active task description (explicit task_hint only).
        min_token_len: Minimum word length to use as a protection token.

    Returns:
        Set of ``segment.index`` values that should be hard-protected.
    """
    candidate_tokens: set[str] = {
        word
        for word in current_task.split()
        if len(word) >= min_token_len and any(c in word for c in "0123456789_./\\")
    }
    if not candidate_tokens:
        return set()

    non_protected = [s for s in segments if not s.protected]
    if not non_protected:
        return set()

    # Filter out tokens that appear in more than half the non-protected segments —
    # these are workspace-wide constants, not specific task references.
    half = len(non_protected) / 2.0
    task_tokens: set[str] = set()
    for token in candidate_tokens:
        count = sum(1 for s in non_protected if token in s.content)
        if count <= half:
            task_tokens.add(token)

    if not task_tokens:
        return set()

    protected_indices: set[int] = set()
    for seg in non_protected:
        for token in task_tokens:
            if token in seg.content:
                protected_indices.add(seg.index)
                break

    return protected_indices


# ---------------------------------------------------------------------------
# Lossless redundant tool-result deduplication
# ---------------------------------------------------------------------------

_DEDUP_STUB: str = (
    "[Traject: identical tool output appears again later in the context; "
    "this earlier copy was removed to save tokens.]"
)


def _compute_dedup(
    segments: list[Segment],
    normalized: list[dict[str, Any]],
) -> tuple[set[int], set[int]]:
    """Identify exact-duplicate tool results that can be removed losslessly.

    In agent loops the model frequently re-reads the same file or re-runs the
    same command, producing byte-identical TOOL_RESULT segments. Every copy but
    the last carries no unique information — the last occurrence is kept verbatim
    and earlier copies are replaced with a short reference. This is lossless: any
    fact in an earlier copy still appears verbatim in the retained later copy.

    Segments explicitly marked ``traject_preserve`` are never deduplicated.

    Args:
        segments: Parsed segments.
        normalized: The normalized messages (parallel to ``segments`` by index),
            used to honor the ``traject_preserve`` opt-out.

    Returns:
        ``(stub_indices, keep_verbatim_indices)`` — earlier duplicate segment
        indices to replace with a stub, and the last-occurrence indices that
        must be retained verbatim to guarantee losslessness.
    """
    last_occurrence: dict[str, int] = {}
    for seg in segments:
        if seg.artifact_type == ArtifactType.TOOL_RESULT and seg.content.strip():
            last_occurrence[seg.content] = seg.index

    stub_indices: set[int] = set()
    keep_verbatim: set[int] = set()
    for seg in segments:
        if seg.artifact_type != ArtifactType.TOOL_RESULT or not seg.content.strip():
            continue
        if normalized[seg.index].get("traject_preserve") is True:
            continue
        final_idx = last_occurrence[seg.content]
        if final_idx != seg.index:
            stub_indices.add(seg.index)
            keep_verbatim.add(final_idx)
    return stub_indices, keep_verbatim


def _detect_adapter(messages: Any) -> FrameworkAdapter:  # noqa: ANN401
    """Return the first adapter that accepts *messages*, or raise TrajectCompressionError.

    ``Any`` is unavoidable here — this function accepts messages from any supported
    framework before the adapter is selected.
    """
    if RawOpenAIAdapter.accepts(messages):
        return RawOpenAIAdapter()

    try:
        from traject.compression.adapters.langchain import LangChainAdapter

        if LangChainAdapter.accepts(messages):
            return LangChainAdapter()
    except TrajectDependencyError:
        pass

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
    """Return the compression decision for a single soft-protected or fallback segment.

    Retained for soft-protected segments (0.15 threshold) and as a fallback for
    non-candidate segments. Non-soft-protected segments use
    :func:`_select_compression_candidates` instead.

    Args:
        segment: The segment to evaluate. Must not be hard-protected.
        score: Relevance score in ``[0.0, 1.0]``.
        strategy: Active compression strategy.
        max_turn: Highest turn index in the batch.

    Returns:
        ``"RETAIN"``, ``"SUMMARIZE"``, or ``"DROP"``.
    """
    art = segment.artifact_type
    turns_ago = max_turn - segment.turn_index

    if segment.soft_protected:
        if art == ArtifactType.TOOL_RESULT and turns_ago > 3 and score < 0.15:
            return "SUMMARIZE"
        if art == ArtifactType.REASONING_BLOCK and score < 0.15:
            return "DROP"
        return "RETAIN"

    if strategy == CompressionStrategy.CONSERVATIVE:
        if art == ArtifactType.TOOL_RESULT and turns_ago > 3 and score < 0.40:
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
        TrajectCompressionError: If any system prompt is absent from compressed.
        TrajectCompressionError: If compressed is empty.
    """
    if len(compressed) < 1:
        raise TrajectCompressionError(
            "Compression produced an empty message list. "
            "At least one message must be retained."
        )

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
    model: str | None = None,
    ccr_store: CCRStore | None = None,
) -> CompressionResult:
    """Run the full 8-step Traject compression pipeline on *messages*.

    Args:
        messages: Input message list in any supported format.
        config: Immutable compression configuration.
        task_hint: Optional natural-language description of the active task.
        adapter: Optional pre-constructed framework adapter.
        model: Optional model identifier used to pick the tiktoken encoding
            for token counting (e.g. ``"gpt-4o"`` -> ``o200k_base``).
            Defaults to ``None``, which preserves the legacy ``cl100k_base``
            behaviour exactly. For Anthropic (``claude-*``) and Gemini models
            the resulting token counts are APPROXIMATE — tiktoken does not
            implement those providers' tokenizers, so the counts must not be
            presented as exact.
        ccr_store: Optional :class:`~traject.compression.ccr.CCRStore` for
            reversible compression.  When provided, segments that would
            otherwise be dropped are stored in Redis and replaced with a
            short ``<<ccr:HASH>>`` stub.  The agent can recover the original
            content via the ``traject_retrieve`` MCP tool.

    Returns:
        A :class:`~traject.models.CompressionResult` with token counts,
        segment statistics, and the final message list.

    Raises:
        TrajectCompressionError: When no adapter accepts the messages type.
        TrajectConfigError: If config fails validation.
    """
    # Step 1: VALIDATE CONFIG
    validate_config(config)

    # Step 1 (cont.): NORMALIZE
    if adapter is None:
        adapter = _detect_adapter(messages)
    normalized: list[dict[str, Any]] = adapter.normalize(messages)

    # Step 2: CLASSIFY
    artifact_types: list[ArtifactType] = classify_sequence(normalized)

    # Encoding is needed both for the raw baseline and for compressed counting.
    enc = _encoding_for_model(model)

    # The reported baseline is the RAW token count of what the caller sent,
    # measured BEFORE preprocessing. This ensures the lossless preprocessing
    # savings (prose filter, JSON columnarization) are reflected in the
    # reported compression_ratio and tokens_saved rather than silently
    # shrinking the baseline.
    original_tokens: int = _sum_message_tokens(normalized, enc)

    # Step 2a: PREPROCESS — prose filter (ASSISTANT) + JSON columnarizer (TOOL_RESULT)
    preprocessed: list[dict[str, Any]] = _preprocess_messages(
        normalized, artifact_types
    )

    # Step 3: PARSE (token counts reflect preprocessed content)
    segments: list[Segment] = parse(preprocessed, artifact_types, model=model)
    # Post-preprocessing total drives the greedy candidate-selection target so
    # the target math operates on the segments the engine can still act on.
    parse_total_tokens: int = sum(s.token_count for s in segments)

    # Step 4: PROTECT — last N turns
    max_turn: int = max((s.turn_index for s in segments), default=0)
    protected_turn_threshold: int = max_turn - config.min_turns_protected + 1
    segments = [
        s.model_copy(update={"protected": True})
        if (s.turn_index >= protected_turn_threshold or s.protected)
        else s
        for s in segments
    ]

    # Step 4a: DYNAMIC SUBSTRING PROTECTION
    # Only apply when an explicit task_hint is provided.
    # Falling back to the last message content causes over-protection
    # because terminal messages often contain generic continuation language.
    if task_hint:
        substring_protected_indices = _compute_substring_protection(segments, task_hint)
        if substring_protected_indices:
            segments = [
                s.model_copy(update={"protected": True})
                if s.index in substring_protected_indices
                else s
                for s in segments
            ]

    # Step 4b: SOFT-PROTECT — semantic reference + content-aware pass
    ref_scores: list[float] = compute_semantic_reference_scores(segments, window=5)
    _SOFT_PROTECT_THRESHOLD: float = 0.75
    segments = [
        s.model_copy(update={"soft_protected": True})
        if (
            not s.protected
            and (
                ref_score >= _SOFT_PROTECT_THRESHOLD
                or _has_high_information_content(s.content)
            )
        )
        else s
        for s, ref_score in zip(segments, ref_scores, strict=False)
    ]
    segments_soft_protected_count: int = sum(1 for s in segments if s.soft_protected)

    # Step 5: SCORE
    cache = CompressionCache()
    scores: list[float] = score_segments(segments, task_hint, cache=cache)

    # Step 6: COMPRESS — adaptive candidate selection + soft-protect path
    candidate_decisions = _select_compression_candidates(
        segments=segments,
        scores=scores,
        strategy=config.strategy,
        max_turn=max_turn,
        target_reduction_pct=config.target_reduction_pct,
        original_tokens=parse_total_tokens,
        score_ceiling=config.score_ceiling,
    )

    retained: list[Segment] = []
    summarized: list[Segment] = []
    dropped: list[Segment] = []
    compressed_messages: list[dict[str, Any]] = []
    ccr_stubbed_count: int = 0

    # Lossless dedup runs first: it applies even to otherwise-protected duplicate
    # tool results because the information is preserved in the retained later copy.
    dedup_stub_indices, dedup_keep_verbatim = _compute_dedup(segments, preprocessed)

    for seg, score in zip(segments, scores, strict=False):
        # Earlier exact-duplicate tool output → replace with a short reference.
        if seg.index in dedup_stub_indices:
            summarized.append(seg)
            compressed_messages.append({"role": seg.role, "content": _DEDUP_STUB})
            continue

        # The final occurrence of a deduplicated output must be kept verbatim so
        # no information is lost.
        if seg.protected or seg.index in dedup_keep_verbatim:
            retained.append(seg)
            compressed_messages.append(preprocessed[seg.index])
            continue

        if seg.soft_protected:
            decision = _apply_strategy(seg, score, config.strategy, max_turn)
        else:
            raw_decision = candidate_decisions.get(seg.index, "RETAIN")
            decision = raw_decision

        if decision == "RETAIN":
            retained.append(seg)
            compressed_messages.append(preprocessed[seg.index])
        elif decision == "SUMMARIZE":
            # Command-aware domain compressor replaces the old generic summarizer.
            summary = tool_result_classifier.summarize(seg.content)
            # Inflation guard: never substitute a replacement that is not
            # strictly smaller than the original (short content can summarize
            # to something larger once the marker suffix is appended).
            if len(enc.encode(summary)) < seg.token_count:
                summarized.append(seg)
                compressed_messages.append({"role": seg.role, "content": summary})
            else:
                retained.append(seg)
                compressed_messages.append(preprocessed[seg.index])
        else:  # DROP
            if ccr_store is not None and seg.content.strip():
                # CCR: store full content in Redis, inject a retrieval stub.
                stub = ccr_store.store(seg.content)
                summarized.append(seg)
                compressed_messages.append({"role": seg.role, "content": stub})
                ccr_stubbed_count += 1
            else:
                dropped.append(seg)

    compressed_tokens: int = sum(
        len(
            enc.encode(
                m.get("content", "") if isinstance(m.get("content"), str) else ""
            )
        )
        for m in compressed_messages
    )
    # Clamp: summarization may produce output longer than input for short content.
    # The canonical token-saved value is always non-negative.
    tokens_saved_raw: int = max(0, original_tokens - compressed_tokens)
    # Adjust compressed_tokens upward if it exceeds original (summarizer inflation).
    if compressed_tokens > original_tokens:
        compressed_tokens = original_tokens

    # Step 7: VALIDATE
    try:
        _validate_compression_result(
            preprocessed, compressed_messages, artifact_types, config
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
                f"Compression validation failed: {exc}. Original messages returned."
            ],
            cache_hits=cache.hits,
            cache_hit_rate=cache.hit_rate,
            segments_soft_protected=segments_soft_protected_count,
            segments_ccr_stubbed=0,
        )

    # Step 8: SHADOW MODE
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
            max(0.0, 1.0 - (final_tokens / original_tokens))
            if original_tokens > 0
            else 0.0
        )

    logger.info(
        "traject.compression.complete",
        original_tokens=original_tokens,
        compressed_tokens=final_tokens,
        tokens_saved=final_saved,
        compression_ratio=round(ratio, 4),
        strategy=config.strategy.value,
        shadow_mode=config.shadow_mode,
        cache_hits=cache.hits,
        cache_hit_rate=round(cache.hit_rate, 4),
        segments_soft_protected=segments_soft_protected_count,
        segments_ccr_stubbed=ccr_stubbed_count,
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
        cache_hits=cache.hits,
        cache_hit_rate=cache.hit_rate,
        segments_soft_protected=segments_soft_protected_count,
        segments_ccr_stubbed=ccr_stubbed_count,
    )
