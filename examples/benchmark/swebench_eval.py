#!/usr/bin/env python3
"""SWE-bench trajectory compression evaluator.

Runs Traject's compression engine (CONSERVATIVE strategy, shadow mode) over
SWE-bench agent trajectory files and reports per-instance and aggregate token
reduction statistics. No live LLM calls are made — only existing trajectory
files are analysed.

Supported input formats
-----------------------
The script accepts JSONL files where each line is one of:

1. **Standard chat format** (SWE-Gym, SWE-agent ``messages`` key)::

       {"instance_id": "...", "messages": [{"role": "...", "content": "..."}]}

2. **SWE-agent ``query`` key format**::

       {"instance_id": "...", "query": [{"role": "...", "content": "..."}]}

3. **Flat trajectory format** (thought/action/observation turns)::

       {"instance_id": "...", "history": [{"role": "...", "content": "..."}]}

4. **HuggingFace SWE-bench Verified** — plain JSON lines with any of the
   keys above, optionally wrapped in a ``{"data": {...}}`` envelope.

Lines that cannot be parsed or contain no messages are skipped with a warning.

Usage
-----
::

    # Evaluate all trajectories in a JSONL file
    python examples/benchmark/swebench_eval.py --input trajectories.jsonl

    # Evaluate the first 50 instances only
    python examples/benchmark/swebench_eval.py --input trajectories.jsonl --n-instances 50

    # Use MODERATE strategy instead of CONSERVATIVE
    python examples/benchmark/swebench_eval.py --input trajectories.jsonl --strategy moderate

    # Output results as JSON for downstream processing
    python examples/benchmark/swebench_eval.py --input trajectories.jsonl --output-json results.json

Downloading SWE-bench trajectories
-----------------------------------
The SWE-Gym project publishes agent trajectories on HuggingFace::

    pip install datasets huggingface_hub
    python - << 'EOF'
    from datasets import load_dataset
    ds = load_dataset("SWE-Gym/SWE-Gym", split="train")
    ds.to_json("trajectories.jsonl")
    EOF

Or use any SWE-agent ``.traj`` file converted to JSONL, or the
``princeton-nlp/SWE-bench_Verified`` dataset with recorded trajectories.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Traject imports — must be installed: pip install -e "sdk/python[dev]"
# ---------------------------------------------------------------------------
try:
    from traject.compression.engine import compress
    from traject.compression.strategies import (
        CompressionConfig,
        CompressionStrategy,
        get_config,
    )
except ImportError as exc:
    print(
        f"ERROR: Traject SDK not found ({exc}).\n"
        "Install with: pip install -e 'sdk/python[dev]' from the repo root.",
        file=sys.stderr,
    )
    sys.exit(1)

# Optional rich for pretty tables — fall back to plain text if not installed.
try:
    from rich.console import Console
    from rich.table import Table

    _RICH_AVAILABLE = True
    _console = Console()
except ImportError:
    _RICH_AVAILABLE = False
    _console = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class InstanceResult:
    """Compression result for a single SWE-bench trajectory instance.

    Attributes:
        instance_id: The SWE-bench instance identifier.
        original_tokens: Total token count before compression.
        compressed_tokens: Token count after compression decisions.
        tokens_saved: Tokens that would be saved (shadow mode).
        reduction_pct: Percentage reduction (0.0–100.0).
        n_turns: Number of conversational turns in the trajectory.
        segments_soft_protected: Segments elevated to the soft-protect tier.
        elapsed_ms: Time taken to run the compression pipeline (ms).
        skipped: True when the instance could not be processed.
        skip_reason: Human-readable reason for skipping.
    """

    instance_id: str
    original_tokens: int
    compressed_tokens: int
    tokens_saved: int
    reduction_pct: float
    n_turns: int
    segments_soft_protected: int
    elapsed_ms: float
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class AggregateStats:
    """Aggregate statistics across all evaluated instances."""

    n_instances: int
    n_skipped: int
    total_original_tokens: int
    total_compressed_tokens: int
    total_tokens_saved: int
    aggregate_reduction_pct: float
    mean_reduction_pct: float
    p50_reduction_pct: float
    p95_reduction_pct: float
    mean_elapsed_ms: float
    total_soft_protected_segments: int


# ---------------------------------------------------------------------------
# Trajectory loading
# ---------------------------------------------------------------------------

_MESSAGE_KEYS = ("messages", "query", "history", "conversation", "turns")


def _extract_messages(record: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Extract a list of chat messages from a trajectory record.

    Tries several common key names used across SWE-bench datasets and
    agent frameworks.

    Args:
        record: A parsed JSON object from one line of the JSONL file.

    Returns:
        A list of ``{"role": ..., "content": ...}`` dicts, or ``None``
        when no recognized message structure can be extracted.
    """
    # Unwrap HuggingFace-style envelope
    if "data" in record and isinstance(record["data"], dict):
        record = record["data"]

    # Try known message list keys
    for key in _MESSAGE_KEYS:
        value = record.get(key)
        if isinstance(value, list) and len(value) > 0:
            # Validate that elements look like chat messages
            if isinstance(value[0], dict) and (
                "role" in value[0] or "content" in value[0]
            ):
                return _normalise_messages(value)

    # SWE-agent flat format: top-level "system", "user", "assistant" strings
    if "system" in record and isinstance(record.get("system"), str):
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": record["system"]}
        ]
        for turn in record.get("interactions", []):
            if isinstance(turn, dict):
                role = turn.get("role", "user")
                content = turn.get("content", turn.get("message", ""))
                msgs.append({"role": role, "content": str(content)})
        if len(msgs) > 1:
            return msgs

    return None


