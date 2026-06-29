#!/usr/bin/env python3
"""Traject compression quality evaluator — independent fact-preservation analysis.

This evaluator answers one question honestly: **when compression drops or
summarizes context, does it lose load-bearing information the agent needs?**

Why this rewrite
----------------
The previous version measured "information retention" as the cosine similarity
(``all-MiniLM-L6-v2``) between a dropped segment and the nearest surviving
segment — using the *same* embedding model that drives the compression
decision. That is circular: the engine drops a segment precisely because the
model judged it low-relevance / similar to what remains, so the metric is
almost guaranteed to report high "retention." It measures the model against
itself, not whether the agent's task-critical facts survived.

This version uses an **independent, deterministic** signal: it extracts the
concrete, non-reconstructable facts from the original context (file:line
references, exception types, test names, ``Class.method`` identifiers, git
SHAs, URLs) using literal pattern extraction — which has nothing to do with the
embedding scorer — and checks whether each fact still appears *verbatim* in the
compressed context. No embedding model, no network, fully reproducible.

It reports two rates:

* **Fact preservation** — fraction of all critical facts still present.
* **At-risk fact preservation** — restricted to facts whose every occurrence
  was in a segment that compression actually modified. This is the adversarial
  worst case: it only credits compression for facts it could have lost but
  carried through (e.g. preserved inside a summary).

Config honesty
--------------
By default the evaluator runs the **shipped** strategy config from
``STRATEGY_DEFAULTS`` (so ``min_turns_protected`` is the real production value,
not 0). ``shadow_mode`` is forced off *only* so the compressed output can be
observed — no provider calls are made. Pass ``--unprotected`` to reproduce the
old benchmark-only configuration (``min_turns_protected=0``) for comparison.

Usage
-----
::

    python examples/benchmark/quality_eval.py --input trajectories.jsonl
    python examples/benchmark/quality_eval.py --input trajectories.jsonl --strategy moderate
    python examples/benchmark/quality_eval.py --input trajectories.jsonl --unprotected
    python examples/benchmark/quality_eval.py --input trajectories.jsonl --output-json q.json

No live LLM calls are made.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

try:
    from traject.compression.engine import compress
    from traject.compression.strategies import (
        CompressionConfig,
        CompressionStrategy,
        get_config,
    )
except ImportError as exc:
    print(f"ERROR: Traject SDK not found ({exc}).", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Independent critical-fact extraction
#
# These patterns capture concrete, non-reconstructable facts. They are
# deliberately independent of the embedding model that drives compression
# decisions, so the resulting metric is not circular. Matches use no capture
# groups, so ``findall`` returns whole matches.
# ---------------------------------------------------------------------------

_FACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[\w./\\-]+\.(?:py|js|ts|go|rs|java|c|cpp|h|rb|sh):\d+"),  # file:line
    re.compile(r'File "[^"]+", line \d+'),                                # traceback frame
    re.compile(r"\b[A-Za-z_]*(?:Error|Exception)\b"),                     # error / exception types
    re.compile(r"\btest_[A-Za-z0-9_]+"),                                  # test names
    re.compile(r"\b[A-Z][A-Za-z0-9_]+\.[a-z_][A-Za-z0-9_]+"),            # Class.method
    re.compile(r"\b[0-9a-f]{7,40}\b"),                                    # git sha-like
    re.compile(r"https?://[^\s\"')]+"),                                   # urls
]

_TOOL_OBS_MARKERS = (
    "OBSERVATION:", "observation:", "EXECUTION RESULT", "stdout:", "stderr:",
    "exit code:", "$ ", "bash-", "[Command output]",
)


def extract_critical_facts(messages: list[dict[str, Any]]) -> set[str]:
    """Return the set of load-bearing facts present in *messages*.

    Independent of the compression scorer: uses literal pattern extraction.
    """
    facts: set[str] = set()
    for msg in messages:
        content = str(msg.get("content", ""))
        if not content:
            continue
        for pat in _FACT_PATTERNS:
            for match in pat.findall(content):
                if len(match) >= 4:
                    facts.add(match)
    return facts


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
    n_facts: int                  # total critical facts in the original
    facts_preserved: int          # still present verbatim in compressed context
    preservation_rate: float      # facts_preserved / n_facts (1.0 if no facts)
    n_facts_at_risk: int          # facts whose every occurrence was modified
    facts_at_risk_preserved: int  # of those, how many survived anyway
    at_risk_preservation_rate: float
    elapsed_ms: float
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class AggregateStats:
    n_instances: int
    n_skipped: int
    mean_reduction_pct: float
    aggregate_reduction_pct: float
    overall_preservation_rate: float
    mean_preservation_rate: float
    p10_preservation_rate: float
    p50_preservation_rate: float
    total_facts: int
    total_facts_preserved: int
    total_facts_at_risk: int
    total_facts_at_risk_preserved: int
    at_risk_preservation_rate: float


# ---------------------------------------------------------------------------
# Trajectory loading
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


def load_trajectories(
    path: Path, n: int | None
) -> list[tuple[str, list[dict[str, Any]], list[str] | None]]:
    """Load ``(instance_id, messages, ground_truth_facts)`` tuples.

    ``ground_truth_facts`` is populated from a ``critical_facts`` key when the
    dataset provides one (annotated corpora); otherwise ``None`` and facts are
    extracted from the context.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    instances: list[tuple[str, list[dict[str, Any]], list[str] | None]] = []
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
            if not msgs:
                continue
            gt = record.get("critical_facts")
            gt_list = [str(x) for x in gt] if isinstance(gt, list) else None
            instances.append((instance_id, msgs, gt_list))
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


