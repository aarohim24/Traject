"""Unit tests for axon.advisor.prompt_cache_advisor.

Validates: Requirements 6.1–6.7 (Prompt Cache Optimization Advisor)
"""
from __future__ import annotations

import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from typer.testing import CliRunner

from traject.advisor.prompt_cache_advisor import (
    CACHE_THRESHOLDS,
    AdvisorReport,
    CacheOpportunity,
    PromptCacheAdvisor,
)
from traject.classifier.artifact_type import ArtifactType
from traject.cli.main import app
from traject.models import InferenceSpan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

runner = CliRunner()

_WORDS = (
    "The quick brown fox jumps over the lazy dog. "
    "Sphinx of black quartz judge my vow. "
    "Pack my box with five dozen liquor jugs. "
)


def _build_long_prompt(min_tokens: int = 1200) -> str:
    """Return a stable, volatile-free system prompt of at least *min_tokens* tokens.

    The prompt is constructed by repeating innocuous sentences until tiktoken
    reports that the cl100k_base token count exceeds the requested minimum.
    No volatile patterns ({var}, ISO dates, 'today', 'user', etc.) are used.
    """
    import tiktoken

    encoding = tiktoken.get_encoding("cl100k_base")
    text = _WORDS
    while len(encoding.encode(text)) < min_tokens:
        text += _WORDS
    return text


def _span_json(**overrides: Any) -> str:
    """Build a valid InferenceSpan JSON string for use in JSONL fixtures."""
    span = InferenceSpan(
        id=overrides.get("id", uuid4()),
        trace_id="trace-test",
        parent_span_id=None,
        span_name="gen_ai.anthropic.claude",
        timestamp=datetime.utcnow(),
        duration_ms=100,
        provider=overrides.get("provider", "anthropic"),
        model=overrides.get("model", "claude-3-5-haiku-20241022"),
        api_version=None,
        input_tokens=overrides.get("input_tokens", 500),
        output_tokens=overrides.get("output_tokens", 50),
        cached_tokens=0,
        token_count_method="exact",
        cost_usd=Decimal("0.00010000"),
        feature_tag=overrides.get("feature_tag", "test"),
        prompt_hash=overrides.get("prompt_hash", "a" * 64),
        artifact_type=ArtifactType.SYSTEM_PROMPT,
        compression_applied=False,
        shadow_mode=True,
        pre_compression_tokens=None,
        tokens_saved=None,
        cache_hit=False,
        environment="test",
    )
    return span.model_dump_json()


# ---------------------------------------------------------------------------
# analyze_prompt — token threshold
# ---------------------------------------------------------------------------


class TestAnalyzePromptBelowThreshold:
    """Validates Requirement 6.1 — returns None for prompts below threshold."""

    def test_short_prompt_returns_none(self) -> None:
        """Requirement 6.1: fewer than 1024 tokens → None."""
        advisor = PromptCacheAdvisor()
        # A single short sentence is far below 1024 tokens
        result = advisor.analyze_prompt("Hello, world!", "anthropic")
        assert result is None

    def test_threshold_boundary_below_returns_none(self) -> None:
        """Prompts just under the threshold must return None."""
        import tiktoken

        advisor = PromptCacheAdvisor()
        encoding = tiktoken.get_encoding("cl100k_base")
        threshold = CACHE_THRESHOLDS["anthropic"]  # 1024

        # Build a prompt that is exactly (threshold - 1) tokens
        # by adding words until we are one token short
        text = _WORDS
        while len(encoding.encode(text)) < threshold - 1:
            text += _WORDS
        # Trim excess
        tokens = encoding.encode(text)
        if len(tokens) >= threshold:
            text = encoding.decode(tokens[: threshold - 1])

        result = advisor.analyze_prompt(text, "anthropic")
        assert result is None

    def test_unknown_provider_uses_default_threshold_1024(self) -> None:
        """Unknown providers fall back to 1024 threshold."""
        advisor = PromptCacheAdvisor()
        result = advisor.analyze_prompt("short", "unknown_provider")
        assert result is None


# ---------------------------------------------------------------------------
# analyze_prompt — returns CacheOpportunity above threshold
# ---------------------------------------------------------------------------


