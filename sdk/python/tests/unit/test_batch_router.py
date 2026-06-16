"""Unit and property-based tests for traject.batch.batch_router.

Covers :class:`~traject.batch.batch_router.BatchRouter` filtering behaviour,
error handling on API failures, and the ``poll_and_collect`` stub.

Validates: Requirements 20.1, 20.2
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from traject.batch.batch_router import BatchJobRecord, BatchJobStatus, BatchRouter
from traject.classifier.artifact_type import ArtifactType
from traject.models import InferenceSpan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_span(*, batch_eligible: bool = True) -> InferenceSpan:
    """Build a minimal valid :class:`InferenceSpan` for testing.

    Args:
        batch_eligible: Whether the span is eligible for batch submission.

    Returns:
        A fully-constructed :class:`InferenceSpan`.
    """
    return InferenceSpan(
        id=uuid4(),
        trace_id="trace-abc",
        parent_span_id=None,
        span_name="gen_ai.openai.gpt-4o",
        timestamp=datetime.now(tz=UTC),
        duration_ms=100,
        provider="openai",
        model="gpt-4o",
        api_version=None,
        input_tokens=50,
        output_tokens=25,
        cached_tokens=0,
        token_count_method="exact",
        cost_usd=Decimal("0.001"),
        feature_tag="test",
        prompt_hash="a" * 64,
        artifact_type=ArtifactType.USER_MESSAGE,
        compression_applied=False,
        shadow_mode=True,
        pre_compression_tokens=None,
        tokens_saved=None,
        cache_hit=False,
        environment="test",
        batch_eligible=batch_eligible,
    )


def _make_openai_client(*, file_id: str = "file-123", batch_id: str = "batch-456") -> Any:
    """Build a minimal mock openai client that succeeds.

    Args:
        file_id: ID to return on ``files.create``.
        batch_id: ID to return on ``batches.create``.

    Returns:
        A :class:`~unittest.mock.MagicMock` mimicking ``openai.AsyncOpenAI``.
    """
    client = MagicMock()

    file_obj = MagicMock()
    file_obj.id = file_id

    batch_obj = MagicMock()
    batch_obj.id = batch_id
    batch_obj.expires_at = None

    client.files.create = AsyncMock(return_value=file_obj)
    client.batches.create = AsyncMock(return_value=batch_obj)
    return client


# ---------------------------------------------------------------------------
# Task 20.1 — Unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_batch_filters_non_eligible_spans() -> None:
    """submit_batch() must count only batch_eligible=True spans.

    Two eligible spans and one non-eligible span are submitted.
    The returned record's ``span_count`` must be 2, not 3.
    """
    client = _make_openai_client()
    router = BatchRouter(openai_client=client)

    spans = [
        _make_span(batch_eligible=True),
        _make_span(batch_eligible=True),
        _make_span(batch_eligible=False),
    ]

    result = await router.submit_batch(spans, "openai")

    assert isinstance(result, BatchJobRecord)
    assert result.span_count == 2


@pytest.mark.asyncio
async def test_submit_batch_returns_failed_on_api_failure() -> None:
    """submit_batch() returns FAILED when the API call raises.

    Mocking ``openai_client.files.create`` to raise ``RuntimeError``
    must result in a ``BatchJobRecord`` with ``status == FAILED``, not a
    raised exception.
    """
    client = MagicMock()
    client.files.create = AsyncMock(side_effect=RuntimeError("api down"))
    router = BatchRouter(openai_client=client)

    spans = [_make_span(batch_eligible=True)]
    result = await router.submit_batch(spans, "openai")

    assert isinstance(result, BatchJobRecord)
    assert result.status == BatchJobStatus.FAILED


@pytest.mark.asyncio
async def test_poll_and_collect_returns_zero_on_empty_job_list() -> None:
    """poll_and_collect() stub returns 0 when no jobs are tracked.

    No clients are provided to ``BatchRouter``.  The method must return
    the integer ``0`` without raising.
    """
    router = BatchRouter()
    mock_db = AsyncMock()

    result = await router.poll_and_collect(mock_db, None)

    assert result == 0


@pytest.mark.asyncio
async def test_submit_batch_returns_failed_when_no_eligible_spans() -> None:
    """submit_batch() returns FAILED immediately when all spans are ineligible.

    No API call should be attempted; the returned record must have
    ``status == FAILED`` and ``span_count == 0``.
    """
    client = _make_openai_client()
    router = BatchRouter(openai_client=client)

    spans = [
        _make_span(batch_eligible=False),
        _make_span(batch_eligible=False),
    ]

    result = await router.submit_batch(spans, "openai")

    assert isinstance(result, BatchJobRecord)
    assert result.status == BatchJobStatus.FAILED
    assert result.span_count == 0
    # No API calls should have been made
    client.files.create.assert_not_called()


# ---------------------------------------------------------------------------
# Task 20.2 — Property-based test
# ---------------------------------------------------------------------------


def _span_strategy() -> st.SearchStrategy[InferenceSpan]:
    """Build a Hypothesis strategy that generates batch-eligible spans.

    Returns:
        A strategy producing :class:`InferenceSpan` objects where
        ``batch_eligible=True``, ``duration_ms >= 0``, and token counts
        are non-negative.
    """
    return st.builds(
        InferenceSpan,
        id=st.builds(uuid4),
        trace_id=st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")), min_size=1, max_size=32),
        parent_span_id=st.none(),
        span_name=st.just("gen_ai.openai.gpt-4o"),
        timestamp=st.just(datetime.now(tz=UTC)),
        duration_ms=st.integers(min_value=0, max_value=10_000),
        provider=st.just("openai"),
        model=st.just("gpt-4o"),
        api_version=st.none(),
        input_tokens=st.integers(min_value=0, max_value=10_000),
        output_tokens=st.integers(min_value=0, max_value=10_000),
        cached_tokens=st.integers(min_value=0, max_value=1_000),
        token_count_method=st.just("exact"),
        cost_usd=st.just(Decimal("0.001")),
        feature_tag=st.just("test"),
        prompt_hash=st.just("a" * 64),
        artifact_type=st.just(ArtifactType.USER_MESSAGE),
        compression_applied=st.just(False),
        shadow_mode=st.just(True),
        pre_compression_tokens=st.none(),
        tokens_saved=st.none(),
        cache_hit=st.just(False),
        environment=st.just("test"),
        batch_eligible=st.just(True),
    )


@pytest.mark.asyncio
async def test_submit_batch_returns_failed_for_unknown_provider() -> None:
    """submit_batch() returns FAILED for an unrecognised provider name.

    When ``provider`` is neither ``"openai"`` nor ``"anthropic"``, the
    router cannot dispatch the batch.  It must return a
    :class:`BatchJobRecord` with ``status == FAILED`` without raising.
    """
    client = _make_openai_client()
    router = BatchRouter(openai_client=client)

    spans = [_make_span(batch_eligible=True)]
    result = await router.submit_batch(spans, "unknown-provider")

    assert isinstance(result, BatchJobRecord)
    assert result.status == BatchJobStatus.FAILED


@pytest.mark.asyncio
async def test_submit_batch_returns_failed_when_anthropic_client_none() -> None:
    """submit_batch() returns FAILED for Anthropic when no client is provided.

    When ``anthropic_client=None`` (the default), attempting to submit to
    ``"anthropic"`` must return a ``FAILED`` record, not raise.
    """
    router = BatchRouter()  # no clients

    spans = [_make_span(batch_eligible=True)]
    result = await router.submit_batch(spans, "anthropic")

    assert isinstance(result, BatchJobRecord)
    assert result.status == BatchJobStatus.FAILED


@given(spans=st.lists(_span_strategy(), min_size=1, max_size=20))
@settings(max_examples=30, deadline=None)
def test_submit_batch_never_raises_for_eligible_spans(spans: list[InferenceSpan]) -> None:
    """submit_batch() always returns a BatchJobRecord — never raises.

    **Validates: Requirements 20.2**

    For any non-empty list of batch-eligible spans, even if the provider
    client raises, ``submit_batch`` must catch the exception and return a
    :class:`BatchJobRecord` with ``status=FAILED``.  This property confirms
    the non-raising contract under all inputs.
    """
    import asyncio

    # The mock client always raises to exercise the FAILED error path.
    client = MagicMock()
    client.files.create = AsyncMock(side_effect=Exception("injected failure"))
    router = BatchRouter(openai_client=client)

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(router.submit_batch(spans, "openai"))
    finally:
        loop.close()

    assert isinstance(result, BatchJobRecord), (
        f"Expected BatchJobRecord, got {type(result)!r}"
    )
    assert result.status == BatchJobStatus.FAILED
