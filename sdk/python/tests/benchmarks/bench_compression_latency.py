"""Benchmark: Compression pipeline latency.

Measures the wall-clock latency of compress() for synthetic message arrays
of 5, 10, 20, and 50 segments.

Usage:
    python bench_compression_latency.py [--assert-median-ms 50]

Exits with code 1 if the p50 latency for 20-segment context exceeds the
assertion threshold.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from typing import Any

from traject.compression.engine import compress
from traject.compression.strategies import CompressionStrategy, get_config


def _make_messages(n: int) -> list[dict[str, Any]]:
    """Build a synthetic message list with n messages."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a helpful AI assistant. Answer concisely."}
    ]
    for i in range(n - 1):
        if i % 2 == 0:
            messages.append({"role": "user", "content": f"User message number {i + 1}. Please help me with task {i + 1}."})
        else:
            messages.append({"role": "assistant", "content": f"Assistant response number {i + 1}. Here is my answer to task {i}."})
    return messages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assert-median-ms", type=float, default=50.0)
    args = parser.parse_args()
    threshold_ms = args.assert_median_ms

    config = get_config(CompressionStrategy.CONSERVATIVE)
    segment_counts = [5, 10, 20, 50]
    n_iterations = 100

    results: dict[int, dict[str, float]] = {}
    target_p50: float | None = None

    for n in segment_counts:
        messages = _make_messages(n)
        latencies: list[float] = []

        # Warm up
        for _ in range(5):
            compress(messages, config)

        for _ in range(n_iterations):
            t0 = time.perf_counter()
            compress(messages, config)
            latencies.append((time.perf_counter() - t0) * 1000)

        latencies.sort()
        p50 = statistics.median(latencies)
        p95 = latencies[int(0.95 * n_iterations)]
        results[n] = {"min": min(latencies), "p50": p50, "p95": p95, "max": max(latencies)}

        if n == 20:
            target_p50 = p50

    print(f"Compression Latency (n_iterations={n_iterations}, shadow_mode=True, CONSERVATIVE)")
    print(f"{'Segments':<10} {'min (ms)':<12} {'p50 (ms)':<12} {'p95 (ms)':<12} {'max (ms)':<12}")
    print("-" * 58)
    for n in segment_counts:
        r = results[n]
        print(f"{n:<10} {r['min']:<12.3f} {r['p50']:<12.3f} {r['p95']:<12.3f} {r['max']:<12.3f}")

    print(f"\nThreshold (20 segments, p50): {threshold_ms} ms")

    if target_p50 is not None and target_p50 > threshold_ms:
        print(f"FAIL: 20-segment p50 {target_p50:.3f} ms exceeds threshold {threshold_ms} ms")
        sys.exit(1)
    print(f"PASS: 20-segment p50 {target_p50:.3f} ms is within {threshold_ms} ms threshold")


if __name__ == "__main__":
    main()