def _normalise_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalise messages to plain ``{"role": str, "content": str}`` format.

    Handles content lists (Anthropic style) and tool_call role variants.

    SWE-bench datasets often encode tool observations as ``role="user"``
    messages. These are detected by content patterns (OBSERVATION:, stdout,
    stderr, exit code, bash output markers) and remapped to ``role="tool"``
    so Traject's classifier can identify them as TOOL_RESULT artifacts and
    apply compression decisions correctly.

    Args:
        messages: Raw message list from the trajectory file.

    Returns:
        Normalised list of ``{"role": str, "content": str}`` dicts.
    """
    # Markers that indicate a "user" message is actually a tool observation
    _TOOL_OBS_MARKERS = (
        "OBSERVATION:",
        "observation:",
        "EXECUTION RESULT",
        "execution result",
        "stdout:",
        "stderr:",
        "exit code:",
        "$ ",
        "bash-",
        "[Command output]",
        "Command output:",
        "Tool response:",
        "Function output:",
    )

    normalised: list[dict[str, Any]] = []
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        role: str = str(msg.get("role", "user"))
        content = msg.get("content", "")

        # Content may be a list of blocks (Anthropic / tool result format)
        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(str(block.get("text", "")))
                    elif "text" in block:
                        text_parts.append(str(block["text"]))
                elif isinstance(block, str):
                    text_parts.append(block)
            content = " ".join(text_parts)
        else:
            content = str(content)

        # Map tool/function roles to "tool" for Traject's classifier
        if role in ("function", "ipython", "observation"):
            role = "tool"

        # SWE-bench specific: user messages that are actually tool observations.
        # Detected by: appears after an assistant message AND content starts
        # with an observation marker.
        if role == "user" and i > 0:
            prev_role = str(messages[i - 1].get("role", ""))
            if prev_role == "assistant":
                content_start = content.lstrip()[:80].lower()
                if any(m.lower() in content_start for m in _TOOL_OBS_MARKERS):
                    role = "tool"

        normalised.append({"role": role, "content": content})
    return normalised


def load_trajectories(
    path: Path,
    n_instances: int | None = None,
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Load trajectory instances from a JSONL file.

    Args:
        path: Path to the JSONL file.
        n_instances: Maximum number of instances to load. ``None`` loads all.

    Returns:
        List of ``(instance_id, messages)`` tuples.

    Raises:
        FileNotFoundError: If *path* does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Trajectory file not found: {path}\n"
            "See the module docstring for download instructions."
        )

    instances: list[tuple[str, list[dict[str, Any]]]] = []
    skipped = 0

    with path.open("r", encoding="utf-8") as fh:
        for line_num, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                record: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError as exc:
                print(
                    f"  WARNING: line {line_num}: JSON parse error ({exc}) — skipped.",
                    file=sys.stderr,
                )
                skipped += 1
                continue

            instance_id: str = str(
                record.get("instance_id")
                or record.get("id")
                or record.get("name")
                or f"line_{line_num}"
            )

            messages = _extract_messages(record)
            if messages is None or len(messages) == 0:
                print(
                    f"  WARNING: {instance_id}: no messages found — skipped.",
                    file=sys.stderr,
                )
                skipped += 1
                continue

            instances.append((instance_id, messages))

            if n_instances is not None and len(instances) >= n_instances:
                break

    if skipped > 0:
        print(
            f"  Loaded {len(instances)} instances ({skipped} skipped).",
            file=sys.stderr,
        )

    return instances


# ---------------------------------------------------------------------------
# Compression evaluation
# ---------------------------------------------------------------------------


def _count_turns(messages: list[dict[str, Any]]) -> int:
    """Return the number of user/assistant turn pairs in the message list."""
    return sum(1 for m in messages if m.get("role") in ("user", "assistant"))


def _assign_agentic_turn_indices(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assign synthetic turn indices for agentic tool-calling trajectories.

    In SWE-bench trajectories, the agent follows a tight loop:
    assistant → tool → assistant → tool → ...
    The standard parser only increments turn_index on user→assistant
    transitions, leaving all segments at turn_index=0 in single-user-turn
    trajectories. This means CONSERVATIVE's ``turns_ago > 3`` threshold
    never fires.

    This function inserts a ``_traject_turn`` field into each message dict
    so the evaluator can pass a pre-processed message list where older
    assistant/tool cycles have higher apparent age. It treats each
    assistant→tool pair as one "step" and counts steps from the end.

    Note: This modifies a copy of the messages list, not the original.

    Args:
        messages: Normalised chat message list.

    Returns:
        A new list of message dicts with ``_traject_turn`` fields added.
        The compression engine does not read this field directly; it is
        used only for diagnostic purposes here. The actual fix is handled
        by the segment parser counting assistant→tool transitions.
    """
    # Count assistant→tool transitions as steps
    step = 0
    steps: list[int] = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "assistant":
            step += 1
        steps.append(step)

    total_steps = max(steps) if steps else 0
    result = []
    for msg, s in zip(messages, steps, strict=False):
        m = dict(msg)
        # Assign turn index = distance from end (older = higher turns_ago)
        m["_traject_turn_from_end"] = total_steps - s
        result.append(m)
    return result


