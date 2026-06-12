"""Axon SDK command-line interface.

Provides three commands: analyze (read JSONL span logs and display cost
summary), version (print the SDK version), and doctor (check that all
required dependencies are installed).
"""
from __future__ import annotations

import importlib
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import structlog
import typer
from rich.console import Console
from rich.table import Table

from axon.models import InferenceSpan

app = typer.Typer(name="axon", help="Axon SDK developer tools.")
console = Console()
_log = structlog.get_logger(__name__)


@app.command()
def analyze(
    input: Annotated[
        Path,
        typer.Option(
            "--input",
            "-i",
            help="Path to JSONL file of InferenceSpan records.",
        ),
    ],
    format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: table or json."),
    ] = "table",
) -> None:
    """Analyze a JSONL file of InferenceSpan records and display a cost summary.

    Args:
        input: Path to the JSONL file containing InferenceSpan records.
        format: Output format — 'table' (default) or 'json'.
    """
    if not input.exists():
        console.print(f"[red]Error: file not found: {input}[/red]")
        raise typer.Exit(code=1)

    # aggregated[key] = {calls, input_tokens, output_tokens, cost_usd, tokens_saved,
    #                    cache_hits}
    aggregated: dict[tuple[str, str], dict[str, Any]] = {}

    with input.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                span = InferenceSpan.model_validate_json(line)
            except Exception as exc:
                _log.warning(
                    "axon.cli.analyze.skip_malformed_line",
                    line=line_number,
                    error=str(exc),
                )
                continue

            key = (span.model, span.feature_tag)
            if key not in aggregated:
                aggregated[key] = {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": Decimal("0"),
                    "tokens_saved": 0,
                    "cache_hits": 0,
                }
            entry = aggregated[key]
            entry["calls"] += 1
            entry["input_tokens"] += span.input_tokens
            entry["output_tokens"] += span.output_tokens
            if span.cost_usd is not None:
                entry["cost_usd"] += span.cost_usd
            if span.tokens_saved is not None:
                entry["tokens_saved"] += span.tokens_saved
            if span.cache_hit:
                entry["cache_hits"] += 1

    if format == "json":
        rows = [
            {
                "model": model,
                "feature_tag": tag,
                **{k: str(v) if isinstance(v, Decimal) else v for k, v in data.items()},
            }
            for (model, tag), data in aggregated.items()
        ]
        console.print(json.dumps(rows, indent=2))
        return

    # Default: rich table
    table = Table(title="Axon Cost Analysis")
    table.add_column("Model", style="cyan")
    table.add_column("Feature Tag", style="magenta")
    table.add_column("Calls", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Cost (USD)", justify="right", style="green")
    table.add_column("Shadow Savings (tokens)", justify="right")
    table.add_column("Cache Hits", justify="right")

    for (model, tag), data in aggregated.items():
        table.add_row(
            model,
            tag,
            str(data["calls"]),
            str(data["input_tokens"]),
            str(data["output_tokens"]),
            str(data["cost_usd"]),
            str(data["tokens_saved"]),
            str(data["cache_hits"]),
        )

    console.print(table)


@app.command()
def version() -> None:
    """Print the axon-sdk version."""
    console.print("axon-sdk 0.1.0")


@app.command(name="cache-advisor")
def cache_advisor(
    input: Annotated[
        Path,
        typer.Option(
            "--input",
            "-i",
            help="Path to JSONL file of InferenceSpan records.",
        ),
    ],
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            "-p",
            help="Provider name (e.g. anthropic, openai).",
        ),
    ] = "anthropic",
) -> None:
    """Analyse spans from a JSONL file for prompt cache optimisation opportunities.

    Reads a JSONL file produced by the Axon instrumentor, groups spans by their
    prompt hash, and prints a rich table summarising any detected caching
    opportunities.

    Args:
        input: Path to the JSONL file containing InferenceSpan records.
        provider: Provider name used to look up the caching threshold.
    """
    if not input.exists():
        typer.echo(f"Error: file not found: {input}", err=True)
        raise typer.Exit(code=1)

    from axon.advisor.prompt_cache_advisor import PromptCacheAdvisor

    advisor = PromptCacheAdvisor()
    report = advisor.analyze_directory(str(input))

    table = Table(title="Prompt Cache Opportunities")
    table.add_column("Provider")
    table.add_column("Token Count", justify="right")
    table.add_column("Est. Savings %", justify="right")
    table.add_column("Recommendation")

    for opp in report.opportunities:
        table.add_row(
            opp.provider,
            str(opp.token_count),
            f"{opp.estimated_savings_pct:.1%}",
            opp.recommendation,
        )

    console.print(table)


@app.command()
def doctor() -> None:
    """Check that required dependencies are installed and report their status.

    Exits with code 0 if all required dependencies are present, 1 otherwise.
    """
    required_checks = [
        ("sentence-transformers", "sentence_transformers"),
        ("opentelemetry-sdk", "opentelemetry.sdk"),
        ("tiktoken", "tiktoken"),
    ]
    optional_checks = [
        ("openai (optional)", "openai"),
        ("anthropic (optional)", "anthropic"),
    ]

    table = Table(title="Axon Dependency Check")
    table.add_column("Package", style="bold")
    table.add_column("Status")

    all_required_ok = True

    for display_name, import_name in required_checks:
        try:
            importlib.import_module(import_name)
            table.add_row(display_name, "[green]✓ installed[/green]")
        except ImportError:
            table.add_row(display_name, "[red]✗ missing (required)[/red]")
            all_required_ok = False

    for display_name, import_name in optional_checks:
        try:
            importlib.import_module(import_name)
            table.add_row(display_name, "[green]✓ installed[/green]")
        except ImportError:
            table.add_row(display_name, "[yellow]✗ not installed (optional)[/yellow]")

    # Check AXON_OTLP_ENDPOINT env var
    otlp_endpoint = os.environ.get("AXON_OTLP_ENDPOINT")
    if otlp_endpoint:
        table.add_row("AXON_OTLP_ENDPOINT", f"[green]set ({otlp_endpoint})[/green]")
    else:
        table.add_row("AXON_OTLP_ENDPOINT", "[dim]not set[/dim]")

    console.print(table)
    raise typer.Exit(code=0 if all_required_ok else 1)
