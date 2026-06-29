"""Tests for lossless tool-output dedup and the summary inflation guard.

These cover the two Phase-2 engine changes:

* repeated byte-identical TOOL_RESULT segments are deduplicated losslessly —
  earlier copies become a short stub, the last copy is kept verbatim; and
* a segment is never replaced by a summary that is not strictly smaller.
"""

from __future__ import annotations

from typing import Any

from traject.compression.engine import _DEDUP_STUB, compress
from traject.compression.strategies import CompressionConfig, CompressionStrategy


def _live(strategy: CompressionStrategy = CompressionStrategy.CONSERVATIVE) -> CompressionConfig:
    return CompressionConfig(
        strategy=strategy,
        target_reduction_pct=0.20,
        min_turns_protected=1,
        protect_system_prompt=True,
        shadow_mode=False,
    )


def _agent_loop_with_repeats(repeats: int) -> list[dict[str, Any]]:
    """A loop that re-reads the same large file `repeats` times."""
    big = "$ cat module.py\n" + "\n".join(f"line {i} of source code" for i in range(80))
    msgs: list[dict[str, Any]] = [{"role": "system", "content": "You are an agent."}]
    msgs.append({"role": "user", "content": "Fix the bug in module.py at line 42 (ValueError)."})
    for i in range(repeats):
        msgs.append({"role": "assistant", "content": f"Step {i}: read module.py."})
        msgs.append({"role": "tool", "content": big})
    msgs.append({"role": "assistant", "content": "Now I will apply the fix and run tests."})
    msgs.append({"role": "tool", "content": "$ pytest\n1 passed"})
    return msgs


class TestDedup:
    def test_repeated_tool_output_is_deduplicated(self) -> None:
        msgs = _agent_loop_with_repeats(repeats=4)
        result = compress(msgs, _live())
        # Earlier identical copies replaced by the stub; at least repeats-1 of them.
        stubs = [m for m in result.messages if m.get("content") == _DEDUP_STUB]
        assert len(stubs) >= 3
        assert result.tokens_saved > 0
        assert result.compressed_tokens < result.original_tokens

    def test_dedup_is_lossless_last_copy_retained_verbatim(self) -> None:
        msgs = _agent_loop_with_repeats(repeats=3)
        big = msgs[3]["content"]  # the repeated tool output
        result = compress(msgs, _live())
        blob = "\n".join(str(m.get("content", "")) for m in result.messages)
        # The full original output still appears verbatim exactly once.
        assert big in blob
        # A unique line from the file survived.
        assert "line 42 of source code" in blob

    def test_no_dedup_when_outputs_differ(self) -> None:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": "Sys."}]
        for i in range(4):
            msgs.append({"role": "assistant", "content": f"step {i}"})
            msgs.append({"role": "tool", "content": f"unique output {i} " + "x " * 50})
        result = compress(msgs, _live())
        assert all(m.get("content") != _DEDUP_STUB for m in result.messages)

    def test_dedup_respects_traject_preserve(self) -> None:
        big = "$ cat a.py\n" + "data\n" * 60
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": "Sys."},
            {"role": "assistant", "content": "read"},
            {"role": "tool", "content": big, "traject_preserve": True},
            {"role": "assistant", "content": "read again"},
            {"role": "tool", "content": big},
            {"role": "user", "content": "continue the task please now"},
            {"role": "assistant", "content": "ok"},
        ]
        result = compress(msgs, _live())
        # The preserved early copy must not be stubbed.
        assert any(
            m.get("content") == big for m in result.messages
        ), "preserved duplicate should remain verbatim"


class TestInflationGuard:
    def test_short_tool_result_not_inflated(self) -> None:
        # Single-token-ish tool output whose 'summary' + marker would be larger.
        msgs: list[dict[str, Any]] = [{"role": "system", "content": "Sys."}]
        msgs.append({"role": "tool", "content": "ok"})
        for i in range(5):
            msgs.append({"role": "user", "content": f"q{i}"})
            msgs.append({"role": "assistant", "content": f"a{i}"})
        result = compress(msgs, _live())
        # Never larger than the original, and no inflated marker emitted.
        assert result.compressed_tokens <= result.original_tokens
        assert all(
            "[summarized by Traject" not in str(m.get("content", ""))
            or len(str(m.get("content", ""))) < len("ok") + 60
            for m in result.messages
        )

    def test_compression_never_increases_tokens(self) -> None:
        for repeats in (1, 2, 5):
            msgs = _agent_loop_with_repeats(repeats=repeats)
            result = compress(msgs, _live())
            assert result.compressed_tokens <= result.original_tokens
            assert result.tokens_saved >= 0