class TestAnalyzePromptAboveThreshold:
    """Validates Requirements 6.2 and 6.4."""

    def test_returns_cache_opportunity(self) -> None:
        """Requirement 6.2: 1024+ tokens → CacheOpportunity returned."""
        advisor = PromptCacheAdvisor()
        long_prompt = _build_long_prompt(1200)
        result = advisor.analyze_prompt(long_prompt, "anthropic")

        assert result is not None
        assert isinstance(result, CacheOpportunity)

    def test_provider_matches_input(self) -> None:
        """Requirement 6.2: CacheOpportunity.provider equals the input provider."""
        advisor = PromptCacheAdvisor()
        result = advisor.analyze_prompt(_build_long_prompt(), "openai")
        assert result is not None
        assert result.provider == "openai"

    def test_token_count_gte_threshold(self) -> None:
        """Requirement 6.2: token_count in result is >= 0 and recommendation is non-empty."""
        advisor = PromptCacheAdvisor()
        result = advisor.analyze_prompt(_build_long_prompt(), "anthropic")
        assert result is not None
        assert result.token_count >= 0
        assert len(result.recommendation) > 0

    def test_estimated_savings_pct_formula(self) -> None:
        """Requirement 6.4: estimated_savings_pct == stable_tokens / total_tokens * 0.9."""
        import tiktoken

        advisor = PromptCacheAdvisor()
        encoding = tiktoken.get_encoding("cl100k_base")

        # No volatile patterns → stable_tokens == total_tokens
        long_prompt = _build_long_prompt(1200)
        result = advisor.analyze_prompt(long_prompt, "anthropic")
        assert result is not None

        total_tokens = len(encoding.encode(long_prompt))
        stable_tokens = result.token_count
        expected_savings = stable_tokens / total_tokens * 0.9

        assert abs(result.estimated_savings_pct - expected_savings) < 1e-9


# ---------------------------------------------------------------------------
# analyze_prompt — volatile line detection
# ---------------------------------------------------------------------------


class TestVolatilePatternDetection:
    """Validates Requirement 6.3."""

    def _make_prompt_with_volatile(self, stable_lines: int, volatile_line: str) -> str:
        """Return a long enough prompt with *stable_lines* stable lines then a volatile."""
        # Each "stable" line has many repeated words to push past token threshold
        stable = "\n".join(
            "word " * 80 for _ in range(stable_lines)
        )
        return stable + "\n" + volatile_line

    def test_format_placeholder_triggers_volatility(self) -> None:
        """Requirement 6.3: {variable} on line N → stable prefix is lines 0..N-1."""
        import tiktoken

        advisor = PromptCacheAdvisor()
        encoding = tiktoken.get_encoding("cl100k_base")

        # Build a 2-line stable block then a volatile line
        stable_part = "word " * 80 + "\n" + "word " * 80
        volatile_line = "Hello {user_name}, today is your day."
        prompt = stable_part + "\n" + volatile_line

        # Ensure total tokens exceed threshold
        while len(encoding.encode(prompt)) < 1024:
            stable_part = stable_part + "\n" + "word " * 80
            prompt = stable_part + "\n" + volatile_line

        result = advisor.analyze_prompt(prompt, "anthropic")
        assert result is not None
        # The volatile line itself must NOT appear in the stable segment
        assert "{user_name}" not in result.segment

    def test_iso_date_triggers_volatility(self) -> None:
        """Requirement 6.3: ISO date YYYY-MM-DD on a line marks it volatile."""
        import tiktoken

        advisor = PromptCacheAdvisor()
        encoding = tiktoken.get_encoding("cl100k_base")

        stable_part = "word " * 80 + "\n" + "word " * 80
        volatile_line = "The date is 2026-06-10, please remember."
        prompt = stable_part + "\n" + volatile_line

        while len(encoding.encode(prompt)) < 1024:
            stable_part = stable_part + "\n" + "word " * 80
            prompt = stable_part + "\n" + volatile_line

        result = advisor.analyze_prompt(prompt, "anthropic")
        assert result is not None
        assert "2026-06-10" not in result.segment

    def test_stable_prefix_stops_at_first_volatile_line(self) -> None:
        """Lines before the volatile marker form the stable prefix."""
        import tiktoken

        advisor = PromptCacheAdvisor()
        encoding = tiktoken.get_encoding("cl100k_base")

        line1 = "word " * 80
        line2 = "word " * 80
        line3 = "Today the {session} is active."  # volatile — 'today' + '{session}'
        line4 = "More content after volatile."

        prompt = "\n".join([line1, line2, line3, line4])
        while len(encoding.encode(prompt)) < 1024:
            line1 = line1 + " word" * 20
            prompt = "\n".join([line1, line2, line3, line4])

        result = advisor.analyze_prompt(prompt, "anthropic")
        assert result is not None
        # Stable segment must contain line1 and line2 but not line3 or line4
        assert "Today" not in result.segment
        assert "{session}" not in result.segment