def _extract_task_hint(messages: list[dict[str, Any]]) -> str | None:
    """Extract the issue/task description from the first user message.

    SWE-bench trajectories start with a system prompt followed by a user
    message containing the GitHub issue. Using this as the task hint lets
    the semantic scorer distinguish segments relevant to the active task
    from stale tool results and completed reasoning blocks.

    Args:
        messages: Normalised chat message list.

    Returns:
        The content of the first non-system user message, truncated to
        500 characters for embedding efficiency, or ``None`` when not found.
    """
    for msg in messages:
        if msg.get("role") == "user":
            content = str(msg.get("content", ""))
            if content:
                return content[:500]
    return None
    """Extract the issue/task description from the first user message.

    SWE-bench trajectories start with a system prompt followed by a user
    message containing the GitHub issue. Using this as the task hint lets
    the semantic scorer distinguish segments relevant to the active task
    from stale tool results and completed reasoning blocks.

    Args:
        messages: Normalised chat message list.

    Returns:
        The content of the first non-system user message, truncated to
        500 characters for embedding efficiency, or ``None`` when not found.
    """
    for msg in messages:
        if msg.get("role") == "user":
            content = str(msg.get("content", ""))
            if content:
                return content[:500]
    return None


def evaluate_instance(
    instance_id: str,
    messages: list[dict[str, Any]],
    config: CompressionConfig,
) -> InstanceResult:
    """Run Traject compression on a single trajectory instance.

    Args:
        instance_id: The SWE-bench instance identifier.
        messages: Normalised chat message list for this trajectory.
        config: The :class:`~traject.compression.strategies.CompressionConfig`
            to apply. Must have ``shadow_mode=True`` for analysis-only runs.

    Returns:
        An :class:`InstanceResult` populated with token counts and timings.
    """
    t0 = time.perf_counter()
    try:
        task_hint = _extract_task_hint(messages)
        result = compress(messages, config, task_hint=task_hint)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        reduction_pct = (
            (result.tokens_saved / result.original_tokens * 100.0)
            if result.original_tokens > 0
            else 0.0
        )

        return InstanceResult(
            instance_id=instance_id,
            original_tokens=result.original_tokens,
            compressed_tokens=result.compressed_tokens,
            tokens_saved=result.tokens_saved,
            reduction_pct=reduction_pct,
            n_turns=_count_turns(messages),
            segments_soft_protected=result.segments_soft_protected,
            elapsed_ms=elapsed_ms,
        )

    except Exception as exc:  # noqa: BLE001 — evaluation must never crash
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return InstanceResult(
            instance_id=instance_id,
            original_tokens=0,
            compressed_tokens=0,
            tokens_saved=0,
            reduction_pct=0.0,
            n_turns=0,
            segments_soft_protected=0,
            elapsed_ms=elapsed_ms,
            skipped=True,
            skip_reason=str(exc),
        )


