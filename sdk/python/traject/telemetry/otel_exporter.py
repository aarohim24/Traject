"""OpenTelemetry span exporter for the Traject SDK.

Implements the telemetry export layer described in ADR-001 (OTel-first
telemetry). Converts :class:`~traject.models.InferenceSpan` Pydantic models
into OTEL spans and ships them to a :class:`ConsoleSpanExporter` by default,
or an :class:`OTLPSpanExporter` when an OTLP endpoint is configured.

The module-level :func:`configure_exporter` function is idempotent — it is
safe to call many times; the :class:`TracerProvider` is created exactly once
per process. :func:`emit_span` calls :func:`configure_exporter` automatically,
so explicit configuration is optional for stdout-only use cases.

When ``export_format="summary"`` (the default), :func:`emit_span` prints a
compact human-readable line to stdout instead of raw OTEL JSON:

    [traject] model=gpt-4o-mini  tokens=1847→1432  saved=415 (22.5%)  cost=$0.000215  tag=my_agent

Set ``export_format="json"`` via :func:`traject.configure` to restore the
full OTEL JSON output.
"""

from __future__ import annotations

import os
import sys

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
_export_format: str = "summary"  # "summary" | "json"


# ---------------------------------------------------------------------------
# Summary formatter
# ---------------------------------------------------------------------------


def _format_summary(span_data: InferenceSpan) -> str:
    """Return a compact human-readable summary line for a span.

    Format:
        [traject] model=<model>  tokens=<in>→<out>  saved=<n> (<pct>%)  cost=$<usd>  tag=<tag>

    Args:
        span_data: Populated :class:`~traject.models.InferenceSpan` instance.

    Returns:
        A single-line string suitable for printing to stdout.
    """
    tokens_in = span_data.input_tokens
    tokens_out = span_data.output_tokens
    saved = span_data.tokens_saved or 0

    if tokens_in > 0 and saved > 0:
        pct = saved / tokens_in * 100.0
        saved_str = f"saved={saved} ({pct:.1f}%)"
    elif saved > 0:
        saved_str = f"saved={saved}"
    else:
        saved_str = "saved=0"

    cost_str = ""
    if span_data.cost_usd is not None:
        cost_str = f"  cost=${span_data.cost_usd:.6f}"

    shadow_marker = " [shadow]" if span_data.shadow_mode else ""

    return (
        f"[traject] model={span_data.model}  "
        f"tokens={tokens_in}→{tokens_out}  "
        f"{saved_str}"
        f"{cost_str}  "
        f"tag={span_data.feature_tag}"
        f"{shadow_marker}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_exporter(
    otlp_endpoint: str | None = None,
    export_to_stdout: bool = True,
    export_format: str = "summary",
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
        export_to_stdout: When ``True`` (the default), span data is printed
            to standard output. The format is controlled by ``export_format``.
        export_format: Controls stdout output format when ``export_to_stdout``
            is ``True``. ``"summary"`` (default) prints a compact
            human-readable line. ``"json"`` attaches a
            :class:`~opentelemetry.sdk.trace.export.ConsoleSpanExporter` for
            full OTEL JSON output.

    Returns:
        None
    """
    global _tracer_provider, _export_format

    if _tracer_provider is not None:
        return

    _export_format = export_format

    resource = Resource.create(
        {
            "service.name": "traject-sdk",
            "service.version": "0.1.0",
        }
    )
    provider = TracerProvider(resource=resource)

    # Only attach ConsoleSpanExporter for raw JSON mode. Summary mode prints
    # directly in emit_span() to avoid OTEL's verbose JSON wrapping.
    if export_to_stdout and export_format == "json":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    endpoint = otlp_endpoint or os.environ.get("TRAJECT_OTLP_ENDPOINT")
    if endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )

    trace.set_tracer_provider(provider)
    _tracer_provider = provider


def emit_span(span_data: InferenceSpan, export_to_stdout: bool = True) -> None:
    """Export a single :class:`~traject.models.InferenceSpan` as an OTEL span.

    When ``_export_format == "summary"`` and ``export_to_stdout`` is ``True``,
    prints a compact human-readable line directly to stdout before recording
    the OTEL span. When ``_export_format == "json"``, the
    :class:`~opentelemetry.sdk.trace.export.ConsoleSpanExporter` attached
    during :func:`configure_exporter` handles stdout output.

    Calls :func:`configure_exporter` with default arguments before emitting,
    so a :class:`TracerProvider` is always available.

    Args:
        span_data: Fully populated :class:`~traject.models.InferenceSpan`
            instance produced by the instrumentation layer.
        export_to_stdout: Whether to print summary output. Mirrors the flag
            passed to :func:`configure_exporter`. Defaults to ``True``.

    Returns:
        None
    """
    configure_exporter()

    if export_to_stdout and _export_format == "summary":
        print(_format_summary(span_data), flush=True)  # noqa: T201 — intentional user-facing output

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
