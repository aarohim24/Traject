"""Unit tests for axon.backend_client.BackendClient.

Uses ``respx`` to mock HTTP transport so the real httpx.AsyncClient is
exercised without making live network calls.  The module under test is never
mocked — only external HTTP is intercepted.

Validates: Requirements 3 (Backend Integration, fail-open contract).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import httpx
import pytest
import respx

from axon.backend_client import BackendClient, BudgetStatus
from axon.classifier.artifact_type import ArtifactType
from axon.models import InferenceSpan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_span(**overrides: object) -> InferenceSpan:
    """Build a minimal valid :class:`InferenceSpan` for test use."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "parent_span_id": None,
        "span_name": "gen_ai.openai.gpt-4o-mini",
        "timestamp": datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.UTC),
        "duration_ms": 500,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_version": None,
        "input_tokens": 100,
        "output_tokens": 50,
        "cached_tokens": 0,
        "token_count_method": "exact",
        "cost_usd": Decimal("0.00007500"),
        "feature_tag": "test-feature",
        "prompt_hash": "a" * 64,
        "artifact_type": ArtifactType.USER_MESSAGE,
        "compression_applied": False,
        "shadow_mode": True,
        "pre_compression_tokens": None,
        "tokens_saved": None,
        "cache_hit": False,
        "environment": "test",
        "batch_eligible": False,
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return InferenceSpan(**defaults)  # type: ignore[arg-type]


_BASE_URL = "http://axon-backend.test"
_API_KEY = "test-api-key"


# ---------------------------------------------------------------------------
# Test 1: send_span fires POST to /v1/spans with correct payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_span_posts_to_v1_spans_with_correct_payload() -> None:
    """send_span fires a POST to /v1/spans and includes the span in a 'spans' list.

    Verifies the request URL path, the presence of the API key header, and
    that the payload wraps the span dict under the 'spans' key.
    """
    span = _make_span()

    with respx.mock(base_url=_BASE_URL, assert_all_called=True) as mock:
        route = mock.post("/v1/spans").mock(
            return_value=httpx.Response(200, json={"received": 1})
        )

        client = BackendClient(base_url=_BASE_URL, api_key=_API_KEY)
        await client.send_span(span)
        await client.close()

    assert route.called, "POST /v1/spans was not called"
    request = route.calls.last.request

    # Verify API key header is present
    assert request.headers.get("x-axon-api-key") == _API_KEY

    # Verify payload structure
    import json

    payload = json.loads(request.content)
    assert "spans" in payload, f"'spans' key missing from payload: {payload.keys()}"
    assert isinstance(payload["spans"], list)
    assert len(payload["spans"]) == 1

    span_data = payload["spans"][0]
    assert span_data["feature_tag"] == "test-feature"
    assert span_data["model"] == "gpt-4o-mini"
    assert span_data["provider"] == "openai"


# ---------------------------------------------------------------------------
# Test 2: send_span does not raise on 500 response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_span_does_not_raise_on_500_response() -> None:
    """send_span must not raise when the backend returns a 500 HTTP error.

    Fail-open contract: HTTP errors are logged but never propagated.
    """
    span = _make_span()

    with respx.mock(base_url=_BASE_URL):
        respx.post("/v1/spans").mock(
            return_value=httpx.Response(500, json={"error": "internal server error"})
        )

        client = BackendClient(base_url=_BASE_URL, api_key=_API_KEY)
        # Must not raise
        await client.send_span(span)
        await client.close()


# ---------------------------------------------------------------------------
# Test 3: check_budget returns BudgetStatus.OK on HTTP 500
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_budget_returns_ok_on_http_500() -> None:
    """check_budget returns BudgetStatus.OK when the backend returns a 500 error.

    Fail-open contract: any non-success response must not block LLM calls.
    """
    with respx.mock(base_url=_BASE_URL):
        respx.get("/v1/budgets/my-feature").mock(
            return_value=httpx.Response(500, json={"error": "internal server error"})
        )

        client = BackendClient(base_url=_BASE_URL, api_key=_API_KEY)
        result = await client.check_budget("my-feature")
        await client.close()

    assert result == BudgetStatus.OK, (
        f"Expected BudgetStatus.OK on HTTP 500, got {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: check_budget returns BudgetStatus.OK on network timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_budget_returns_ok_on_network_timeout() -> None:
    """check_budget returns BudgetStatus.OK when the network request times out.

    Fail-open contract: timeouts and network errors must not block LLM calls.
    """
    with respx.mock(base_url=_BASE_URL):
        respx.get("/v1/budgets/my-feature").mock(
            side_effect=httpx.TimeoutException("timed out")
        )

        client = BackendClient(base_url=_BASE_URL, api_key=_API_KEY)
        result = await client.check_budget("my-feature")
        await client.close()

    assert result == BudgetStatus.OK, (
        f"Expected BudgetStatus.OK on timeout, got {result!r}"
    )


# ---------------------------------------------------------------------------
# Test 5: check_budget returns correct status from successful response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_str,expected",
    [
        ("ok", BudgetStatus.OK),
        ("warning", BudgetStatus.WARNING),
        ("exhausted", BudgetStatus.EXHAUSTED),
    ],
    ids=["ok", "warning", "exhausted"],
)
async def test_check_budget_parses_status_correctly(
    status_str: str, expected: BudgetStatus
) -> None:
    """check_budget returns the correct BudgetStatus for each valid status string."""
    with respx.mock(base_url=_BASE_URL, assert_all_called=False) as mock:
        mock.get("/v1/budgets/tagged-feature").mock(
            return_value=httpx.Response(200, json={"status": status_str})
        )

        client = BackendClient(base_url=_BASE_URL, api_key=_API_KEY)
        result = await client.check_budget("tagged-feature")
        await client.close()

    assert result == expected
