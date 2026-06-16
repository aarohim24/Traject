"""Multi-agent cascade tracer for W3C TraceContext propagation.

Provides :class:`~traject.tracer.cascade_tracer.CascadeTracer` for starting and
joining distributed traces across multi-agent workloads, plus the low-level
:mod:`~traject.tracer.context_propagator` module for injecting and extracting W3C
``traceparent`` headers. All trace and span identifiers are randomly generated
using :func:`uuid.uuid4` and conform to the 128-bit / 64-bit W3C spec
requirements. No external network calls are made during trace context
propagation; the backend is contacted only for cost aggregation in
:meth:`~traject.tracer.cascade_tracer.CascadeTracer.get_cascade_cost`.
"""