def build_config(
    strategy: CompressionStrategy, unprotected: bool = False
) -> CompressionConfig:
    """Return the config to benchmark.

    Defaults to the **shipped** strategy config from ``STRATEGY_DEFAULTS`` — so
    ``min_turns_protected`` is the real production value (3 for conservative /
    moderate, 2 for aggressive), not 0. ``shadow_mode`` is forced off *only* so
    that the compressed output can be measured; no provider calls are made by
    this offline script.

    When *unprotected* is True the legacy benchmark-only configuration is used
    (``min_turns_protected=0``). That config disables the recent-turn safety
    guarantee that ships by default, so its numbers do **not** describe the
    behaviour a user gets out of the box — it exists only to reproduce and
    contrast with the previously published figures.
    """
    config = replace(get_config(strategy), shadow_mode=False)
    if unprotected:
        config = replace(config, min_turns_protected=0)
    return config


def run_evaluation(
    instances: list[tuple[str, list[dict[str, Any]]]],
    config: CompressionConfig,
    show_progress: bool = True,
) -> list[InstanceResult]:
    """Run compression evaluation across all instances.

    Args:
        instances: List of ``(instance_id, messages)`` tuples from
            :func:`load_trajectories`.
        config: The compression config to apply (see :func:`build_config`).
        show_progress: Print progress to stderr when True.

    Returns:
        List of :class:`InstanceResult` objects, one per instance.
    """
    results: list[InstanceResult] = []
    total = len(instances)

    for i, (instance_id, messages) in enumerate(instances, start=1):
        if show_progress and i % 10 == 0:
            print(f"  Progress: {i}/{total}...", file=sys.stderr)

        result = evaluate_instance(instance_id, messages, config)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    """Return the *pct*-th percentile of *values* (sorted ascending)."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct / 100.0
    lo = int(k)
    hi = lo + 1
    if hi >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[lo] + (k - lo) * (sorted_vals[hi] - sorted_vals[lo])


def compute_aggregate(results: list[InstanceResult]) -> AggregateStats:
    """Compute aggregate statistics from per-instance results.

    Args:
        results: List of :class:`InstanceResult` objects.

    Returns:
        Populated :class:`AggregateStats`.
    """
    valid = [r for r in results if not r.skipped]
    n_skipped = sum(1 for r in results if r.skipped)

    if not valid:
        return AggregateStats(
            n_instances=len(results),
            n_skipped=n_skipped,
            total_original_tokens=0,
            total_compressed_tokens=0,
            total_tokens_saved=0,
            aggregate_reduction_pct=0.0,
            mean_reduction_pct=0.0,
            p50_reduction_pct=0.0,
            p95_reduction_pct=0.0,
            mean_elapsed_ms=0.0,
            total_soft_protected_segments=0,
        )

    total_orig = sum(r.original_tokens for r in valid)
    total_comp = sum(r.compressed_tokens for r in valid)
    total_saved = sum(r.tokens_saved for r in valid)
    reduction_pcts = [r.reduction_pct for r in valid]

    return AggregateStats(
        n_instances=len(results),
        n_skipped=n_skipped,
        total_original_tokens=total_orig,
        total_compressed_tokens=total_comp,
        total_tokens_saved=total_saved,
        aggregate_reduction_pct=(
            total_saved / total_orig * 100.0 if total_orig > 0 else 0.0
        ),
        mean_reduction_pct=sum(reduction_pcts) / len(reduction_pcts),
        p50_reduction_pct=_percentile(reduction_pcts, 50.0),
        p95_reduction_pct=_percentile(reduction_pcts, 95.0),
        mean_elapsed_ms=sum(r.elapsed_ms for r in valid) / len(valid),
        total_soft_protected_segments=sum(
            r.segments_soft_protected for r in valid
        ),
    )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _fmt_pct(v: float) -> str:
    return f"{v:.1f}%"


def _fmt_tokens(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def print_results_rich(
    results: list[InstanceResult],
    agg: AggregateStats,
    strategy: CompressionStrategy,
) -> None:
    """Print a rich table of per-instance and aggregate results."""
    assert _console is not None

    _console.print(
        f"\n[bold]Traject SWE-bench Compression Evaluation[/bold] "
        f"— strategy: [cyan]{strategy.value}[/cyan] (shadow mode)\n"
    )

    table = Table(
        show_header=True,
        header_style="bold dim",
        box=None,
        padding=(0, 1),
    )
    table.add_column("Instance", style="dim", max_width=40)
    table.add_column("Orig tokens", justify="right")
    table.add_column("Comp tokens", justify="right")
    table.add_column("Saved", justify="right")
    table.add_column("Reduction", justify="right")
    table.add_column("Turns", justify="right")
    table.add_column("Soft-prot", justify="right")
    table.add_column("ms", justify="right")

    for r in results:
        if r.skipped:
            table.add_row(
                r.instance_id,
                "—", "—", "—",
                f"[red]SKIP: {r.skip_reason[:30]}[/red]",
                "—", "—", "—",
            )
        else:
            color = (
                "green" if r.reduction_pct >= 10.0
                else "yellow" if r.reduction_pct >= 5.0
                else "white"
            )
            table.add_row(
                r.instance_id,
                _fmt_tokens(r.original_tokens),
                _fmt_tokens(r.compressed_tokens),
                _fmt_tokens(r.tokens_saved),
                f"[{color}]{_fmt_pct(r.reduction_pct)}[/{color}]",
                str(r.n_turns),
                str(r.segments_soft_protected),
                f"{r.elapsed_ms:.0f}",
            )

    _console.print(table)

    # Aggregate summary
    _console.print("\n[bold]Aggregate[/bold]")
    _console.print(f"  Instances evaluated : {agg.n_instances - agg.n_skipped} ({agg.n_skipped} skipped)")
    _console.print(f"  Total original      : {_fmt_tokens(agg.total_original_tokens)} tokens")
    _console.print(f"  Total compressed    : {_fmt_tokens(agg.total_compressed_tokens)} tokens")
    _console.print(f"  Total saved         : {_fmt_tokens(agg.total_tokens_saved)} tokens")
    _console.print(f"  Aggregate reduction : [bold green]{_fmt_pct(agg.aggregate_reduction_pct)}[/bold green]")
    _console.print(f"  Mean reduction      : {_fmt_pct(agg.mean_reduction_pct)}")
    _console.print(f"  p50 reduction       : {_fmt_pct(agg.p50_reduction_pct)}")
    _console.print(f"  p95 reduction       : {_fmt_pct(agg.p95_reduction_pct)}")
    _console.print(f"  Soft-prot segments  : {agg.total_soft_protected_segments:,}")
    _console.print(f"  Mean latency        : {agg.mean_elapsed_ms:.1f} ms/instance\n")


def print_results_plain(
    results: list[InstanceResult],
    agg: AggregateStats,
    strategy: CompressionStrategy,
) -> None:
    """Print plain-text results when rich is not available."""
    print(f"\nTraject SWE-bench Compression Evaluation — {strategy.value} (shadow mode)\n")

    header = (
        f"{'Instance':<40} {'Orig':>8} {'Comp':>8} "
        f"{'Saved':>8} {'Reduction':>10} {'Turns':>6} {'Soft-p':>6} {'ms':>6}"
    )
    print(header)
    print("-" * len(header))

    for r in results:
        if r.skipped:
            print(f"{'SKIP: ' + r.instance_id:<40} {'—':>8} {'—':>8} {'—':>8} {r.skip_reason[:10]:>10}")
        else:
            print(
                f"{r.instance_id:<40} "
                f"{_fmt_tokens(r.original_tokens):>8} "
                f"{_fmt_tokens(r.compressed_tokens):>8} "
                f"{_fmt_tokens(r.tokens_saved):>8} "
                f"{_fmt_pct(r.reduction_pct):>10} "
                f"{r.n_turns:>6} "
                f"{r.segments_soft_protected:>6} "
                f"{r.elapsed_ms:>6.0f}"
            )

    print("\n--- Aggregate ---")
    print(f"Instances evaluated : {agg.n_instances - agg.n_skipped} ({agg.n_skipped} skipped)")
    print(f"Total original      : {_fmt_tokens(agg.total_original_tokens)} tokens")
    print(f"Total saved         : {_fmt_tokens(agg.total_tokens_saved)} tokens")
    print(f"Aggregate reduction : {_fmt_pct(agg.aggregate_reduction_pct)}")
    print(f"Mean reduction      : {_fmt_pct(agg.mean_reduction_pct)}")
    print(f"p50 reduction       : {_fmt_pct(agg.p50_reduction_pct)}")
    print(f"p95 reduction       : {_fmt_pct(agg.p95_reduction_pct)}")
    print(f"Soft-prot segments  : {agg.total_soft_protected_segments:,}")
    print(f"Mean latency        : {agg.mean_elapsed_ms:.1f} ms/instance\n")


def write_json_output(
    results: list[InstanceResult],
    agg: AggregateStats,
    path: Path,
    config: CompressionConfig,
) -> None:
    """Write results to a JSON file for downstream processing.

    Args:
        results: Per-instance results.
        agg: Aggregate statistics.
        path: Output file path.
        config: The exact config used for the evaluation. Recorded verbatim so
            the results file never misrepresents how it was produced.
    """
    payload: dict[str, Any] = {
        "metadata": {
            "strategy": config.strategy.value,
            # Report the config exactly as run. The eval forces shadow_mode off
            # to observe compression offline; recording True here (as a prior
            # version did) misrepresents the run.
            "shadow_mode": config.shadow_mode,
            "min_turns_protected": config.min_turns_protected,
            "target_reduction_pct": config.target_reduction_pct,
            "shipped_default_config": config.min_turns_protected
            == get_config(config.strategy).min_turns_protected,
            "traject_version": _get_traject_version(),
        },
        "aggregate": {
            "n_instances": agg.n_instances,
            "n_skipped": agg.n_skipped,
            "total_original_tokens": agg.total_original_tokens,
            "total_compressed_tokens": agg.total_compressed_tokens,
            "total_tokens_saved": agg.total_tokens_saved,
            "aggregate_reduction_pct": round(agg.aggregate_reduction_pct, 4),
            "mean_reduction_pct": round(agg.mean_reduction_pct, 4),
            "p50_reduction_pct": round(agg.p50_reduction_pct, 4),
            "p95_reduction_pct": round(agg.p95_reduction_pct, 4),
            "mean_elapsed_ms": round(agg.mean_elapsed_ms, 2),
            "total_soft_protected_segments": agg.total_soft_protected_segments,
        },
        "instances": [
            {
                "instance_id": r.instance_id,
                "original_tokens": r.original_tokens,
                "compressed_tokens": r.compressed_tokens,
                "tokens_saved": r.tokens_saved,
                "reduction_pct": round(r.reduction_pct, 4),
                "n_turns": r.n_turns,
                "segments_soft_protected": r.segments_soft_protected,
                "elapsed_ms": round(r.elapsed_ms, 2),
                "skipped": r.skipped,
                "skip_reason": r.skip_reason,
            }
            for r in results
        ],
    }

    path.write_text(json.dumps(payload, indent=2))
    print(f"Results written to: {path}", file=sys.stderr)


def _get_traject_version() -> str:
    """Return the installed traject-sdk version string."""
    try:
        from traject import __version__  # noqa: PLC0415
        return __version__
    except ImportError:
        return "unknown"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        required=True,
        metavar="FILE",
        help="Path to JSONL file containing SWE-bench trajectories.",
    )
    parser.add_argument(
        "--n-instances", "-n",
        type=int,
        default=None,
        metavar="N",
        help="Evaluate only the first N instances. Default: all.",
    )
    parser.add_argument(
        "--strategy", "-s",
        choices=["conservative", "moderate", "aggressive"],
        default="conservative",
        help="Compression strategy to apply. Default: conservative.",
    )
    parser.add_argument(
        "--unprotected",
        action="store_true",
        help=(
            "Reproduce the legacy benchmark-only config (min_turns_protected=0). "
            "This disables the recent-turn safety guarantee that ships by default; "
            "its numbers do NOT describe out-of-the-box behaviour."
        ),
    )
    parser.add_argument(
        "--output-json", "-o",
        type=Path,
        default=None,
        metavar="FILE",
        help="Write results to a JSON file for downstream processing.",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Suppress progress output.",
    )
    return parser


def main() -> None:
    """Entry point for the SWE-bench evaluation script."""
    parser = _build_parser()
    args = parser.parse_args()

    strategy = CompressionStrategy(args.strategy)
    config = build_config(strategy, unprotected=args.unprotected)

    print(
        f"Loading trajectories from: {args.input}",
        file=sys.stderr,
    )
    if args.n_instances:
        print(f"Evaluating first {args.n_instances} instances.", file=sys.stderr)

    instances = load_trajectories(args.input, n_instances=args.n_instances)

    if not instances:
        print("ERROR: No valid instances found in input file.", file=sys.stderr)
        sys.exit(1)

    config_label = (
        "LEGACY unprotected config (min_turns_protected=0)"
        if args.unprotected
        else f"shipped default config (min_turns_protected={config.min_turns_protected})"
    )
    print(
        f"Measuring {strategy.value.upper()} compression on {len(instances)} "
        f"instances — {config_label}. No provider calls are made.",
        file=sys.stderr,
    )

    results = run_evaluation(
        instances,
        config=config,
        show_progress=not args.no_progress,
    )
    agg = compute_aggregate(results)

    if _RICH_AVAILABLE:
        print_results_rich(results, agg, strategy)
    else:
        print_results_plain(results, agg, strategy)

    if args.output_json:
        write_json_output(results, agg, args.output_json, config)


if __name__ == "__main__":
    main()
