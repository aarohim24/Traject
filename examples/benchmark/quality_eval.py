#!/usr/bin/env python3
"""Traject compression quality evaluator — information retention analysis.

Measures whether compression preserves semantically critical content from
the original trajectory. This is a proxy for agent quality: if the
information the agent needed is still present in the compressed context,
the agent's behaviour should not degrade.

Methodology
-----------
For each trajectory:

1. Run compression (CONSERVATIVE, shadow_mode=False) to get the
   compressed message list.
2. Identify "dropped" and "summarized" segments — the ones compression
   actually modified.
3. For each modified segment, compute the maximum cosine similarity
   between that segment's embedding and the embedding of the nearest
   segment in the compressed context.
4. If similarity >= RETENTION_THRESHOLD (default 0.7), the segment's
   key information is considered retained.
5. Retention rate = retained / total_modified.

A retention rate >= 0.90 means 90%+ of compressed content is still
semantically accessible in the compressed context — indicating low
information loss despite token savings.

Usage
-----
::

    python examples/benchmark/quality_eval.py --input trajectories.jsonl
    python examples/benchmark/quality_eval.py --input trajectories.jsonl --n-instances 50
    python examples/benchmark/quality_eval.py --input trajectories.jsonl --output-json quality_results.json

No live LLM calls are made.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

try:
    from sentence_transformers import SentenceTransformer

    _model: SentenceTransformer = SentenceTransformer("all-MiniLM-L6-v2")
except ImportError as exc:
    print(f"ERROR: sentence-transformers not found ({exc}).", file=sys.stderr)
    sys.exit(1)

try:
    from traject.compression.engine import compress
    from traject.compression.strategies import (
        CompressionConfig,
        CompressionStrategy,
    )
except ImportError as exc:
    print(f"ERROR: Traject SDK not found ({exc}).", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RETENTION_THRESHOLD: float = 0.70  # cosine similarity >= this → retained
_TOOL_OBS_MARKERS = (
    "OBSERVATION:", "observation:", "EXECUTION RESULT", "stdout:", "stderr:",
    "exit code:", "$ ", "bash-", "[Command output]",
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class InstanceQuality:
    """Quality metrics for a single compressed trajectory."""

    instance_id: str
    original_tokens: int
    compressed_tokens: int
    reduction_pct: float
    segments_modified: int       # dropped + summarized
    segments_retained: int       # modified but info still in compressed context
    retention_rate: float        # retained / modified (NaN if 0 modified)
    elapsed_ms: float
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class AggregateQuality:
    """Aggregate quality metrics across all instances."""

    n_instances: int
    n_skipped: int
    mean_reduction_pct: float
    aggregate_reduction_pct: float
    mean_retention_rate: float
    p10_retention_rate: float    # worst-case instances
    p50_retention_rate: float
    p90_retention_rate: float
    total_segments_modified: int
    total_segments_retained: int
    overall_retention_rate: float


# ---------------------------------------------------------------------------
# Trajectory loading (reused from swebench_eval)
# ---------------------------------------------------------------------------

_MESSAGE_KEYS = ("messages", "query", "history", "conversation", "turns")


def _extract_messages(record: dict[str, Any]) -> list[dict[str, Any]] | None:
    if "data" in record and isinstance(record["data"], dict):
        record = record["data"]
    for key in _MESSAGE_KEYS:
        value = record.get(key)
        if isinstance(value, list) and len(value) > 0:
            if isinstance(value[0], dict) and ("role" in value[0] or "content" in value[0]):
                return _normalise_messages(value)
    return None


def _normalise_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role: str = str(msg.get("role", "user"))
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                    elif "text" in block:
                        parts.append(str(block["text"]))
                elif isinstance(block, str):
                    parts.append(block)
            content = " ".join(parts)
        else:
            content = str(content)
        if role in ("function", "ipython", "observation"):
            role = "tool"
        if role == "user" and i > 0:
            prev_role = str(messages[i - 1].get("role", ""))
            if prev_role == "assistant":
                content_start = content.lstrip()[:80].lower()
                if any(m.lower() in content_start for m in _TOOL_OBS_MARKERS):
                    role = "tool"
        normalised.append({"role": role, "content": content})
    return normalised


def load_trajectories(path: Path, n: int | None) -> list[tuple[str, list[dict[str, Any]]]]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    instances = []
    with path.open("r", encoding="utf-8") as fh:
        for line_num, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            instance_id = str(
                record.get("instance_id") or record.get("id") or f"line_{line_num}"
            )
            msgs = _extract_messages(record)
            if msgs:
                instances.append((instance_id, msgs))
            if n is not None and len(instances) >= n:
                break
    return instances


# ---------------------------------------------------------------------------
# Quality evaluation core
# ---------------------------------------------------------------------------


def _extract_task_hint(messages: list[dict[str, Any]]) -> str | None:
    for msg in messages:
        if msg.get("role") == "user":
            content = str(msg.get("content", ""))
            if content:
                return content[:500]
    return None


def _identify_modified_segments(
    original: list[dict[str, Any]],
    compressed: list[dict[str, Any]],
) -> list[str]:
    """Return content of segments present in original but absent/changed in compressed.

    Compares by content identity. A segment is "modified" if its content
    does not appear verbatim in the compressed message list.

    Args:
        original: Original normalised message list.
        compressed: Compressed message list.

    Returns:
        List of content strings for modified segments.
    """
    compressed_contents: set[str] = {
        str(m.get("content", "")) for m in compressed
    }
    modified: list[str] = []
    for msg in original:
        content = str(msg.get("content", ""))
        if content and content not in compressed_contents:
            modified.append(content)
    return modified


def _retention_score(
    modified_contents: list[str],
    compressed: list[dict[str, Any]],
    threshold: float = RETENTION_THRESHOLD,
) -> tuple[int, int]:
    """Count how many modified segments have their info retained in compressed context.

    For each modified segment, embeds its content and finds the maximum
    cosine similarity to any segment in the compressed context. If
    max_sim >= threshold, the information is considered retained.

    Args:
        modified_contents: Content strings of dropped/summarized segments.
        compressed: The compressed message list.
        threshold: Cosine similarity threshold for "retained".

    Returns:
        Tuple of (n_retained, n_total_modified).
    """
    if not modified_contents:
        return (0, 0)

    compressed_texts = [str(m.get("content", "")) for m in compressed if m.get("content")]
    if not compressed_texts:
        return (0, len(modified_contents))

    # Batch encode both sets
    all_texts = modified_contents + compressed_texts
    all_embeddings = _model.encode(all_texts, normalize_embeddings=True)

    n_mod = len(modified_contents)
    mod_embeddings = all_embeddings[:n_mod]
    comp_embeddings = all_embeddings[n_mod:]

    # For each modified segment, find max cosine similarity to any compressed segment
    retained = 0
    for mod_emb in mod_embeddings:
        sims = np.dot(comp_embeddings, mod_emb)
        max_sim = float(np.max(sims)) if len(sims) > 0 else 0.0
        if max_sim >= threshold:
            retained += 1

    return (retained, n_mod)


def evaluate_quality(
    instance_id: str,
    messages: list[dict[str, Any]],
    config: CompressionConfig,
) -> InstanceQuality:
    """Run compression and measure information retention for one instance."""
    t0 = time.perf_counter()
    try:
        task_hint = _extract_task_hint(messages)
        result = compress(messages, config, task_hint=task_hint)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Compare original vs compressed to find modified segments
        # Normalize both to plain str content for comparison
        orig_contents = [str(m.get("content", "")) for m in _normalise_messages(messages)]
        comp_contents = {str(m.get("content", "")) for m in _normalise_messages(result.messages)}

        # A segment is "modified" if its exact content is no longer in the compressed set
        # AND it had non-trivial content (>20 chars)
        modified: list[str] = [
            c for c in orig_contents
            if c not in comp_contents and len(c) > 20
        ]
        retained, total_modified = _retention_score(modified, _normalise_messages(result.messages))

        retention_rate = retained / total_modified if total_modified > 0 else 1.0

        original_tokens = result.original_tokens
        compressed_tokens = result.compressed_tokens
        reduction_pct = (
            (result.tokens_saved / original_tokens * 100.0)
            if original_tokens > 0 else 0.0
        )

        return InstanceQuality(
            instance_id=instance_id,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            reduction_pct=reduction_pct,
            segments_modified=total_modified,
            segments_retained=retained,
            retention_rate=retention_rate,
            elapsed_ms=elapsed_ms,
        )

    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return InstanceQuality(
            instance_id=instance_id,
            original_tokens=0,
            compressed_tokens=0,
            reduction_pct=0.0,
            segments_modified=0,
            segments_retained=0,
            retention_rate=0.0,
            elapsed_ms=elapsed_ms,
            skipped=True,
            skip_reason=str(exc),
        )


def run_quality_eval(
    instances: list[tuple[str, list[dict[str, Any]]]],
    strategy: CompressionStrategy,
    show_progress: bool = True,
) -> list[InstanceQuality]:
    config = CompressionConfig(
        strategy=strategy,
        target_reduction_pct={
            CompressionStrategy.CONSERVATIVE: 0.20,
            CompressionStrategy.MODERATE: 0.35,
            CompressionStrategy.AGGRESSIVE: 0.55,
        }[strategy],
        min_turns_protected=0,
        protect_system_prompt=True,
        shadow_mode=False,
    )
    results = []
    for i, (instance_id, messages) in enumerate(instances, start=1):
        if show_progress and i % 5 == 0:
            print(f"  Progress: {i}/{len(instances)}...", file=sys.stderr)
        results.append(evaluate_quality(instance_id, messages, config))
    return results


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_v) - 1)
    return sorted_v[lo] + (k - lo) * (sorted_v[hi] - sorted_v[lo])


def compute_aggregate_quality(results: list[InstanceQuality]) -> AggregateStats:
    valid = [r for r in results if not r.skipped]
    n_skipped = sum(1 for r in results if r.skipped)

    if not valid:
        return AggregateStats(
            n_instances=len(results), n_skipped=n_skipped,
            mean_reduction_pct=0.0, aggregate_reduction_pct=0.0,
            mean_retention_rate=0.0,
            p10_retention_rate=0.0, p50_retention_rate=0.0, p90_retention_rate=0.0,
            total_segments_modified=0, total_segments_retained=0,
            overall_retention_rate=0.0,
        )

    total_orig = sum(r.original_tokens for r in valid)
    total_comp = sum(r.compressed_tokens for r in valid)
    total_saved = total_orig - total_comp
    total_mod = sum(r.segments_modified for r in valid)
    total_ret = sum(r.segments_retained for r in valid)
    retention_rates = [r.retention_rate for r in valid]

    return AggregateStats(
        n_instances=len(results),
        n_skipped=n_skipped,
        mean_reduction_pct=sum(r.reduction_pct for r in valid) / len(valid),
        aggregate_reduction_pct=total_saved / total_orig * 100.0 if total_orig > 0 else 0.0,
        mean_retention_rate=sum(retention_rates) / len(retention_rates),
        p10_retention_rate=_pct(retention_rates, 10.0),
        p50_retention_rate=_pct(retention_rates, 50.0),
        p90_retention_rate=_pct(retention_rates, 90.0),
        total_segments_modified=total_mod,
        total_segments_retained=total_ret,
        overall_retention_rate=total_ret / total_mod if total_mod > 0 else 1.0,
    )


@dataclass
class AggregateStats:
    n_instances: int
    n_skipped: int
    mean_reduction_pct: float
    aggregate_reduction_pct: float
    mean_retention_rate: float
    p10_retention_rate: float
    p50_retention_rate: float
    p90_retention_rate: float
    total_segments_modified: int
    total_segments_retained: int
    overall_retention_rate: float


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _fmt_pct(v: float) -> str:
    return f"{v:.1f}%"


def print_results(
    results: list[InstanceQuality],
    agg: AggregateStats,
    strategy: CompressionStrategy,
    threshold: float,
) -> None:
    print(f"\nTraject Compression Quality Evaluation — {strategy.value} (threshold={threshold})\n")
    header = f"{'Instance':<40} {'Reduction':>10} {'Modified':>9} {'Retained':>9} {'Retention':>10} {'ms':>6}"
    print(header)
    print("-" * len(header))
    for r in results:
        if r.skipped:
            print(f"{'SKIP: ' + r.instance_id:<40} {'—':>10} {'—':>9} {'—':>9} {r.skip_reason[:10]:>10}")
        else:
            ret_str = _fmt_pct(r.retention_rate * 100) if r.segments_modified > 0 else "n/a"
            print(
                f"{r.instance_id:<40} {_fmt_pct(r.reduction_pct):>10} "
                f"{r.segments_modified:>9} {r.segments_retained:>9} "
                f"{ret_str:>10} {r.elapsed_ms:>6.0f}"
            )

    print(f"\n{'─' * 70}")
    print(f"Instances evaluated    : {agg.n_instances - agg.n_skipped} ({agg.n_skipped} skipped)")
    print(f"Aggregate token reduction : {_fmt_pct(agg.aggregate_reduction_pct)}")
    print(f"Mean reduction         : {_fmt_pct(agg.mean_reduction_pct)}")
    print(f"─")
    print(f"Segments modified      : {agg.total_segments_modified:,}")
    print(f"Segments retained      : {agg.total_segments_retained:,}  (sim >= {threshold})")
    print(f"Overall retention rate : {_fmt_pct(agg.overall_retention_rate * 100)}")
    print(f"Mean retention rate    : {_fmt_pct(agg.mean_retention_rate * 100)}")
    print(f"p10 retention rate     : {_fmt_pct(agg.p10_retention_rate * 100)}  (worst 10% of instances)")
    print(f"p50 retention rate     : {_fmt_pct(agg.p50_retention_rate * 100)}")
    print(f"p90 retention rate     : {_fmt_pct(agg.p90_retention_rate * 100)}")

    # Verdict
    print(f"\n{'─' * 70}")
    rate = agg.overall_retention_rate
    if agg.total_segments_modified == 0:
        print("RESULT: No segments were modified — no quality risk.")
    elif rate >= 0.95:
        print(f"RESULT: ✓ HIGH quality ({_fmt_pct(rate * 100)} retention). "
              f"Compression is safe at {_fmt_pct(agg.aggregate_reduction_pct)} reduction.")
    elif rate >= 0.85:
        print(f"RESULT: ✓ ACCEPTABLE quality ({_fmt_pct(rate * 100)} retention). "
              f"Monitor p10 instances for edge cases.")
    elif rate >= 0.70:
        print(f"RESULT: ⚠ MARGINAL quality ({_fmt_pct(rate * 100)} retention). "
              f"Consider reducing strategy aggressiveness.")
    else:
        print(f"RESULT: ✗ LOW quality ({_fmt_pct(rate * 100)} retention). "
              f"Information loss too high for this strategy.")
    print()


def write_json(
    results: list[InstanceQuality],
    agg: AggregateStats,
    path: Path,
    strategy: CompressionStrategy,
    threshold: float,
) -> None:
    payload: dict[str, Any] = {
        "metadata": {"strategy": strategy.value, "retention_threshold": threshold},
        "aggregate": {
            "n_instances": agg.n_instances,
            "n_skipped": agg.n_skipped,
            "aggregate_reduction_pct": round(agg.aggregate_reduction_pct, 4),
            "mean_reduction_pct": round(agg.mean_reduction_pct, 4),
            "overall_retention_rate": round(agg.overall_retention_rate, 4),
            "mean_retention_rate": round(agg.mean_retention_rate, 4),
            "p10_retention_rate": round(agg.p10_retention_rate, 4),
            "p50_retention_rate": round(agg.p50_retention_rate, 4),
            "p90_retention_rate": round(agg.p90_retention_rate, 4),
            "total_segments_modified": agg.total_segments_modified,
            "total_segments_retained": agg.total_segments_retained,
        },
        "instances": [
            {
                "instance_id": r.instance_id,
                "reduction_pct": round(r.reduction_pct, 4),
                "segments_modified": r.segments_modified,
                "segments_retained": r.segments_retained,
                "retention_rate": round(r.retention_rate, 4),
                "elapsed_ms": round(r.elapsed_ms, 2),
                "skipped": r.skipped,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2))
    print(f"Results written to: {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", type=Path, required=True, metavar="FILE")
    parser.add_argument("--n-instances", "-n", type=int, default=None, metavar="N")
    parser.add_argument(
        "--strategy", "-s",
        choices=["conservative", "moderate", "aggressive"],
        default="conservative",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float,
        default=RETENTION_THRESHOLD,
        help=f"Cosine similarity threshold for 'retained' (default: {RETENTION_THRESHOLD})",
    )
    parser.add_argument("--output-json", "-o", type=Path, default=None, metavar="FILE")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args()

    strategy = CompressionStrategy(args.strategy)
    instances = load_trajectories(args.input, args.n_instances)
    if not instances:
        print("ERROR: No valid instances found.", file=sys.stderr)
        sys.exit(1)

    print(
        f"Running quality eval: {strategy.value} on {len(instances)} instances "
        f"(retention threshold={args.threshold})...",
        file=sys.stderr,
    )
    results = run_quality_eval(instances, strategy, show_progress=not args.no_progress)
    agg = compute_aggregate_quality(results)
    print_results(results, agg, strategy, args.threshold)
    if args.output_json:
        write_json(results, agg, args.output_json, strategy, args.threshold)


if __name__ == "__main__":
    main()
