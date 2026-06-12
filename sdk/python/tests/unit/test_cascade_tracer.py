"""Unit and property-based tests for axon.tracer.

Covers the W3C TraceContext propagator (context_propagator.py) and the
CascadeTracer orchestration API (cascade_tracer.py).

Validates: Requirements 4 (W3C TraceContext Propagation) and 5 (CascadeTracer API).
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from axon.tracer.cascade_tracer import CascadeCostSummary, CascadeTracer
from axon.tracer.context_propagator import (
    TRACEPARENT_HEADER,
    extract_trace_context,
    inject_trace_context,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRACEPARENT_FULL_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$")
"""Validates a fully-formed sampled traceparent header value."""

_VALID_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
_VALID_SPAN_ID = "00f067aa0ba902b7"


# ---------------------------------------------------------------------------
# Test 1: inject produces a valid traceparent header
# Validates: Requirement 4.1, 4.2
# ---------------------------------------------------------------------------


def test_inject_produces_valid_traceparent() -> None:
    """inject_trace_context sets a traceparent header matching the W3C pattern.

    The resulting value must match ``^00-[0-9a-f]{32}-[0-9a-f]{16}-01$``.
    """
    headers: dict[str, str] = {}
    result = inject_trace_context(headers, _VALID_TRACE_ID, _VALID_SPAN_ID)

    assert TRACEPARENT_HEADER in result
    assert _TRACEPARENT_FULL_RE.match(result[TRACEPARENT_HEADER]), (
        f"traceparent value {result[TRACEPARENT_HEADER]!r} did not match W3C pattern"
    )


# ---------------------------------------------------------------------------
# Test 2: inject → extract round-trip returns identical IDs
# Validates: Requirement 4.5
# ---------------------------------------------------------------------------


def test_inject_extract_round_trip() -> None:
    """Injecting then extracting a traceparent returns the original trace_id and span_id."""
    headers: dict[str, str] = {}
    inject_trace_context(headers, _VALID_TRACE_ID, _VALID_SPAN_ID)

    extracted = extract_trace_context(headers)
    assert extracted is not None, "extract_trace_context returned None after inject"

    extracted_trace_id, extracted_span_id = extracted
    assert extracted_trace_id == _VALID_TRACE_ID
    assert extracted_span_id == _VALID_SPAN_ID


# ---------------------------------------------------------------------------
# Test 3: extract returns None for missing/empty/truncated headers — never raises
# Validates: Requirement 4.4
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"traceparent": ""},
        {"traceparent": "00-tooshort-00f067aa0ba902b7-01"},
        {"traceparent": "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
        {"traceparent": "not-a-traceparent-value"},
        {"x-other-header": "something"},
    ],
    ids=["empty", "empty-value", "truncated-trace-id", "bad-version", "garbage", "unrelated-header"],
)
def test_extract_returns_none_for_invalid_headers(headers: dict[str, str]) -> None:
    """extract_trace_context returns None for missing, empty, or malformed traceparent.

    Must never raise an exception.
    """
    result = extract_trace_context(headers)
    assert result is None, f"Expected None for headers={headers!r}, got {result!r}"


# ---------------------------------------------------------------------------
# Test 4: PBT — arbitrary strings as traceparent never cause extract to raise
# Validates: Requirements 4.3, 4.4 (P-T2)
# **Validates: Requirements 4.3, 4.4**
# ---------------------------------------------------------------------------


@given(
    key=st.text(min_size=0, max_size=64),
    value=st.text(min_size=0, max_size=512),
)
@settings(max_examples=500)
def test_property_extract_never_raises_on_arbitrary_input(key: str, value: str) -> None:
    """**Validates: Requirements 4.3, 4.4**

    P-T2: extract_trace_context never raises for any dict with arbitrary
    string keys and values, including the traceparent key with random content.
    The result is either a valid (trace_id, span_id) tuple or None.
    """
    headers: dict[str, str] = {key: value}
    # Must not raise under any circumstance
    result = extract_trace_context(headers)
    # Result is either None or a 2-tuple of strings
    if result is not None:
        trace_id, span_id = result
        assert isinstance(trace_id, str)
        assert isinstance(span_id, str)
        assert len(trace_id) == 32
        assert len(span_id) == 16
        assert re.fullmatch(r"[0-9a-f]{32}", trace_id)
        assert re.fullmatch(r"[0-9a-f]{16}", span_id)


# ---------------------------------------------------------------------------
# Test 5: start_orchestration produces valid trace_id and span_id
# Validates: Requirement 5.1
# ---------------------------------------------------------------------------


def test_start_orchestration_produces_valid_ids() -> None:
    """start_orchestration returns a TraceContext with valid 32-hex trace_id and 16-hex span_id."""
    tracer = CascadeTracer()
    ctx = tracer.start_orchestration("test-feature", metadata={"env": "ci"})

    assert re.fullmatch(r"[0-9a-f]{32}", ctx.trace_id), (
        f"trace_id {ctx.trace_id!r} is not 32 lowercase hex chars"
    )
    assert re.fullmatch(r"[0-9a-f]{16}", ctx.span_id), (
        f"span_id {ctx.span_id!r} is not 16 lowercase hex chars"
    )
    assert ctx.feature_tag == "test-feature"
    assert ctx.metadata == {"env": "ci"}


# ---------------------------------------------------------------------------
# Test 6: join_trace with valid headers returns TraceContext with matching trace_id
# Validates: Requirement 5.3
# ---------------------------------------------------------------------------


def test_join_trace_with_valid_headers_returns_matching_trace_id() -> None:
    """join_trace returns a TraceContext whose trace_id matches the inbound header."""
    headers: dict[str, str] = {}
    inject_trace_context(headers, _VALID_TRACE_ID, _VALID_SPAN_ID)

    tracer = CascadeTracer()
    ctx = tracer.join_trace(headers)

    assert ctx is not None, "join_trace returned None for valid headers"
    assert ctx.trace_id == _VALID_TRACE_ID
    # Sub-agent gets a freshly generated span_id — it must differ from parent
    assert re.fullmatch(r"[0-9a-f]{16}", ctx.span_id), (
        f"span_id {ctx.span_id!r} is not 16 lowercase hex chars"
    )


# ---------------------------------------------------------------------------
# Test 7: join_trace with empty dict returns None
# Validates: Requirement 5.4
# ---------------------------------------------------------------------------


def test_join_trace_with_empty_headers_returns_none() -> None:
    """join_trace returns None (fail open) when no traceparent header is present."""
    tracer = CascadeTracer()
    result = tracer.join_trace({})
    assert result is None


# ---------------------------------------------------------------------------
# Test 8: get_cascade_cost with no backend_client returns zero-cost summary
# Validates: Requirement 5.5
# ---------------------------------------------------------------------------


def test_get_cascade_cost_no_backend_returns_zero_summary() -> None:
    """get_cascade_cost without a backend_client returns a CascadeCostSummary with Decimal(0) totals."""
    tracer = CascadeTracer()
    summary = tracer.get_cascade_cost(_VALID_TRACE_ID)

    assert isinstance(summary, CascadeCostSummary)
    assert summary.trace_id == _VALID_TRACE_ID
    assert summary.orchestrator_cost_usd == Decimal("0")
    assert summary.total_cost_usd == Decimal("0")
    assert summary.sub_agent_costs == {}
    assert summary.span_count == 0
