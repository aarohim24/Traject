"""Benchmark: SDK instrumentation overhead.

Measures the wall-clock overhead added by @traject.instrument() vs a bare
function call. Uses a mock OpenAI client that returns a canned response
in < 1ms (no network I/O).

Usage:
    python bench_sdk_overhead.py [--assert-median-ms 5]

Exits with code 1 if the median overhead exceeds the assertion threshold.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

# Suppress OTEL console output during benchmark
import traject
from traject.compression.strategies import CompressionStrategy
from traject.telemetry import otel_exporter


def _make_mock_response() -> Any:
    """Return a mock OpenAI ChatCompletion response."""
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=50,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
    )
    return SimpleNamespace(
        id="chatcmpl-test",
        choices=[],
        model="gpt-4o",
        usage=usage,
    )


def _baseline_fn(messages: list[dict[str, Any]]) -> Any:
    """Bare function that returns a mock response immediately."""
    return _make_mock_response()


def _instrumented_fn(messages: list[dict[str, Any]]) -> Any:
    """Instrumented wrapper (decorated at module level below)."""
    return _make_mock_response()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assert-median-ms", type=float, default=5.0)
    args = parser.parse_args()
    threshold_ms = args.assert_median_ms

    n_calls = 1000
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, how are you?"},
    ]

    # Disable OTEL stdout during benchmark
    otel_exporter._tracer_provider = None  # type: ignore[attr-defined]
    with patch.object(otel_exporter, "emit_span", return_value=None):
        # Warm up
        for _ in range(10):
            _baseline_fn(messages)

        # Baseline timing
        baseline_times: list[float] = []
        for _ in range(n_calls):
            t0 = time.perf_counter()
            _baseline_fn(messages)
            baseline_times.append((time.perf_counter() - t0) * 1000)

        # Instrument and time
        decorated = traject.instrument(
            feature_tag="bench",
            shadow_mode=True,
            strategy=CompressionStrategy.CONSERVATIVE,
            environment="benchmark",
        )(_instrumented_fn)

        # Warm up instrumented
        for _ in range(10):
            decorated(messages=messages)

        instrumented_times: list[float] = []
        for _ in range(n_calls):
            t0 = time.perf_counter()
            decorated(messages=messages)
            instrumented_times.append((time.perf_counter() - t0) * 1000)

    overhead = [i - b for i, b in zip(instrumented_times, baseline_times, strict=False)]
    overhead.sort()

    p50 = statistics.median(overhead)
    p95 = overhead[int(0.95 * n_calls)]
    p99 = overhead[int(0.99 * n_calls)]

    print(f"SDK Overhead (n={n_calls})")
    print(f"  min:  {min(overhead):.3f} ms")
    print(f"  p50:  {p50:.3f} ms")
    print(f"  p95:  {p95:.3f} ms")
    print(f"  p99:  {p99:.3f} ms")
    print(f"  max:  {max(overhead):.3f} ms")
    print(f"  threshold: {threshold_ms} ms")

    if p50 > threshold_ms:
        print(f"FAIL: p50 overhead {p50:.3f} ms exceeds threshold {threshold_ms} ms")
        sys.exit(1)
    print(f"PASS: p50 overhead {p50:.3f} ms is within {threshold_ms} ms threshold")


if __name__ == "__main__":
    main()
