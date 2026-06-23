"""MCP server implementation for the Traject SDK.

Exposes three MCP tools — ``traject_compress``, ``traject_stats``, and
``traject_budget`` — allowing any MCP-compatible client (Copilot agent mode,
Claude Desktop, Cursor, etc.) to leverage Traject's compression pipeline and
token-budget tracking without code changes or API keys.

Session state is maintained at module level (per-process). Thread safety is
not guaranteed in concurrent environments; for MVP single-process deployments
this is acceptable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog
import tiktoken
from mcp.server.fastmcp import FastMCP

from traject.compression.engine import compress
from traject.compression.strategies import (
    CompressionConfig,
    CompressionStrategy,
    get_config,
)
from traject.exceptions import TrajectError

_log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class _SessionStats:
    """Accumulated compression metrics for the current MCP server session.

    Attributes:
        calls: Number of ``traject_compress`` calls in this session.
        total_input_tokens: Sum of original token counts across all calls.
        total_output_tokens: Sum of compressed token counts across all calls.
        total_tokens_saved: Sum of tokens eliminated across all calls.
        total_cost_usd: Placeholder cost accumulator (always zero in Phase 3;
            kept as Decimal for ADR-006 compliance).
        budget_limit_tokens: Optional session-level token budget set via
            ``traject_budget``.
    """

    calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens_saved: int = 0
    total_cost_usd: Decimal = field(default_factory=lambda: Decimal("0"))
    budget_limit_tokens: int | None = None


_session: _SessionStats = _SessionStats()

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp: FastMCP = FastMCP("traject")

# ---------------------------------------------------------------------------
# Strategy string → enum helper
# ---------------------------------------------------------------------------

_VALID_STRATEGIES: dict[str, CompressionStrategy] = {
    s.value: s for s in CompressionStrategy
}


def _parse_strategy(strategy: str) -> CompressionStrategy:
    """Map a strategy name string to a :class:`CompressionStrategy` enum member.

    Args:
        strategy: One of ``"conservative"``, ``"moderate"``, or ``"aggressive"``.

    Returns:
        The matching :class:`CompressionStrategy` enum member.

    Raises:
        ValueError: If *strategy* is not a recognised strategy name.
    """
    normalised = strategy.strip().lower()
    if normalised not in _VALID_STRATEGIES:
        valid = ", ".join(f'"{v}"' for v in _VALID_STRATEGIES)
        raise ValueError(f"Unknown strategy {strategy!r}. Valid options are: {valid}.")
    return _VALID_STRATEGIES[normalised]


# ---------------------------------------------------------------------------
# Tool: traject_compress
# ---------------------------------------------------------------------------


@mcp.tool()
def traject_compress(
    text: str,
    strategy: str = "conservative",
    shadow_mode: bool = True,
) -> dict[str, Any]:
    """Compress a text blob before passing it to an LLM.

    Runs Traject's trajectory compression pipeline on the provided text,
    returning the compressed version alongside token reduction metrics.
    Safe to use in shadow mode (default) — original text is returned
    alongside metrics but nothing is modified.

    Args:
        text: The text content to compress (tool output, file content,
            log dump, RAG chunk, conversation history, etc.).
        strategy: Compression strategy — ``"conservative"`` (default, 20%
            target), ``"moderate"`` (35% target), or ``"aggressive"`` (55%
            target).
        shadow_mode: When ``True`` (default), returns the original text
            unchanged but still reports what compression would have saved.
            Set to ``False`` to return the compressed text.

    Returns:
        dict with keys:

        - **text** (str): compressed text, or original if ``shadow_mode=True``
        - **original_tokens** (int)
        - **compressed_tokens** (int)
        - **tokens_saved** (int)
        - **compression_ratio** (float)
        - **shadow_mode** (bool)
        - **strategy** (str)
        - **warnings** (list[str])
    """
    warnings: list[str] = []

    # Validate strategy before touching session state.
    try:
        strategy_enum = _parse_strategy(strategy)
    except ValueError:
        raise

    messages: list[dict[str, Any]] = [{"role": "user", "content": text}]

    # Build config respecting the caller's shadow_mode preference.
    base_config: CompressionConfig = get_config(strategy_enum)
    config = CompressionConfig(
        strategy=base_config.strategy,
        target_reduction_pct=base_config.target_reduction_pct,
        min_turns_protected=base_config.min_turns_protected,
        protect_system_prompt=base_config.protect_system_prompt,
        shadow_mode=shadow_mode,
        score_ceiling=base_config.score_ceiling,
    )

    try:
        result = compress(messages, config)
    except TrajectError as exc:
        _log.warning(
            "traject.mcp.compress_error",
            error=str(exc),
            strategy=strategy,
        )
        warnings.append(f"Compression failed ({exc}); returning original text.")
        # Count tokens for the original text so stats are still updated.
        enc = tiktoken.get_encoding("cl100k_base")
        original_tokens = len(enc.encode(text))
        _session.calls += 1
        _session.total_input_tokens += original_tokens
        _session.total_output_tokens += original_tokens
        return {
            "text": text,
            "original_tokens": original_tokens,
            "compressed_tokens": original_tokens,
            "tokens_saved": 0,
            "compression_ratio": 0.0,
            "shadow_mode": shadow_mode,
            "strategy": strategy,
            "warnings": warnings,
        }

    # Update session stats.
    _session.calls += 1
    _session.total_input_tokens += result.original_tokens
    _session.total_output_tokens += result.compressed_tokens
    _session.total_tokens_saved += result.tokens_saved

    # Determine output text.
    if shadow_mode:
        output_text = text
    else:
        first_msg = result.messages[0]
        content = first_msg.get("content", "") if isinstance(first_msg, dict) else ""
        output_text = content if isinstance(content, str) else text

    return {
        "text": output_text,
        "original_tokens": result.original_tokens,
        "compressed_tokens": result.compressed_tokens,
        "tokens_saved": result.tokens_saved,
        "compression_ratio": result.compression_ratio,
        "shadow_mode": shadow_mode,
        "strategy": strategy,
        "warnings": result.warnings,
    }


# ---------------------------------------------------------------------------
# Tool: traject_stats
# ---------------------------------------------------------------------------


@mcp.tool()
def traject_stats() -> dict[str, Any]:
    """Return compression statistics for the current Traject session.

    Reports aggregate token reduction metrics accumulated since the MCP
    server started or since the last session reset.

    Returns:
        dict with keys:

        - **calls** (int): number of ``traject_compress`` calls this session
        - **total_input_tokens** (int)
        - **total_tokens_saved** (int)
        - **aggregate_reduction_pct** (float): 0.0 if no calls yet
        - **total_cost_usd** (str): Decimal formatted as string
        - **session_active** (bool)
    """
    reduction_pct = (
        _session.total_tokens_saved / _session.total_input_tokens
        if _session.total_input_tokens > 0
        else 0.0
    )
    return {
        "calls": _session.calls,
        "total_input_tokens": _session.total_input_tokens,
        "total_tokens_saved": _session.total_tokens_saved,
        "aggregate_reduction_pct": reduction_pct,
        "total_cost_usd": str(_session.total_cost_usd),
        "session_active": True,
    }


# ---------------------------------------------------------------------------
# Tool: traject_budget
# ---------------------------------------------------------------------------


@mcp.tool()
def traject_budget(
    limit_tokens: int | None = None,
) -> dict[str, Any]:
    """Check token spend against a configured budget threshold.

    When called with *limit_tokens*, sets or updates the session budget.
    Always returns current spend vs limit status.

    Args:
        limit_tokens: Optional token budget limit for this session.
            When provided, updates the session budget. When ``None``,
            returns status against any previously set limit.

    Returns:
        dict with keys:

        - **tokens_used** (int)
        - **tokens_saved** (int)
        - **budget_limit** (int | None)
        - **budget_remaining** (int | None)
        - **pct_used** (float | None): 0.0-1.0 or ``None`` if no limit set
        - **status** (str): ``"ok"``, ``"warning"`` (>80%), ``"exceeded"``
          (>100%), or ``"no_limit"``
    """
    if limit_tokens is not None:
        _session.budget_limit_tokens = limit_tokens
        _log.info(
            "traject.mcp.budget_set",
            limit_tokens=limit_tokens,
        )

    tokens_used = _session.total_input_tokens
    limit = _session.budget_limit_tokens

    if limit is None:
        return {
            "tokens_used": tokens_used,
            "tokens_saved": _session.total_tokens_saved,
            "budget_limit": None,
            "budget_remaining": None,
            "pct_used": None,
            "status": "no_limit",
        }

    remaining = max(0, limit - tokens_used)
    pct_used = tokens_used / limit if limit > 0 else 0.0

    if pct_used > 1.0:
        status = "exceeded"
    elif pct_used > 0.8:
        status = "warning"
    else:
        status = "ok"

    return {
        "tokens_used": tokens_used,
        "tokens_saved": _session.total_tokens_saved,
        "budget_limit": limit,
        "budget_remaining": remaining,
        "pct_used": pct_used,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Public factory + run helpers
# ---------------------------------------------------------------------------


def create_mcp_server() -> FastMCP:
    """Return the configured FastMCP server instance.

    Primarily used in tests to obtain the server instance without starting it.

    Returns:
        The module-level :data:`mcp` :class:`~mcp.server.fastmcp.FastMCP`
        instance with all three tools registered.
    """
    return mcp


def run(host: str = "localhost", port: int = 3000) -> None:
    """Start the Traject MCP server using stdio transport.

    Args:
        host: Hostname hint (informational; MCP stdio transport ignores it).
        port: Port hint (informational; MCP stdio transport ignores it).
    """
    _log.info(
        "traject.mcp.starting",
        host=host,
        port=port,
        transport="stdio",
    )
    mcp.run(transport="stdio")
