"""Unit tests for axon.router.task_classifier.

Validates: Requirements 1.1–1.14 (task classification and complexity estimation).

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10,
1.11, 1.12, 1.13, 1.14**
"""
from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from traject.router.task_classifier import TaskType, classify_task, estimate_complexity

# ---------------------------------------------------------------------------
# classify_task — parametrized representative prompts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        # CODE_GENERATION: system prompt keyword "implement"
        (
            [
                {"role": "system", "content": "implement the following function"},
                {"role": "user", "content": "add two numbers"},
            ],
            TaskType.CODE_GENERATION,
        ),
        # CODE_GENERATION: system prompt keyword "function"
        (
            [
                {"role": "system", "content": "write a function in Python"},
                {"role": "user", "content": "reverse a string"},
            ],
            TaskType.CODE_GENERATION,
        ),
        # CODE_GENERATION: user message has code block (no review keyword in system)
        (
            [
                {"role": "user", "content": "fix this: ```python\nprint('hello')\n```"},
            ],
            TaskType.CODE_GENERATION,
        ),
        # CODE_REVIEW: review keyword in system + code block in message
        # Note: system prompt "review the code" must NOT contain "code", "implement",
        # "function", "class", or "bug" to avoid Signal 1 (CODE_GENERATION) firing first.
        (
            [
                {"role": "system", "content": "please review the submission below"},
                {"role": "user", "content": "```python\nx = 1 + 1\n```"},
            ],
            TaskType.CODE_REVIEW,
        ),
        # SUMMARIZATION: keyword "summarize"
        (
            [{"role": "user", "content": "please summarize this document for me"}],
            TaskType.SUMMARIZATION,
        ),
        # SUMMARIZATION: keyword "tldr"
        (
            [{"role": "user", "content": "give me a tldr of this article"}],
            TaskType.SUMMARIZATION,
        ),
        # CLASSIFICATION: keyword "classify"
        (
            [{"role": "user", "content": "classify this email as spam or not spam"}],
            TaskType.CLASSIFICATION,
        ),
        # CLASSIFICATION: keyword "one of the following"
        (
            [{"role": "user", "content": "choose one of the following categories"}],
            TaskType.CLASSIFICATION,
        ),
        # EXTRACTION: keyword "extract"
        (
            [{"role": "user", "content": "extract all names from this text"}],
            TaskType.EXTRACTION,
        ),
        # EXTRACTION: keyword "what are the"
        (
            [{"role": "user", "content": "what are the main topics in this article?"}],
            TaskType.EXTRACTION,
        ),
        # TRANSLATION: keyword "translate"
        (
            [{"role": "user", "content": "translate this paragraph to Spanish"}],
            TaskType.TRANSLATION,
        ),
        # TRANSLATION: keyword "in french"
        (
            [{"role": "user", "content": "write a greeting in french"}],
            TaskType.TRANSLATION,
        ),
        # REASONING: keyword "step by step"
        (
            [{"role": "user", "content": "explain step by step how HTTPS works"}],
            TaskType.REASONING,
        ),
        # REASONING: keyword "compare"
        (
            [{"role": "user", "content": "compare Python and JavaScript for web dev"}],
            TaskType.REASONING,
        ),
        # CREATIVE_WRITING: keyword "write a story"
        (
            [{"role": "user", "content": "write a story about a brave knight"}],
            TaskType.CREATIVE_WRITING,
        ),
        # CREATIVE_WRITING: keyword "fictional"
        (
            [{"role": "user", "content": "create a fictional world for a novel"}],
            TaskType.CREATIVE_WRITING,
        ),
        # QUESTION_ANSWERING: last user message ends with "?"
        (
            [{"role": "user", "content": "What is the capital of France?"}],
            TaskType.QUESTION_ANSWERING,
        ),
        # UNKNOWN: no signal matches
        (
            [{"role": "user", "content": "do the thing"}],
            TaskType.UNKNOWN,
        ),
        # UNKNOWN: empty messages
        (
            [],
            TaskType.UNKNOWN,
        ),
    ],
)
def test_classify_task_representative_prompts(
    messages: list[dict[str, Any]], expected: TaskType
) -> None:
    """classify_task returns the expected TaskType for representative inputs."""
    result = classify_task(messages)
    assert result == expected, (
        f"Expected {expected!r} for messages={messages!r}, got {result!r}"
    )


# ---------------------------------------------------------------------------
# Edge cases: never raises
# ---------------------------------------------------------------------------


def test_classify_task_empty_list_returns_unknown() -> None:
    """classify_task([]) returns UNKNOWN and never raises."""
    result = classify_task([])
    assert result == TaskType.UNKNOWN


