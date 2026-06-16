"""OpenTelemetry span emission for the Axon SDK.

Provides ``configure_exporter`` and ``emit_span`` for converting Axon
``InferenceSpan`` objects into structured OTEL spans and exporting them
to stdout or an OTLP endpoint.
"""
from traject.telemetry.otel_exporter import configure_exporter, emit_span

__all__ = ["configure_exporter", "emit_span"]
