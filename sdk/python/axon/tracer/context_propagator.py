"""W3C TraceContext header injection and extraction for multi-agent tracing.

Implements the subset of the W3C Trace Context Level 1 specification
(https://www.w3.org/TR/trace-context/) that is required by the Axon cascade
tracer: serialising a ``traceparent`` header from a ``(trace_id, span_id)``
pair, and deserialising one back into those components. The ``tracestate``
header is recognised by its constant but is not manipulated; callers may pass
it through opaquely.

All public functions in this module are guaranteed never to raise: any
malformed input causes a ``None`` return rather than an exception.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

TRACEPARENT_HEADER: str = "traceparent"
"""Canonical (lowercase) name of the W3C traceparent header."""

TRACESTATE_HEADER: str = "tracestate"
"""Canonical (lowercase) name of the W3C tracestate header."""

# ---------------------------------------------------------------------------
# Internal regex
# ---------------------------------------------------------------------------

_TRACEPARENT_RE: re.Pattern[str] = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$"
)
"""Compiled pattern that validates a ``traceparent`` header value.

Only version ``00`` is supported.  The two capture groups return the
``trace_id`` (32 hex chars) and ``parent_id`` (16 hex chars).
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def inject_trace_context(
    headers: dict[str, str],
    trace_id: str,
    span_id: str,
) -> dict[str, str]:
    """Set the ``traceparent`` header in *headers* using the supplied IDs.

    Mutates *headers* in place and also returns it so callers can use method
    chaining.  The resulting header value follows the W3C spec format::

        traceparent: 00-<trace_id>-<span_id>-01

    The trace-flags byte is always ``01`` (sampled).

    Args:
        headers: A mutable mapping of HTTP header names to values.  The
            ``"traceparent"`` key will be added or overwritten.
        trace_id: 32 lowercase hexadecimal characters representing the
            128-bit trace identifier.
        span_id: 16 lowercase hexadecimal characters representing the
            64-bit span (parent) identifier.

    Returns:
        The same *headers* dict, mutated in place, for method chaining.
    """
    headers[TRACEPARENT_HEADER] = f"00-{trace_id}-{span_id}-01"
    return headers


def extract_trace_context(
    headers: dict[str, str],
) -> tuple[str, str] | None:
    """Parse a ``traceparent`` header value into ``(trace_id, parent_span_id)``.

    Performs a case-insensitive search for the ``traceparent`` key in
    *headers* and validates the value against the W3C pattern.  Returns
    ``None`` — and never raises — when the header is absent, malformed, or
    uses an unsupported version.

    Args:
        headers: A mapping of HTTP header names to values.  Lookup is
            performed case-insensitively so that both ``"Traceparent"`` and
            ``"traceparent"`` are found.

    Returns:
        A ``(trace_id, parent_span_id)`` tuple where both elements are
        32-char and 16-char lowercase hex strings respectively, or ``None``
        if no valid ``traceparent`` header is present.
    """
    try:
        value: str | None = None
        for key, val in headers.items():
            if key.lower() == TRACEPARENT_HEADER:
                value = val
                break

        if value is None:
            return None

        match = _TRACEPARENT_RE.match(value)
        if match is None:
            return None

        return match.group(1), match.group(2)
    except Exception:  # pylint: disable=broad-except
        return None
