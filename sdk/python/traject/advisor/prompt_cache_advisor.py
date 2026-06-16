"""Prompt cache optimization advisor for identifying cacheable prompt prefixes.

This module analyses system prompts and JSONL span logs to detect opportunities
where a stable prefix can be separated from a volatile suffix, allowing the
provider's prompt-caching mechanism to amortise the cost of the stable portion
across repeated calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import tiktoken

from traject.models import InferenceSpan

__all__ = [
    "CACHE_THRESHOLDS",
    "AdvisorReport",
    "CacheOpportunity",
    "PromptCacheAdvisor",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_THRESHOLDS: dict[str, int] = {
    "anthropic": 1024,
    "openai": 1024,
}

_VOLATILE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\{[^}]+\}"),  # {variable} format strings
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO dates
    re.compile(r"\btoday\b|\bnow\b|\bcurrent date\b", re.IGNORECASE),
    re.compile(r"\buser(?:name)?\b|\bsession\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CacheOpportunity:
    """A detected opportunity to apply prompt caching to a stable prefix.

    Attributes:
        segment: The stable text prefix that is safe to cache.
        token_count: Number of tokens in the stable prefix.
        provider: Provider name (e.g. ``"anthropic"``, ``"openai"``).
        estimated_savings_pct: Fraction of total token cost that could be
            saved by caching this prefix (0.0-0.9).
        recommendation: Human-readable action the caller should take.
    """

    segment: str
    token_count: int
    provider: str
    estimated_savings_pct: float
    recommendation: str


@dataclass
class AdvisorReport:
    """Summary report produced by the advisor after analysing a collection of spans.

    Attributes:
        analyzed_prompts: Number of unique prompt hashes examined.
        cache_eligible_count: Number of prompts meeting the token threshold.
        opportunities: List of individual cache opportunities found.
        total_estimated_savings_pct: Average estimated savings across all
            eligible opportunities.
        restructuring_suggestions: Free-text suggestions for restructuring
            prompts to improve cache hit rates.
    """

    analyzed_prompts: int
    cache_eligible_count: int
    opportunities: list[CacheOpportunity] = field(default_factory=list)
    total_estimated_savings_pct: float = 0.0
    restructuring_suggestions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------


class PromptCacheAdvisor:
    """Analyses prompts and span logs for prompt-caching optimisation opportunities.

    The advisor operates on raw system-prompt text (``analyze_prompt``),
    on in-memory collections of :class:`~traject.models.InferenceSpan` objects
    (``analyze_spans``), or directly on JSONL log files (``analyze_directory``).
    """

    def analyze_prompt(
        self,
        system_prompt: str,
        provider: str,
    ) -> CacheOpportunity | None:
        """Analyse a single system prompt for caching eligibility.

        The prompt is tokenised with tiktoken's ``cl100k_base`` encoding.
        If the token count is below the provider's threshold, ``None`` is
        returned immediately — the prompt is too short to benefit from caching.
        Otherwise the prompt is split into lines, and the first line that
        matches any volatile pattern marks the boundary between the stable
        prefix (cacheable) and the volatile suffix (not cacheable).

        Args:
            system_prompt: The raw system-prompt text to evaluate.
            provider: Provider name used to look up the caching threshold
                (e.g. ``"anthropic"`` or ``"openai"``).

        Returns:
            A :class:`CacheOpportunity` describing the stable prefix and
            the estimated savings, or ``None`` if the prompt is below the
            token threshold or has no stable content.
        """
        encoding = tiktoken.get_encoding("cl100k_base")
        total_tokens = len(encoding.encode(system_prompt))
        threshold = CACHE_THRESHOLDS.get(provider, 1024)

        if total_tokens < threshold:
            return None

        lines = system_prompt.split("\n")

        first_volatile_idx: int | None = None
        for idx, line in enumerate(lines):
            if any(pattern.search(line) for pattern in _VOLATILE_PATTERNS):
                first_volatile_idx = idx
                break

        stable_lines = (
            lines[:first_volatile_idx] if first_volatile_idx is not None else lines
        )
        stable_text = "\n".join(stable_lines)
        stable_tokens = len(encoding.encode(stable_text)) if stable_text else 0

        estimated_savings_pct = stable_tokens / total_tokens * 0.9
        recommendation = (
            f"Move stable prefix ({stable_tokens} tokens) before volatile suffix. "
            "Apply cache_control to prefix block."
        )

        return CacheOpportunity(
            segment=stable_text,
            token_count=stable_tokens,
            provider=provider,
            estimated_savings_pct=estimated_savings_pct,
            recommendation=recommendation,
        )

    def analyze_spans(self, spans: list[Any]) -> AdvisorReport:
        """Analyse a collection of inference spans for caching opportunities.

        Because spans store only a SHA-256 hash of the original prompt (never
        the raw text), this method cannot call :meth:`analyze_prompt` with
        real content.  Instead it groups spans by ``prompt_hash`` to count
        the number of unique prompts seen, which is the primary advisory
        signal: a high call count for a single hash means that prompt is
        a strong caching candidate.

        Args:
            spans: A list of objects that each expose a ``prompt_hash``
                attribute (typically :class:`~traject.models.InferenceSpan`
                instances or compatible objects).

        Returns:
            An :class:`AdvisorReport` with ``analyzed_prompts`` equal to the
            number of unique hashes found.  ``cache_eligible_count`` and
            ``opportunities`` are always 0 / empty because raw prompt text
            is unavailable.
        """
        unique_hashes: set[str] = set()
        for span in spans:
            prompt_hash: str = span.prompt_hash
            unique_hashes.add(prompt_hash)

        return AdvisorReport(
            analyzed_prompts=len(unique_hashes),
            cache_eligible_count=0,
            opportunities=[],
            total_estimated_savings_pct=0.0,
            restructuring_suggestions=[],
        )

    def analyze_directory(self, jsonl_path: str) -> AdvisorReport:
        """Read a JSONL file of InferenceSpan records and analyse them.

        Each line in the file is parsed as an :class:`~traject.models.InferenceSpan`
        using Pydantic's ``model_validate_json``.  Malformed lines are silently
        skipped.  The collected spans are passed to :meth:`analyze_spans`.

        Args:
            jsonl_path: Filesystem path to the JSONL file to read.

        Returns:
            An :class:`AdvisorReport` summarising the spans found in the file.
        """
        spans: list[InferenceSpan] = []
        with open(jsonl_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    span = InferenceSpan.model_validate_json(line)
                    spans.append(span)
                except Exception:  # skip malformed lines silently
                    continue

        return self.analyze_spans(spans)