def _measure(
    original: list[dict[str, Any]],
    compressed: list[dict[str, Any]],
    ground_truth: list[str] | None,
) -> tuple[int, int, int, int]:
    """Return (n_facts, preserved, n_at_risk, at_risk_preserved).

    A fact is *preserved* if it appears verbatim anywhere in the concatenated
    compressed context. A fact is *at risk* if every original segment that
    contained it was modified (i.e. not carried through verbatim). At-risk
    facts that still survive (e.g. inside a summary) are credited.
    """
    orig_contents = [str(m.get("content", "")) for m in original]
    facts: set[str] = set(ground_truth) if ground_truth else extract_critical_facts(original)
    facts = {f for f in facts if any(f in c for c in orig_contents)}
    if not facts:
        return (0, 0, 0, 0)

    compressed_contents = [str(m.get("content", "")) for m in compressed]
    compressed_blob = "\n".join(compressed_contents)
    surviving_verbatim = set(compressed_contents)

    preserved = at_risk = at_risk_preserved = 0
    for fact in facts:
        is_present = fact in compressed_blob
        if is_present:
            preserved += 1
        # "at risk" = no original segment that contained this fact survived verbatim
        carried_verbatim = any(
            fact in content and content in surviving_verbatim for content in orig_contents
        )
        if not carried_verbatim:
            at_risk += 1
            if is_present:
                at_risk_preserved += 1
    return (len(facts), preserved, at_risk, at_risk_preserved)


def evaluate_quality(
    instance_id: str,
    messages: list[dict[str, Any]],
    config: CompressionConfig,
    ground_truth: list[str] | None,
) -> InstanceQuality:
    """Run compression and measure fact preservation for one instance."""
    t0 = time.perf_counter()
    try:
        normalized = _normalise_messages(messages)
        task_hint = _extract_task_hint(normalized)
        result = compress(normalized, config, task_hint=task_hint)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        compressed = _normalise_messages(result.messages)
        n_facts, preserved, n_at_risk, at_risk_preserved = _measure(
            normalized, compressed, ground_truth
        )

        reduction_pct = (
            (result.tokens_saved / result.original_tokens * 100.0)
            if result.original_tokens > 0 else 0.0
        )
        return InstanceQuality(
            instance_id=instance_id,
            original_tokens=result.original_tokens,
            compressed_tokens=result.compressed_tokens,
            reduction_pct=reduction_pct,
            n_facts=n_facts,
            facts_preserved=preserved,
            preservation_rate=(preserved / n_facts) if n_facts > 0 else 1.0,
            n_facts_at_risk=n_at_risk,
            facts_at_risk_preserved=at_risk_preserved,
            at_risk_preservation_rate=(at_risk_preserved / n_at_risk) if n_at_risk > 0 else 1.0,
            elapsed_ms=elapsed_ms,
        )
    except Exception as exc:  # noqa: BLE001 — evaluation must never crash
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return InstanceQuality(
            instance_id=instance_id, original_tokens=0, compressed_tokens=0,
            reduction_pct=0.0, n_facts=0, facts_preserved=0, preservation_rate=0.0,
            n_facts_at_risk=0, facts_at_risk_preserved=0, at_risk_preservation_rate=0.0,
            elapsed_ms=elapsed_ms, skipped=True, skip_reason=str(exc),
        )


def build_config(strategy: CompressionStrategy, unprotected: bool) -> CompressionConfig:
    """Return the config to benchmark.

    Defaults to the shipped strategy config with ``shadow_mode`` forced off so
    the compressed output can be observed (no provider calls are made). When
    *unprotected* is True, reproduces the legacy benchmark-only config that
    disabled recent-turn protection (``min_turns_protected=0``).
    """
    cfg = replace(get_config(strategy), shadow_mode=False)
    if unprotected:
        cfg = replace(cfg, min_turns_protected=0)
    return cfg


