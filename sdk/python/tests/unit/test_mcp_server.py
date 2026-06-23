"""Unit tests for traject.mcp.server — MCP tool implementations."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from traject.exceptions import TrajectError


# ---------------------------------------------------------------------------
# Helpers — reset global session state before each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_session() -> None:  # type: ignore[return]
    """Reset the module-level _session before every test."""
    import traject.mcp.server as srv

    srv._session = srv._SessionStats()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_traject_compress_shadow_mode() -> None:
    """Shadow mode returns original text and tokens_saved >= 0."""
    from traject.mcp.server import traject_compress

    text = "This is a test message that will be analysed for compression."
    result = traject_compress(text=text, strategy="conservative", shadow_mode=True)

    assert result["text"] == text, "Shadow mode must return original text unchanged"
    assert result["tokens_saved"] >= 0
    assert result["shadow_mode"] is True
    assert result["strategy"] == "conservative"


def test_traject_compress_live_mode() -> None:
    """Live mode returns some text and compression_ratio in [0, 1]."""
    from traject.mcp.server import traject_compress

    text = (
        "Please summarise the following tool output. "
        "The tool returned a large JSON blob with many fields. "
        "Most of the fields are not relevant to the current task. "
        "Only the 'status' and 'error' fields matter. "
    ) * 5
    result = traject_compress(text=text, strategy="aggressive", shadow_mode=False)

    assert isinstance(result["text"], str)
    assert 0.0 <= result["compression_ratio"] <= 1.0
    assert result["shadow_mode"] is False
    assert isinstance(result["original_tokens"], int)
    assert result["original_tokens"] > 0


def test_traject_compress_invalid_strategy() -> None:
    """An unrecognised strategy string raises ValueError."""
    from traject.mcp.server import traject_compress

    with pytest.raises(ValueError, match="Unknown strategy"):
        traject_compress(text="hello", strategy="turbo-ultra-max")


def test_traject_compress_empty_text() -> None:
    """Compressing an empty string does not raise."""
    from traject.mcp.server import traject_compress

    result = traject_compress(text="", strategy="conservative", shadow_mode=True)
    assert isinstance(result, dict)
    assert result["text"] == ""
    assert result["tokens_saved"] >= 0


def test_traject_compress_updates_session_stats() -> None:
    """After one compress call, traject_stats() reports calls=1."""
    from traject.mcp.server import traject_compress, traject_stats

    traject_compress(text="Session stats update test", strategy="conservative")
    stats = traject_stats()

    assert stats["calls"] == 1
    assert stats["total_input_tokens"] >= 0
    assert stats["session_active"] is True


def test_traject_stats_initial() -> None:
    """A fresh session has calls=0 and zero tokens."""
    from traject.mcp.server import traject_stats

    stats = traject_stats()

    assert stats["calls"] == 0
    assert stats["total_input_tokens"] == 0
    assert stats["total_tokens_saved"] == 0
    assert stats["aggregate_reduction_pct"] == 0.0
    assert stats["total_cost_usd"] == str(Decimal("0"))
    assert stats["session_active"] is True


def test_traject_budget_no_limit() -> None:
    """With no limit set, status is 'no_limit'."""
    from traject.mcp.server import traject_budget

    result = traject_budget()

    assert result["status"] == "no_limit"
    assert result["budget_limit"] is None
    assert result["budget_remaining"] is None
    assert result["pct_used"] is None


def test_traject_budget_set_and_check() -> None:
    """Setting a budget then checking returns correct remaining tokens."""
    from traject.mcp.server import traject_budget, traject_compress

    # Consume some tokens first.
    traject_compress(text="budget check token spend", strategy="conservative")

    # Set a large budget.
    result = traject_budget(limit_tokens=100_000)

    assert result["budget_limit"] == 100_000
    assert result["status"] in {"ok", "warning", "exceeded"}
    assert result["budget_remaining"] is not None
    assert result["budget_remaining"] >= 0
    assert result["pct_used"] is not None
    assert 0.0 <= result["pct_used"] <= 10.0  # should be well under for a small text


def test_traject_budget_warning_threshold() -> None:
    """When tokens_used > 80% of limit, status is 'warning'."""
    import traject.mcp.server as srv
    from traject.mcp.server import traject_budget

    # Manually set session tokens to 85% of the limit we will set.
    srv._session.total_input_tokens = 850

    result = traject_budget(limit_tokens=1_000)

    assert result["status"] == "warning"
    assert result["pct_used"] is not None
    assert result["pct_used"] > 0.8


def test_traject_compress_traject_error_returns_original() -> None:
    """When compress() raises TrajectError, the tool returns original text."""
    from traject.mcp.server import traject_compress

    original_text = "This text should come back unchanged on error."

    with patch(
        "traject.mcp.server.compress",
        side_effect=TrajectError("simulated compression failure"),
    ):
        result = traject_compress(
            text=original_text,
            strategy="conservative",
            shadow_mode=True,
        )

    assert result["text"] == original_text
    assert result["tokens_saved"] == 0
    assert len(result["warnings"]) > 0
    assert "simulated compression failure" in result["warnings"][0]
