"""Unit tests for axon/telemetry/otel_exporter.py.

Validates: Requirements R4.1, R11.1–11.5
"""
from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from traject.classifier.artifact_type import ArtifactType
from traject.models import InferenceSpan


def _make_span(
    *,
    cost_usd: Decimal | None = Decimal("0.00050000"),
    tokens_saved: int | None = 10,
    feature_tag: str = "test-feature",
    provider: str = "openai",
    model: str = "gpt-4o",
    input_tokens: int = 50,
    output_tokens: int = 25,
    compression_applied: bool = False,
    shadow_mode: bool = True,
    cache_hit: bool = False,
    environment: str = "test",
) -> InferenceSpan:
    return InferenceSpan(
        id=uuid4(),
        trace_id="trace-abc",
        parent_span_id=None,
        span_name=f"gen_ai.{provider}.{model}",
        timestamp=datetime.utcnow(),
        duration_ms=100,
        provider=provider,
        model=model,
        api_version=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=0,
        token_count_method="exact",
        cost_usd=cost_usd,
        feature_tag=feature_tag,
        prompt_hash="a" * 64,
        artifact_type=ArtifactType.USER_MESSAGE,
        compression_applied=compression_applied,
        shadow_mode=shadow_mode,
        pre_compression_tokens=None,
        tokens_saved=tokens_saved,
        cache_hit=cache_hit,
        environment=environment,
    )


@pytest.fixture(autouse=True)
def reset_exporter_state() -> Generator[None, None, None]:
    import axon.telemetry.otel_exporter as mod
    mod._tracer_provider = None  # type: ignore[attr-defined]
    yield
    mod._tracer_provider = None  # type: ignore[attr-defined]


def _setup_in_memory_exporter() -> tuple[InMemorySpanExporter, TracerProvider]:
    import axon.telemetry.otel_exporter as mod
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    mod._tracer_provider = provider  # type: ignore[attr-defined]
    return exporter, provider


class TestConfigureExporter:

    def test_sets_tracer_provider_on_first_call(self) -> None:
        import axon.telemetry.otel_exporter as mod
        assert mod._tracer_provider is None
        mod.configure_exporter(export_to_stdout=False)
        assert mod._tracer_provider is not None

    def test_idempotent(self) -> None:
        import axon.telemetry.otel_exporter as mod
        mod.configure_exporter(export_to_stdout=False)
        first = mod._tracer_provider
        mod.configure_exporter(export_to_stdout=False)
        assert mod._tracer_provider is first

    def test_otlp_endpoint_accepted(self) -> None:
        import axon.telemetry.otel_exporter as mod
        mod.configure_exporter(export_to_stdout=False, otlp_endpoint="http://localhost:4317")
        assert mod._tracer_provider is not None

    def test_env_var_otlp_endpoint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import axon.telemetry.otel_exporter as mod
        monkeypatch.setenv("AXON_OTLP_ENDPOINT", "http://localhost:4317")
        mod.configure_exporter(export_to_stdout=False)
        assert mod._tracer_provider is not None


class TestEmitSpan:

    def test_gen_ai_attributes_set(self) -> None:
        exporter, _ = _setup_in_memory_exporter()
        import axon.telemetry.otel_exporter as mod
        mod.emit_span(_make_span(provider="openai", model="gpt-4o"))
        attrs = exporter.get_finished_spans()[0].attributes
        assert attrs is not None
        assert attrs["gen_ai.system"] == "openai"
        assert attrs["gen_ai.request.model"] == "gpt-4o"

    def test_token_attributes_set(self) -> None:
        exporter, _ = _setup_in_memory_exporter()
        import axon.telemetry.otel_exporter as mod
        mod.emit_span(_make_span(input_tokens=100, output_tokens=50))
        attrs = exporter.get_finished_spans()[0].attributes
        assert attrs is not None
        assert attrs["gen_ai.usage.input_tokens"] == 100
        assert attrs["gen_ai.usage.output_tokens"] == 50

    def test_cost_usd_serialized_as_string(self) -> None:
        exporter, _ = _setup_in_memory_exporter()
        import axon.telemetry.otel_exporter as mod
        cost = Decimal("0.00123456")
        mod.emit_span(_make_span(cost_usd=cost))
        attrs = exporter.get_finished_spans()[0].attributes
        assert attrs is not None
        assert attrs["axon.cost_usd"] == str(cost)

    def test_cost_usd_none_is_empty_string(self) -> None:
        exporter, _ = _setup_in_memory_exporter()
        import axon.telemetry.otel_exporter as mod
        mod.emit_span(_make_span(cost_usd=None))
        attrs = exporter.get_finished_spans()[0].attributes
        assert attrs is not None
        assert attrs["axon.cost_usd"] == ""

    def test_tokens_saved_none_is_zero(self) -> None:
        exporter, _ = _setup_in_memory_exporter()
        import axon.telemetry.otel_exporter as mod
        mod.emit_span(_make_span(tokens_saved=None))
        attrs = exporter.get_finished_spans()[0].attributes
        assert attrs is not None
        assert attrs["axon.compression.tokens_saved"] == 0

    def test_all_fifteen_attributes_present(self) -> None:
        exporter, _ = _setup_in_memory_exporter()
        import axon.telemetry.otel_exporter as mod
        mod.emit_span(_make_span())
        attrs = exporter.get_finished_spans()[0].attributes
        assert attrs is not None
        required = {
            "gen_ai.system", "gen_ai.request.model",
            "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
            "axon.cost_usd", "axon.feature_tag", "axon.prompt_hash",
            "axon.artifact_type", "axon.compression.applied",
            "axon.compression.shadow_mode", "axon.compression.tokens_saved",
            "axon.cache_hit", "axon.environment", "axon.duration_ms",
            "axon.token_count_method",
        }
        assert required.issubset(set(attrs.keys()))

    def test_auto_configures_if_not_configured(self) -> None:
        import axon.telemetry.otel_exporter as mod
        assert mod._tracer_provider is None
        mod.emit_span(_make_span())
        assert mod._tracer_provider is not None
