"""OpenTelemetry span exporter for the Traject SDK.

Implements the telemetry export layer described in ADR-001 (OTel-first
telemetry). Converts :class:`~traject.models.InferenceSpan` Pydantic models
into OTEL spans and ships them to a :class:`ConsoleSpanExporter` by default,
or an :class:`OTLPSpanExporter` when an OTLP endpoint is configured.

The module-level :func:`configure_exporter` function is idempotent — it is
safe to call many times; the :class:`TracerProvider` is created exactly once
per process. :func:`emit_span` calls :func:`configure_exporter` automatically,
so explicit configuration is optional for stdout-only use cases.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from traject.models import InferenceSpan

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_tracer_provider: TracerProvider | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_exporter(
    otlp_endpoint: str | None = None,
    export_to_stdout: bool = True,
) -> None:
    """Configure the global OTEL tracer provider for the Traject SDK.

    This function is idempotent: if a :class:`TracerProvider` has already
    been created, subsequent calls return immediately without modifying any
    state. It is safe to call from multiple code paths without guard checks.

    Args:
        otlp_endpoint: gRPC endpoint for an OTLP collector (e.g.
            ``"http://localhost:4317"``). When ``None``, the
            ``TRAJECT_OTLP_ENDPOINT`` environment variable is checked. If
            neither is set, OTLP export is disabled.
        export_to_stdout: When ``True`` (the default), a
            :class:`~opentelemetry.sdk.trace.export.ConsoleSpanExporter` is
            attached so that spans are printed to standard output. Useful for
            local development without a collector.

    Returns:
        None
    """
    global _tracer_provider

    if _tracer_provider is not None:
        return

    resource = Resource.create(
        {
            "service.name": "traject-sdk",
            "service.version": "0.1.0",
        }
    )
    provider = TracerProvider(resource=resource)

    if export_to_stdout:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    endpoint = otlp_endpoint or os.environ.get("TRAJECT_OTLP_ENDPOINT")
    if endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )

    trace.set_tracer_provider(provider)
    _tracer_provider = provider


def emit_span(span_data: InferenceSpan) -> None:
    """Export a single :class:`~traject.models.InferenceSpan` as an OTEL span.

    Calls :func:`configure_exporter` with default arguments before emitting,
    so a :class:`TracerProvider` is always available. If
    :func:`configure_exporter` has already been called (e.g. via
    :func:`traject.core.instrumentor.configure`), that call is a no-op.

    The span is opened synchronously, all attributes are set, and the span
    is ended before this function returns. The OTEL SDK's
    :class:`~opentelemetry.sdk.trace.export.BatchSpanProcessor` (when
    configured) handles async export in a background thread.

    The ``cost_usd`` field is serialised as a string to preserve
    :class:`~decimal.Decimal` precision; OTEL attribute values do not
    support arbitrary-precision numerics.

    The tracer is obtained directly from the module-level
    :data:`_tracer_provider` instance (not from the OTEL global accessor)
    so that tests can inject an
    :class:`~opentelemetry.sdk.trace.export.in_memory_span_exporter.InMemorySpanExporter`-backed
    provider without fighting the OTEL SDK's singleton override guard.

    Args:
        span_data: Fully populated :class:`~traject.models.InferenceSpan`
            instance produced by the instrumentation layer.

    Returns:
        None
    """
    configure_exporter()

    # Use the module-level provider directly to allow test injection
    # without triggering the OTEL global-override guard.
    assert _tracer_provider is not None  # configure_exporter() guarantees this
    tracer = _tracer_provider.get_tracer("traject-sdk", "0.1.0")

    with tracer.start_as_current_span(span_data.span_name) as span:
        span.set_attribute("gen_ai.system", span_data.provider)
        span.set_attribute("gen_ai.request.model", span_data.model)
        span.set_attribute("gen_ai.usage.input_tokens", span_data.input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", span_data.output_tokens)
        span.set_attribute(
            "traject.cost_usd",
            str(span_data.cost_usd) if span_data.cost_usd is not None else "",
        )
        span.set_attribute("traject.feature_tag", span_data.feature_tag)
        span.set_attribute("traject.prompt_hash", span_data.prompt_hash)
        span.set_attribute("traject.artifact_type", span_data.artifact_type.value)
        span.set_attribute("traject.compression.applied", span_data.compression_applied)
        span.set_attribute("traject.compression.shadow_mode", span_data.shadow_mode)
        span.set_attribute(
            "traject.compression.tokens_saved", span_data.tokens_saved or 0
        )
        span.set_attribute("traject.cache_hit", span_data.cache_hit)
        span.set_attribute("traject.environment", span_data.environment)
        span.set_attribute("traject.duration_ms", span_data.duration_ms)
        span.set_attribute("traject.token_count_method", span_data.token_count_method)
