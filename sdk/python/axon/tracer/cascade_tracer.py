"""CascadeTracer: orchestrator and sub-agent API for multi-agent trace management.

Provides three public symbols consumed by multi-agent workloads:

* :class:`TraceContext` — immutable snapshot of the current agent's position
  inside a distributed trace.  Produced by both
  :meth:`CascadeTracer.start_orchestration` and
  :meth:`CascadeTracer.join_trace`.

* :class:`CascadeCostSummary` — aggregated cost report for a complete trace,
  broken down by sub-agent ``feature_tag``.  All monetary fields use
  :class:`decimal.Decimal` (ADR-006).

* :class:`CascadeTracer` — stateless helper class whose methods generate or
  parse W3C ``traceparent`` headers and, optionally, query the Axon backend
  for per-span cost data.

All trace and span identifiers are generated with :func:`uuid.uuid4` and
meet the W3C Trace Context Level 1 bit-width requirements: 128-bit trace IDs
(32 hex chars) and 64-bit span IDs (16 hex chars).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from axon.tracer.context_propagator import extract_trace_context, inject_trace_context


@dataclass
class TraceContext:
    """Immutable snapshot of an agent's position inside a distributed trace.

    Produced by :meth:`CascadeTracer.start_orchestration` (orchestrator) or
    :meth:`CascadeTracer.join_trace` (sub-agent).  The ``span_id`` uniquely
    identifies *this* agent's root span within the trace; it differs from the
    ``parent_span_id`` that was extracted from the inbound ``traceparent``
    header when a sub-agent calls ``join_trace``.

    Attributes:
        trace_id: 32 lowercase hexadecimal characters representing the
            128-bit W3C trace identifier shared by all agents in the cascade.
        span_id: 16 lowercase hexadecimal characters representing the 64-bit
            W3C span identifier for this agent's root span.
        feature_tag: A human-readable label for the feature or workflow that
            owns this trace (e.g. ``"document-summariser"``).  Empty string
            for sub-agents that joined an existing trace.
        metadata: Arbitrary string key/value pairs attached to the trace
            context at orchestration start.  Always a ``dict``; never
            ``None``.
    """

    trace_id: str
    span_id: str
    feature_tag: str
    metadata: dict[str, str] = field(default_factory=dict)

    def outbound_headers(self) -> dict[str, str]:
        """Build HTTP headers to propagate this trace to a downstream agent.

        Returns:
            A new ``dict`` containing the ``traceparent`` header formatted as
            ``"00-{trace_id}-{span_id}-01"`` per the W3C Trace Context spec.
            The caller should merge this dict into the HTTP headers of any
            outbound request that should be part of the same distributed
            trace.
        """
        return inject_trace_context({}, self.trace_id, self.span_id)


@dataclass
class CascadeCostSummary:
    """Aggregated cost report for a complete multi-agent cascade trace.

    All monetary fields are :class:`decimal.Decimal` instances (ADR-006).
    When the Axon backend is unavailable or ``backend_client`` is ``None``,
    all cost fields default to ``Decimal("0")``.

    Attributes:
        trace_id: The W3C trace identifier for which costs were aggregated.
        orchestrator_cost_usd: Total inference cost incurred by the
            orchestrating agent in USD.
        sub_agent_costs: Mapping from sub-agent ``feature_tag`` to the total
            USD cost incurred by that agent within this trace.
        total_cost_usd: Sum of orchestrator and all sub-agent costs.
        span_count: Number of individual spans collected for this trace.
        feature_tag: The ``feature_tag`` of the orchestrating agent that
            started the trace.
    """

    trace_id: str
    orchestrator_cost_usd: Decimal
    sub_agent_costs: dict[str, Decimal]
    total_cost_usd: Decimal
    span_count: int
    feature_tag: str


class CascadeTracer:
    """Stateless helper for W3C trace context propagation and cascade cost attribution.

    Orchestrators call :meth:`start_orchestration` to mint a fresh trace,
    sub-agents call :meth:`join_trace` to extract and continue an existing
    trace from inbound HTTP headers, and any agent can call
    :meth:`get_cascade_cost` to retrieve aggregated cost data from the Axon
    backend.

    The class is stateless; a single instance can be shared safely across
    threads and async tasks.  No internal state is stored between calls.

    Example — orchestrator::

        tracer = CascadeTracer()
        ctx = tracer.start_orchestration("document-pipeline", metadata={"env": "prod"})
        response = requests.post(url, headers=ctx.outbound_headers(), json=payload)

    Example — sub-agent::

        tracer = CascadeTracer()
        ctx = tracer.join_trace(dict(request.headers))
        if ctx is None:
            # No trace context in headers; proceed without tracing.
            ...
    """

    def start_orchestration(
        self,
        feature_tag: str,
        metadata: dict[str, str] | None = None,
    ) -> TraceContext:
        """Mint a new distributed trace for an orchestrating agent.

        Generates a cryptographically random 128-bit ``trace_id`` and 64-bit
        ``span_id`` using :func:`uuid.uuid4`.  The returned :class:`TraceContext`
        can be used immediately to produce outbound ``traceparent`` headers via
        :meth:`TraceContext.outbound_headers`.

        Args:
            feature_tag: A short, human-readable label for the feature or
                workflow being traced (e.g. ``"research-agent"``).  Used for
                cost attribution grouping in the backend.
            metadata: Optional string key/value pairs to attach to the trace
                context for downstream consumption.  Defaults to an empty
                dict when ``None``.

        Returns:
            A :class:`TraceContext` with a freshly generated ``trace_id``
            (32 hex chars) and ``span_id`` (16 hex chars).
        """
        trace_id: str = uuid.uuid4().hex  # 32 lowercase hex chars (128-bit)
        span_id: str = uuid.uuid4().hex[:16]  # 16 lowercase hex chars (64-bit)
        resolved_metadata: dict[str, str] = metadata if metadata is not None else {}
        return TraceContext(
            trace_id=trace_id,
            span_id=span_id,
            feature_tag=feature_tag,
            metadata=resolved_metadata,
        )

    def join_trace(
        self,
        inbound_headers: dict[str, str],
    ) -> TraceContext | None:
        """Join an existing distributed trace from inbound HTTP headers.

        Extracts the ``traceparent`` header from *inbound_headers*,
        validates it, and returns a new :class:`TraceContext` that continues
        the same trace with a freshly generated ``span_id`` for this agent's
        root span.

        Fails open: if no valid ``traceparent`` header is present, or if
        extraction raises for any reason, ``None`` is returned and no
        exception propagates.

        Args:
            inbound_headers: A mapping of HTTP header names to values, such
                as the headers dict from an incoming HTTP request.  Lookup
                is performed case-insensitively.

        Returns:
            A :class:`TraceContext` whose ``trace_id`` matches the upstream
            trace and whose ``span_id`` is freshly generated for this agent,
            or ``None`` when no valid trace context can be extracted.
        """
        extracted = extract_trace_context(inbound_headers)
        if extracted is None:
            return None

        trace_id, _parent_span_id = extracted
        span_id: str = uuid.uuid4().hex[:16]
        return TraceContext(
            trace_id=trace_id,
            span_id=span_id,
            feature_tag="",
            metadata={},
        )

    def get_cascade_cost(
        self,
        trace_id: str,
        backend_client: Any | None = None,  # Any: backend client has no fixed interface
    ) -> CascadeCostSummary:
        """Return aggregated cost data for all spans in a trace.

        When *backend_client* is ``None`` (the default), returns a
        :class:`CascadeCostSummary` with all cost fields set to
        ``Decimal("0")`` and ``span_count`` set to ``0``.

        When a *backend_client* is provided, calls
        ``backend_client.get_spans_by_trace_id(trace_id)`` to retrieve a
        list of span records and aggregates costs by ``feature_tag``.  Each
        span record is expected to expose ``cost_usd`` (convertible to
        ``Decimal``) and ``feature_tag`` (``str``) attributes or keys.

        Args:
            trace_id: The 32-char lowercase hex W3C trace identifier whose
                cost should be aggregated.
            backend_client: An optional Axon backend client object that
                exposes ``get_spans_by_trace_id(trace_id: str) -> list[Any]``.
                Pass ``None`` to receive an empty summary without a backend
                query.

        Returns:
            A :class:`CascadeCostSummary` with costs aggregated across all
            spans in the trace, or a zero-cost summary when no backend client
            is available.
        """
        if backend_client is None:
            return CascadeCostSummary(
                trace_id=trace_id,
                orchestrator_cost_usd=Decimal("0"),
                sub_agent_costs={},
                total_cost_usd=Decimal("0"),
                span_count=0,
                feature_tag="",
            )

        spans: list[Any] = backend_client.get_spans_by_trace_id(trace_id)
        orchestrator_cost = Decimal("0")
        sub_agent_costs: dict[str, Decimal] = {}
        feature_tag = ""

        for span in spans:
            # Support both attribute-style and dict-style span objects.
            if isinstance(span, dict):
                span_cost = Decimal(str(span.get("cost_usd", "0")))
                span_feature_tag: str = str(span.get("feature_tag", ""))
                is_orchestrator: bool = bool(span.get("is_orchestrator", False))
            else:
                span_cost = Decimal(str(getattr(span, "cost_usd", "0")))
                span_feature_tag = str(getattr(span, "feature_tag", ""))
                is_orchestrator = bool(getattr(span, "is_orchestrator", False))

            if is_orchestrator:
                orchestrator_cost += span_cost
                if not feature_tag:
                    feature_tag = span_feature_tag
            else:
                sub_agent_costs[span_feature_tag] = (
                    sub_agent_costs.get(span_feature_tag, Decimal("0")) + span_cost
                )

        total_cost = orchestrator_cost + sum(sub_agent_costs.values())

        return CascadeCostSummary(
            trace_id=trace_id,
            orchestrator_cost_usd=orchestrator_cost,
            sub_agent_costs=sub_agent_costs,
            total_cost_usd=total_cost,
            span_count=len(spans),
            feature_tag=feature_tag,
        )
