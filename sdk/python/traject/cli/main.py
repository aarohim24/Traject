"""Traject SDK command-line interface.

Provides commands: analyze (read JSONL span logs and display cost summary),
version (print the SDK version), doctor (check dependencies), mcp (start
MCP server), and proxy (start compression proxy).
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

from traject.models import InferenceSpan

app = typer.Typer(name="traject", help="Traject SDK developer tools.")
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
                    "traject.cli.analyze.skip_malformed_line",
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
    table = Table(title="Traject Cost Analysis")
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
    """Print the traject-sdk version."""
    from traject import __version__

    console.print(f"traject-sdk {__version__}")


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
    plan: Annotated[
        bool,
        typer.Option(
            "--plan",
            help=(
                "Print a structured optimisation plan instead of the default summary "
                "table. Shows per-opportunity restructuring steps and estimated "
                "savings without requiring any code changes."
            ),
            is_flag=True,
        ),
    ] = False,
) -> None:
    """Analyse spans from a JSONL file for prompt cache optimisation opportunities.

    Reads a JSONL file produced by the Traject instrumentor, groups spans by their
    prompt hash, and prints a rich table summarising any detected caching
    opportunities.  Pass --plan to see a structured step-by-step optimisation plan.

    Args:
        input: Path to the JSONL file containing InferenceSpan records.
        provider: Provider name used to look up the caching threshold.
        plan: When True, print a structured optimisation plan instead of the
            default summary table.
    """
    if not input.exists():
        typer.echo(f"Error: file not found: {input}", err=True)
        raise typer.Exit(code=1)

    from traject.advisor.prompt_cache_advisor import PromptCacheAdvisor

    advisor = PromptCacheAdvisor()
    report = advisor.analyze_directory(str(input))

    if plan:
        _print_cache_plan(report, provider)
        return

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


def _print_cache_plan(
    report: Any,
    provider: str,
) -> None:
    """Print a structured optimisation plan derived from an AdvisorReport.

    Renders a numbered list of actionable steps for each detected cache
    opportunity, followed by a summary of aggregate estimated savings.

    Args:
        report: An :class:`~traject.advisor.prompt_cache_advisor.AdvisorReport`
            produced by the advisor.
        provider: Provider name used as context in the plan header.
    """
    console.print(
        f"\n[bold cyan]Prompt Cache Optimisation Plan[/bold cyan]  "
        f"[dim](provider: {provider})[/dim]\n"
    )
    console.print(
        f"  Prompts analysed : [bold]{report.analyzed_prompts}[/bold]\n"
        f"  Cache-eligible   : [bold]{report.cache_eligible_count}[/bold]\n"
    )

    if not report.opportunities:
        console.print(
            "[dim]No cache opportunities detected. "
            "All prompts are below the provider token threshold "
            f"or contain no stable prefix.[/dim]\n"
        )
        return

    for idx, opp in enumerate(report.opportunities, start=1):
        savings_pct = f"{opp.estimated_savings_pct:.1%}"
        console.print(
            f"[bold]Opportunity {idx}[/bold]  "
            f"[green]{savings_pct} estimated savings[/green]  "
            f"({opp.token_count} stable tokens / {provider})"
        )
        console.print(f"  [yellow]Step 1[/yellow]  Identify stable prefix boundary.")
        console.print(
            f"  [yellow]Step 2[/yellow]  "
            "Move all static instructions above the first volatile line."
        )
        if provider == "anthropic":
            console.print(
                f"  [yellow]Step 3[/yellow]  "
                "Add ``cache_control: {{type: ephemeral}}`` to the stable block."
            )
        else:
            console.print(
                f"  [yellow]Step 3[/yellow]  "
                "Structure your request so the stable prefix is sent first and "
                "unchanged across calls to hit the OpenAI cached-prefix window."
            )
        console.print(f"  [dim]{opp.recommendation}[/dim]\n")

    if report.restructuring_suggestions:
        console.print("[bold]Additional suggestions[/bold]")
        for suggestion in report.restructuring_suggestions:
            console.print(f"  • {suggestion}")
        console.print()

    avg_savings = report.total_estimated_savings_pct
    console.print(
        f"[bold]Aggregate estimated savings: "
        f"[green]{avg_savings:.1%}[/green][/bold] across all eligible prompts.\n"
    )


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

    table = Table(title="Traject Dependency Check")
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

    # Check TRAJECT_OTLP_ENDPOINT env var
    otlp_endpoint = os.environ.get("TRAJECT_OTLP_ENDPOINT")
    if otlp_endpoint:
        table.add_row("TRAJECT_OTLP_ENDPOINT", f"[green]set ({otlp_endpoint})[/green]")
    else:
        table.add_row("TRAJECT_OTLP_ENDPOINT", "[dim]not set[/dim]")

    console.print(table)
    raise typer.Exit(code=0 if all_required_ok else 1)


@app.command(name="mcp")
def mcp_server(
    host: Annotated[str, typer.Option("--host", help="Host to bind.")] = "localhost",
    port: Annotated[int, typer.Option("--port", help="Port to listen on.")] = 3000,
    transport: Annotated[
        str,
        typer.Option("--transport", help="Transport: stdio or sse."),
    ] = "stdio",
) -> None:
    """Start the Traject MCP server for use with Copilot, Claude Desktop, or Cursor.

    Add to your MCP client config::

        command: traject
        args: ["mcp"]

    Args:
        host: Host hint forwarded to the MCP server (stdio transport ignores it).
        port: Port hint forwarded to the MCP server (stdio transport ignores it).
        transport: MCP transport protocol — ``"stdio"`` (default) or ``"sse"``.
    """
    try:
        from traject.mcp.server import run
    except ImportError:
        typer.echo(
            "Error: MCP server requires 'mcp' package. "
            "Install with: pip install 'traject-sdk[mcp]'",
            err=True,
        )
        raise typer.Exit(code=1) from None

    console.print("[cyan]Starting Traject MCP server...[/cyan]")
    console.print(f"  Transport: {transport}")
    console.print("  Tools: traject_compress, traject_stats, traject_budget")
    run(host=host, port=port)


@app.command(name="proxy")
def proxy_server(
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port to listen on."),
    ] = 8080,
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help=(
                "Interface to bind. Defaults to 127.0.0.1 (localhost only). "
                "Use 0.0.0.0 ONLY if you understand it exposes this "
                "credential-bearing proxy on all network interfaces."
            ),
        ),
    ] = "127.0.0.1",
    backend: Annotated[
        str,
        typer.Option("--backend", "-b", help="Upstream API base URL."),
    ] = "https://api.openai.com",
    strategy: Annotated[
        str,
        typer.Option("--strategy", "-s", help="Compression strategy."),
    ] = "conservative",
    live: Annotated[
        bool,
        typer.Option("--live", help="Enable live compression (default: shadow mode)."),
    ] = False,
) -> None:
    """Start the Traject transparent compression proxy.

    Points your agent at ``http://localhost:<port>`` instead of the
    provider URL.  Compresses context transparently — no code changes
    required.

    Example::

        traject proxy --port 8080 --backend https://api.openai.com
        # Then set: OPENAI_BASE_URL=http://localhost:8080

    Args:
        port: TCP port to listen on.
        host: Interface to bind. Defaults to 127.0.0.1 (localhost only);
            0.0.0.0 exposes the credential-bearing proxy on all interfaces.
        backend: Upstream OpenAI-compatible provider base URL.
        strategy: Compression strategy (``"conservative"``, ``"moderate"``,
            or ``"aggressive"``).
        live: When ``True``, applies live compression. Default is shadow mode
            (metrics only, original messages forwarded).
    """
    try:
        from traject.proxy.app import run
    except ImportError:
        typer.echo(
            "Error: Proxy requires fastapi+uvicorn. "
            "Install with: pip install 'traject-sdk[proxy]'",
            err=True,
        )
        raise typer.Exit(code=1) from None

    from traject.compression.strategies import CompressionStrategy

    shadow = not live
    console.print(f"[cyan]Starting Traject proxy on port {port}[/cyan]")
    console.print(f"  Backend:    {backend}")
    console.print(f"  Strategy:   {strategy}")
    console.print(
        f"  Mode:       {'shadow (metrics only)' if shadow else 'LIVE COMPRESSION'}"
    )
    console.print(f"\n  Set in your agent: OPENAI_BASE_URL=http://localhost:{port}")

    strategy_enum = CompressionStrategy(strategy)
    # Bind to 127.0.0.1 by default — this proxy injects the server's own API
    # credential into every upstream request, so 0.0.0.0 would expose a
    # credential-bearing endpoint on all interfaces. Override only deliberately.
    run(
        host=host,
        port=port,
        backend_url=backend,
        strategy=strategy_enum,
        shadow_mode=shadow,
    )
