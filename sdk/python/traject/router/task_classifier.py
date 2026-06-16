"""Heuristic task-type classifier for the Traject adaptive model router.

Provides ``TaskType``, ``classify_task``, and ``estimate_complexity`` — three
public symbols that give the router a cheap (< 1 ms), dependency-free signal
about the nature of an LLM request and its expected processing demand. All
logic is pure keyword matching; there are no ML models and no network calls.
Every function in this module is guaranteed never to raise: any unexpected
exception is silently absorbed and a safe default is returned instead.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any


class TaskType(StrEnum):
    """Enumeration of recognised LLM task categories.

    Inherits from ``StrEnum`` so that enum members are directly usable
    wherever a plain string is expected (JSON serialisation, structlog
    fields, etc.) without an explicit ``.value`` dereference.

    Attributes:
        CODE_GENERATION: The request asks the model to write or generate code.
        CODE_REVIEW: The request asks the model to review, critique, or
            improve existing code that is supplied in the conversation.
        SUMMARIZATION: The request asks the model to condense or summarise
            a body of text.
        CLASSIFICATION: The request asks the model to assign a category or
            label to the input.
        EXTRACTION: The request asks the model to extract structured
            information from unstructured text.
        QUESTION_ANSWERING: The request poses a question that expects a
            direct factual or explanatory answer.
        REASONING: The request asks the model to reason through a problem,
            compare options, or explain a concept step by step.
        TRANSLATION: The request asks the model to translate text from one
            natural language to another.
        CREATIVE_WRITING: The request asks the model to produce creative or
            fictional text.
        UNKNOWN: No recognised signal was found; the router will apply
            conservative defaults.
    """

    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    SUMMARIZATION = "summarization"
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    QUESTION_ANSWERING = "question_answering"
    REASONING = "reasoning"
    TRANSLATION = "translation"
    CREATIVE_WRITING = "creative_writing"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TRIPLE_BACKTICK_RE: re.Pattern[str] = re.compile(r"```")


def _safe_content(msg: object) -> str:
    """Return the string content of a message dict, or an empty string.

    Args:
        msg: An arbitrary value that is expected to be a ``dict`` with a
            ``"content"`` key holding a ``str``. Handles ``None``, non-dict
            types, and non-string content values without raising.

    Returns:
        The message content as a plain string, or ``""`` when it cannot be
        retrieved.
    """
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if not isinstance(content, str):
        return ""
    return content


def _safe_role(msg: object) -> str:
    """Return the role field of a message dict, or an empty string.

    Args:
        msg: An arbitrary value expected to be a ``dict`` with a ``"role"``
            key holding a ``str``.

    Returns:
        The role as a plain string, or ``""`` when unavailable.
    """
    if not isinstance(msg, dict):
        return ""
    role = msg.get("role")
    if not isinstance(role, str):
        return ""
    return role


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_task(messages: list[dict[str, Any]]) -> TaskType:
    """Classify the task type of an LLM conversation using heuristic signals.

    Applies 11 priority-ordered detection rules (see design doc §2.1) to the
    concatenated message content and returns the first matching ``TaskType``.
    Case-insensitive matching is used throughout. The entire function body is
    wrapped in a broad ``except Exception`` guard so that malformed input —
    missing keys, ``None`` values, non-dict elements — can never cause a
    caller-visible exception.

    Args:
        messages: A list of message dicts, each expected to contain ``"role"``
            and ``"content"`` string fields following the OpenAI chat
            completions schema. The list may be empty, contain non-dict
            elements, or contain dicts with missing or ``None``-valued keys;
            all such cases are handled gracefully.

    Returns:
        The detected ``TaskType`` enum value. Returns ``TaskType.UNKNOWN``
        when no signal matches or when any unexpected error occurs.
    """
    try:
        return _classify_task_impl(messages)
    except Exception:  # pylint: disable=broad-except
        return TaskType.UNKNOWN


def _classify_task_impl(messages: list[dict[str, Any]]) -> TaskType:
    """Core classification logic, separated so the outer wrapper can catch exceptions.

    Args:
        messages: Raw messages list from the caller.

    Returns:
        Detected ``TaskType``.
    """
    if not isinstance(messages, list):
        return TaskType.UNKNOWN

    system_content = ""
    user_contents: list[str] = []
    last_user_content = ""

    for msg in messages:
        role = _safe_role(msg)
        content = _safe_content(msg)
        if role == "system":
            system_content = content.lower()
        elif role == "user":
            user_contents.append(content.lower())
            last_user_content = content.lower()

    full_text = (system_content + " " + " ".join(user_contents)).lower()

    # --- Signal 1: system prompt keywords → CODE_GENERATION ---
    code_gen_kws = ("code", "implement", "function", "class", "bug")
    if any(kw in system_content for kw in code_gen_kws):
        return TaskType.CODE_GENERATION

    # --- Signal 2: review keywords + code block → CODE_REVIEW ---
    review_kws = ("review", "analyze", "critique", "improve")
    has_review_kw = any(kw in system_content for kw in review_kws)
    all_content_raw = " ".join(_safe_content(msg) for msg in messages)
    has_code_block = bool(_TRIPLE_BACKTICK_RE.search(all_content_raw))
    if has_review_kw and has_code_block:
        return TaskType.CODE_REVIEW

    # --- Signal 3: any user message has a code block → CODE_GENERATION ---
    user_raw = " ".join(
        _safe_content(msg) for msg in messages if _safe_role(msg) == "user"
    )
    if _TRIPLE_BACKTICK_RE.search(user_raw):
        return TaskType.CODE_GENERATION

    # --- Signal 4: summarization keywords ---
    summarization_kws = ("summarize", "summary", "tldr", "key points", "brief")
    if any(kw in full_text for kw in summarization_kws):
        return TaskType.SUMMARIZATION

    # --- Signal 5: classification keywords ---
    classification_kws = (
        "classify",
        "categorize",
        "label",
        "which of",
        "one of the following",
    )
    if any(kw in full_text for kw in classification_kws):
        return TaskType.CLASSIFICATION

    # --- Signal 6: extraction keywords ---
    extraction_kws = ("extract", "find all", "list the", "identify", "what are the")
    if any(kw in full_text for kw in extraction_kws):
        return TaskType.EXTRACTION

    # --- Signal 7: translation keywords ---
    translation_kws = ("translate", "in french", "in spanish", "in german")
    if any(kw in full_text for kw in translation_kws):
        return TaskType.TRANSLATION

    # --- Signal 8: reasoning keywords ---
    reasoning_kws = (
        "think",
        "reason",
        "step by step",
        "explain why",
        "analyze",
        "compare",
    )
    if any(kw in full_text for kw in reasoning_kws):
        return TaskType.REASONING

    # --- Signal 9: creative writing keywords ---
    creative_kws = ("write a story", "poem", "creative", "imagine", "fictional")
    if any(kw in full_text for kw in creative_kws):
        return TaskType.CREATIVE_WRITING

    # --- Signal 10: last user message contains "?" → QUESTION_ANSWERING ---
    if "?" in last_user_content:
        return TaskType.QUESTION_ANSWERING

    # --- Signal 11: fallback ---
    return TaskType.UNKNOWN


def estimate_complexity(messages: list[dict[str, Any]], task_type: TaskType) -> float:
    """Estimate the computational complexity of an LLM request as a score in [0.0, 1.0].

    The score is a weighted combination of four signals: total token volume,
    tool-call depth, inherent complexity of the task type, and presence of
    code blocks. The function is guaranteed to return a ``float`` in the
    closed interval ``[0.0, 1.0]`` and will never raise regardless of input.

    Score composition:

    - Token volume  (weight 0.50): ``min(1.0, estimated_tokens / 8000)``
    - Tool calls    (weight 0.20): ``min(1.0, tool_call_count / 10)``
    - Task type     (weight 0.20): +0.20 for REASONING, CODE_GENERATION,
      CODE_REVIEW; +0.00 otherwise
    - Code blocks   (weight 0.10): ``min(0.10, code_block_count * 0.02)``

    Args:
        messages: A list of message dicts following the OpenAI chat
            completions schema. Handles empty lists, non-dict elements,
            and missing or ``None``-valued keys without raising.
        task_type: The ``TaskType`` returned by ``classify_task`` for the
            same message list. Used to apply the task-type complexity bonus.

    Returns:
        A ``float`` in ``[0.0, 1.0]``. Returns ``0.0`` when any unexpected
        error occurs inside the function.
    """
    try:
        return _estimate_complexity_impl(messages, task_type)
    except Exception:  # pylint: disable=broad-except
        return 0.0


def _estimate_complexity_impl(
    messages: list[dict[str, Any]], task_type: TaskType
) -> float:
    """Core complexity estimation logic.

    Args:
        messages: Raw messages list from the caller.
        task_type: Pre-computed task type for the conversation.

    Returns:
        Complexity score in ``[0.0, 1.0]``.
    """
    score = 0.0
    safe_messages: list[dict[str, Any]] = messages if isinstance(messages, list) else []

    # --- Token volume score (50% weight) ---
    total_chars = sum(len(_safe_content(msg)) for msg in safe_messages)
    token_estimate = total_chars / 4.0  # rough tiktoken approximation
    token_score = min(1.0, token_estimate / 8000.0)
    score += token_score * 0.5

    # --- Tool call score (20% weight) ---
    tool_call_count = sum(
        1
        for msg in safe_messages
        if _safe_role(msg) == "tool" or "tool_call" in _safe_content(msg)
    )
    tool_score = min(1.0, tool_call_count / 10.0)
    score += tool_score * 0.2

    # --- Task type bonus (20% weight) ---
    high_complexity_types = (
        TaskType.REASONING,
        TaskType.CODE_GENERATION,
        TaskType.CODE_REVIEW,
    )
    if task_type in high_complexity_types:
        score += 0.2

    # --- Code block score (up to 10% weight) ---
    all_content = " ".join(_safe_content(msg) for msg in safe_messages)
    code_blocks = len(_TRIPLE_BACKTICK_RE.findall(all_content))
    score += min(0.1, code_blocks * 0.02)

    return min(1.0, max(0.0, score))