def run_quality_eval(
    instances: list[tuple[str, list[dict[str, Any]], list[str] | None]],
    config: CompressionConfig,
    show_progress: bool = True,
) -> list[InstanceQuality]:
    results: list[InstanceQuality] = []
    for i, (instance_id, messages, gt) in enumerate(instances, start=1):
        if show_progress and i % 5 == 0:
            print(f"  Progress: {i}/{len(instances)}...", file=sys.stderr)
        results.append(evaluate_quality(instance_id, messages, config, gt))
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
            overall_preservation_rate=0.0, mean_preservation_rate=0.0,
            p10_preservation_rate=0.0, p50_preservation_rate=0.0,
            total_facts=0, total_facts_preserved=0,
            total_facts_at_risk=0, total_facts_at_risk_preserved=0,
            at_risk_preservation_rate=0.0,
        )

    total_orig = sum(r.original_tokens for r in valid)
    total_comp = sum(r.compressed_tokens for r in valid)
    total_facts = sum(r.n_facts for r in valid)
    total_preserved = sum(r.facts_preserved for r in valid)
    total_at_risk = sum(r.n_facts_at_risk for r in valid)
    total_at_risk_preserved = sum(r.facts_at_risk_preserved for r in valid)
    pres_rates = [r.preservation_rate for r in valid]

    return AggregateStats(
        n_instances=len(results),
        n_skipped=n_skipped,
        mean_reduction_pct=sum(r.reduction_pct for r in valid) / len(valid),
        aggregate_reduction_pct=(total_orig - total_comp) / total_orig * 100.0 if total_orig > 0 else 0.0,
        overall_preservation_rate=total_preserved / total_facts if total_facts > 0 else 1.0,
        mean_preservation_rate=sum(pres_rates) / len(pres_rates),
        p10_preservation_rate=_pct(pres_rates, 10.0),
        p50_preservation_rate=_pct(pres_rates, 50.0),
        total_facts=total_facts,
        total_facts_preserved=total_preserved,
        total_facts_at_risk=total_at_risk,
        total_facts_at_risk_preserved=total_at_risk_preserved,
        at_risk_preservation_rate=total_at_risk_preserved / total_at_risk if total_at_risk > 0 else 1.0,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _fmt_pct(v: float) -> str:
    return f"{v:.1f}%"


def print_results(
    results: list[InstanceQuality],
    agg: AggregateStats,
    config: CompressionConfig,
) -> None:
    print(
        f"\nTraject Compression Quality — {config.strategy.value} "
        f"(min_turns_protected={config.min_turns_protected}, "
        f"target={config.target_reduction_pct:.0%})\n"
    )
    print("Metric: independent critical-fact preservation (no embedding model).\n")
    header = (
        f"{'Instance':<34} {'Reduction':>10} {'Facts':>6} {'Kept':>6} "
        f"{'Preserve':>9} {'AtRisk':>7} {'ms':>6}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        if r.skipped:
            print(f"{'SKIP: ' + r.instance_id:<34} {r.skip_reason[:40]}")
            continue
        pres = _fmt_pct(r.preservation_rate * 100) if r.n_facts else "n/a"
        atr = _fmt_pct(r.at_risk_preservation_rate * 100) if r.n_facts_at_risk else "n/a"
        print(
            f"{r.instance_id:<34} {_fmt_pct(r.reduction_pct):>10} "
            f"{r.n_facts:>6} {r.facts_preserved:>6} {pres:>9} {atr:>7} {r.elapsed_ms:>6.0f}"
        )

    print(f"\n{'─' * 78}")
    print(f"Instances evaluated       : {agg.n_instances - agg.n_skipped} ({agg.n_skipped} skipped)")
    print(f"Aggregate token reduction : {_fmt_pct(agg.aggregate_reduction_pct)}")
    print(f"Mean token reduction      : {_fmt_pct(agg.mean_reduction_pct)}")
    print("─")
    print(f"Critical facts (total)    : {agg.total_facts:,}")
    print(f"Facts preserved           : {agg.total_facts_preserved:,}")
    print(f"Fact preservation rate    : {_fmt_pct(agg.overall_preservation_rate * 100)}  (independent metric)")
    print(f"  mean / p50 / p10        : {_fmt_pct(agg.mean_preservation_rate*100)} / "
          f"{_fmt_pct(agg.p50_preservation_rate*100)} / {_fmt_pct(agg.p10_preservation_rate*100)}")
    print(f"At-risk facts             : {agg.total_facts_at_risk:,}  "
          f"(every occurrence was modified)")
    print(f"At-risk facts preserved   : {agg.total_facts_at_risk_preserved:,}  "
          f"({_fmt_pct(agg.at_risk_preservation_rate * 100)})  <- adversarial worst case")

    print(f"\n{'─' * 78}")
    rate = agg.overall_preservation_rate
    if agg.total_facts == 0:
        print("RESULT: No critical facts detected — cannot assess quality on this corpus.")
    elif agg.aggregate_reduction_pct < 1.0:
        print(f"RESULT: ⚠ Compression is ~inert here ({_fmt_pct(agg.aggregate_reduction_pct)} "
              f"reduction). Fact preservation {_fmt_pct(rate*100)} is trivially high — "
              f"nothing was dropped.")
    elif rate >= 0.98:
        print(f"RESULT: ✓ HIGH quality ({_fmt_pct(rate*100)} fact preservation) at "
              f"{_fmt_pct(agg.aggregate_reduction_pct)} reduction.")
    elif rate >= 0.90:
        print(f"RESULT: ✓ ACCEPTABLE ({_fmt_pct(rate*100)} fact preservation) at "
              f"{_fmt_pct(agg.aggregate_reduction_pct)} reduction. Watch at-risk facts.")
    else:
        print(f"RESULT: ✗ Information loss too high ({_fmt_pct(rate*100)} fact preservation) "
              f"for {_fmt_pct(agg.aggregate_reduction_pct)} reduction.")
    print()


def write_json(
    results: list[InstanceQuality],
    agg: AggregateStats,
    path: Path,
    config: CompressionConfig,
) -> None:
    payload: dict[str, Any] = {
        "metadata": {
            "strategy": config.strategy.value,
            "min_turns_protected": config.min_turns_protected,
            "target_reduction_pct": config.target_reduction_pct,
            "shadow_mode": config.shadow_mode,
            "metric": "independent_fact_preservation",
        },
        "aggregate": {
            "n_instances": agg.n_instances,
            "n_skipped": agg.n_skipped,
            "aggregate_reduction_pct": round(agg.aggregate_reduction_pct, 4),
            "mean_reduction_pct": round(agg.mean_reduction_pct, 4),
            "overall_preservation_rate": round(agg.overall_preservation_rate, 4),
            "mean_preservation_rate": round(agg.mean_preservation_rate, 4),
            "p10_preservation_rate": round(agg.p10_preservation_rate, 4),
            "p50_preservation_rate": round(agg.p50_preservation_rate, 4),
            "total_facts": agg.total_facts,
            "total_facts_preserved": agg.total_facts_preserved,
            "total_facts_at_risk": agg.total_facts_at_risk,
            "total_facts_at_risk_preserved": agg.total_facts_at_risk_preserved,
            "at_risk_preservation_rate": round(agg.at_risk_preservation_rate, 4),
        },
        "instances": [
            {
                "instance_id": r.instance_id,
                "reduction_pct": round(r.reduction_pct, 4),
                "n_facts": r.n_facts,
                "facts_preserved": r.facts_preserved,
                "preservation_rate": round(r.preservation_rate, 4),
                "n_facts_at_risk": r.n_facts_at_risk,
                "at_risk_preservation_rate": round(r.at_risk_preservation_rate, 4),
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
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", "-i", type=Path, required=True, metavar="FILE")
    parser.add_argument("--n-instances", "-n", type=int, default=None, metavar="N")
    parser.add_argument(
        "--strategy", "-s",
        choices=["conservative", "moderate", "aggressive"],
        default="conservative",
    )
    parser.add_argument(
        "--unprotected", action="store_true",
        help="Reproduce the legacy benchmark-only config (min_turns_protected=0).",
    )
    parser.add_argument("--output-json", "-o", type=Path, default=None, metavar="FILE")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args()

    strategy = CompressionStrategy(args.strategy)
    config = build_config(strategy, args.unprotected)
    instances = load_trajectories(args.input, args.n_instances)
    if not instances:
        print("ERROR: No valid instances found.", file=sys.stderr)
        sys.exit(1)

    print(
        f"Running quality eval: {strategy.value} on {len(instances)} instances "
        f"(min_turns_protected={config.min_turns_protected})...",
        file=sys.stderr,
    )
    results = run_quality_eval(instances, config, show_progress=not args.no_progress)
    agg = compute_aggregate_quality(results)
    print_results(results, agg, config)
    if args.output_json:
        write_json(results, agg, args.output_json, config)


if __name__ == "__main__":
    main()