def test_classify_task_none_content_field_never_raises() -> None:
    """classify_task with None content values returns UNKNOWN without raising."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": None}]
    result = classify_task(messages)
    assert isinstance(result, TaskType)


def test_classify_task_missing_role_key_never_raises() -> None:
    """classify_task with missing 'role' key never raises."""
    messages: list[dict[str, Any]] = [{"content": "hello world"}]
    result = classify_task(messages)
    assert isinstance(result, TaskType)


def test_classify_task_non_dict_elements_never_raises() -> None:
    """classify_task with non-dict list elements never raises."""
    messages: list[Any] = ["not a dict", 42, None, True]  # type: ignore[list-item]
    result = classify_task(messages)  # type: ignore[arg-type]
    assert result == TaskType.UNKNOWN


def test_classify_task_malformed_dicts_never_raises() -> None:
    """classify_task with malformed dicts (extra/wrong types) never raises."""
    messages: list[dict[str, Any]] = [
        {"role": 123, "content": ["list", "not", "str"]},
        {"role": "user"},  # missing content
        {},  # completely empty
    ]
    result = classify_task(messages)
    assert isinstance(result, TaskType)


def test_classify_task_non_list_input_never_raises() -> None:
    """classify_task with non-list input never raises."""
    result = classify_task(None)  # type: ignore[arg-type]
    assert result == TaskType.UNKNOWN


# ---------------------------------------------------------------------------
# PBT: estimate_complexity always returns float in [0.0, 1.0]
#
# **Validates: Requirements 1.14**
# ---------------------------------------------------------------------------

_message_strategy = st.fixed_dictionaries(
    {
        "role": st.sampled_from(["system", "user", "assistant", "tool"]),
        "content": st.one_of(
            st.text(max_size=200),
            st.none(),
            st.integers(),
        ),
    }
)

_messages_strategy = st.lists(_message_strategy, max_size=15)

_task_type_strategy = st.sampled_from(list(TaskType))


@given(messages=_messages_strategy, task_type=_task_type_strategy)
@settings(max_examples=200)
def test_estimate_complexity_always_returns_float_in_unit_interval(
    messages: list[dict[str, Any]],
    task_type: TaskType,
) -> None:
    """estimate_complexity always returns a float in [0.0, 1.0], never raises.

    **Validates: Requirements 1.14**
    """
    result = estimate_complexity(messages, task_type)
    assert isinstance(result, float), f"Expected float, got {type(result)!r}"
    assert 0.0 <= result <= 1.0, (
        f"Complexity score {result!r} is outside [0.0, 1.0] "
        f"for messages={messages!r}, task_type={task_type!r}"
    )


@given(messages=_messages_strategy, task_type=_task_type_strategy)
@settings(max_examples=100)
def test_estimate_complexity_never_raises(
    messages: list[dict[str, Any]],
    task_type: TaskType,
) -> None:
    """estimate_complexity never raises regardless of input shape.

    **Validates: Requirements 1.14**
    """
    # Simply calling must not raise
    estimate_complexity(messages, task_type)


# ---------------------------------------------------------------------------
# Specific complexity boundary checks
# ---------------------------------------------------------------------------


def test_estimate_complexity_empty_messages_returns_zero_for_simple_task() -> None:
    """Empty messages produce 0.0 for UNKNOWN (no bonuses)."""
    result = estimate_complexity([], TaskType.UNKNOWN)
    assert result == 0.0


def test_estimate_complexity_reasoning_type_adds_bonus() -> None:
    """REASONING task type adds 0.2 bonus versus UNKNOWN for same messages."""
    msgs: list[dict[str, Any]] = [{"role": "user", "content": "hello"}]
    score_reasoning = estimate_complexity(msgs, TaskType.REASONING)
    score_unknown = estimate_complexity(msgs, TaskType.UNKNOWN)
    assert score_reasoning > score_unknown


def test_estimate_complexity_large_input_near_one() -> None:
    """Very large input content with reasoning type produces a score of 0.7.

    token_score saturates at 1.0 → contributes 0.5
    reasoning bonus → contributes 0.2
    no tool calls → 0.0
    no code blocks in plain 'x' * 32000 → 0.0
    total = 0.7
    """
    long_content = "x" * 32000  # ~8000 tokens → token_score saturates at 1.0
    msgs: list[dict[str, Any]] = [{"role": "user", "content": long_content}]
    result = estimate_complexity(msgs, TaskType.REASONING)
    assert result == 0.7  # 0.5 (token) + 0.2 (reasoning bonus)