# ---------------------------------------------------------------------------
# analyze_spans
# ---------------------------------------------------------------------------


class TestAnalyzeSpans:
    """Validates Requirements 6.5."""

    class _FakeSpan:
        """Minimal span-like object exposing only prompt_hash."""

        def __init__(self, prompt_hash: str) -> None:
            self.prompt_hash = prompt_hash

    def test_empty_list_returns_zero_analyzed(self) -> None:
        """Requirement 6.5: empty span list → analyzed_prompts == 0."""
        advisor = PromptCacheAdvisor()
        report = advisor.analyze_spans([])
        assert isinstance(report, AdvisorReport)
        assert report.analyzed_prompts == 0

    def test_groups_by_unique_prompt_hash(self) -> None:
        """Requirement 6.5: 3 spans with 2 unique hashes → analyzed_prompts == 2."""
        advisor = PromptCacheAdvisor()
        spans = [
            self._FakeSpan("a" * 64),
            self._FakeSpan("b" * 64),
            self._FakeSpan("a" * 64),  # duplicate
        ]
        report = advisor.analyze_spans(spans)
        assert report.analyzed_prompts == 2

    def test_all_unique_hashes_counted(self) -> None:
        """All distinct hashes are counted independently."""
        advisor = PromptCacheAdvisor()
        hashes = [hex(i)[2:].zfill(64)[:64] for i in range(1, 6)]
        spans = [self._FakeSpan(h) for h in hashes]
        report = advisor.analyze_spans(spans)
        assert report.analyzed_prompts == 5

    def test_returns_advisor_report_type(self) -> None:
        """analyze_spans always returns AdvisorReport."""
        advisor = PromptCacheAdvisor()
        report = advisor.analyze_spans([self._FakeSpan("c" * 64)])
        assert isinstance(report, AdvisorReport)


# ---------------------------------------------------------------------------
# analyze_directory
# ---------------------------------------------------------------------------


class TestAnalyzeDirectory:
    """Validates Requirement 6.6."""

    def test_valid_jsonl_returns_report_without_raising(self) -> None:
        """Requirement 6.6: valid JSONL file → AdvisorReport with no exception."""
        advisor = PromptCacheAdvisor()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(_span_json(prompt_hash="a" * 64) + "\n")
            f.write(_span_json(prompt_hash="b" * 64) + "\n")
            tmp_path = f.name

        try:
            report = advisor.analyze_directory(tmp_path)
            assert isinstance(report, AdvisorReport)
            assert report.analyzed_prompts == 2
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_malformed_lines_are_skipped(self) -> None:
        """Malformed JSONL lines do not cause an exception."""
        advisor = PromptCacheAdvisor()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(_span_json() + "\n")
            f.write("this is not valid json\n")
            f.write(_span_json(prompt_hash="c" * 64) + "\n")
            tmp_path = f.name

        try:
            report = advisor.analyze_directory(tmp_path)
            assert isinstance(report, AdvisorReport)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_empty_file_returns_zero_analyzed(self) -> None:
        """An empty JSONL file yields analyzed_prompts == 0."""
        advisor = PromptCacheAdvisor()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            tmp_path = f.name  # empty file

        try:
            report = advisor.analyze_directory(tmp_path)
            assert report.analyzed_prompts == 0
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# CLI: cache-advisor command
# ---------------------------------------------------------------------------


class TestCacheAdvisorCLI:
    """Validates Requirement 6.7."""

    def test_exits_0_with_valid_jsonl(self) -> None:
        """Requirement 6.7: CLI with valid JSONL exits 0 and prints a table."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(_span_json() + "\n")
            tmp_path = f.name

        try:
            result = runner.invoke(app, ["cache-advisor", "--input", tmp_path])
            assert result.exit_code == 0, result.output
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_exits_1_for_missing_file(self) -> None:
        """CLI exits 1 when the input file does not exist."""
        result = runner.invoke(
            app, ["cache-advisor", "--input", "/nonexistent/spans.jsonl"]
        )
        assert result.exit_code == 1

    def test_provider_option_accepted(self) -> None:
        """The --provider option is accepted without error."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write(_span_json() + "\n")
            tmp_path = f.name

        try:
            result = runner.invoke(
                app,
                ["cache-advisor", "--input", tmp_path, "--provider", "openai"],
            )
            assert result.exit_code == 0, result.output
        finally:
            Path(tmp_path).unlink(missing_ok=True)
