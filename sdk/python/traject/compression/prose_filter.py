"""Prose filler removal for ASSISTANT segments (Caveman-inspired).

Strips conversational hedging, pleasantries, and filler phrases from assistant
turns without touching code content.

Design:
- Conservative: only patterns that are unambiguously filler
- Code-safe: skips content that contains fenced code blocks
- Idempotent: applying twice produces the same result as once
- Never returns a longer string than the input
"""

from __future__ import annotations

import re

# Each rule is (compiled pattern, replacement string).
# Patterns are applied in order; earlier removals may expose text for later ones.
_RULES: list[tuple[re.Pattern[str], str]] = [
    # Opening single-word pleasantries at the very start of the message.
    (
        re.compile(
            r"^(?:Certainly|Absolutely|Sure|Great|Excellent|Perfect"
            r"|Indeed|Understood)[!.]\s*",
            re.IGNORECASE,
        ),
        "",
    ),
    (re.compile(r"^Of course[!.]\s*", re.IGNORECASE), ""),
    (re.compile(r"^No problem[!.]\s*", re.IGNORECASE), ""),
    # Closing pleasantries at the very end of the message.
    (
        re.compile(
            r"\s+(?:Please\s+)?(?:let me know|feel free to ask)"
            r"[^.!?\n]*[.!]?\s*$",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        re.compile(
            r"\s+I\s+hope\s+(?:this|that)\s+(?:helps|answers)[^.!?\n]*[.!]?\s*$",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        re.compile(r"\s+Don't hesitate to ask[^.!?\n]*[.!]?\s*$", re.IGNORECASE),
        "",
    ),
    # Filler introductory phrases (mid-text or sentence-initial).
    (re.compile(r"\bIt(?:'s| is) worth noting that\s+", re.IGNORECASE), ""),
    (re.compile(r"\bIt(?:'s| is) important to note that\s+", re.IGNORECASE), ""),
    (re.compile(r"\bPlease note that\s+", re.IGNORECASE), ""),
    (re.compile(r"\bAs you can see[,\s]+", re.IGNORECASE), ""),
    (
        re.compile(
            r"\bAs mentioned(?: earlier| above| previously)?[,\s]+",
            re.IGNORECASE,
        ),
        "",
    ),
    # Sentence-initial hedging.
    # "I don't think" is safe: "don't" appears between "I" and "think".
    (re.compile(r"\bI think,?\s+", re.IGNORECASE), ""),
    (re.compile(r"\bI believe,?\s+", re.IGNORECASE), ""),
]

_MULTI_SPACE_RE: re.Pattern[str] = re.compile(r"  +")


def strip_filler(content: str) -> str:
    """Remove prose filler from an assistant message.

    Skips content that contains fenced code blocks (triple backticks) to avoid
    corrupting code or structured data.

    Args:
        content: The assistant message text.

    Returns:
        Filtered content with filler phrases removed.  Never longer than the
        input.  Returns *content* unchanged when it contains a fenced code block.
    """
    if "```" in content:
        return content

    result = content
    for pattern, replacement in _RULES:
        result = pattern.sub(replacement, result)

    # Collapse double spaces left by removals and strip outer whitespace.
    result = _MULTI_SPACE_RE.sub(" ", result).strip()

    # Inflation guard: never return a longer string (belt-and-suspenders).
    return result if len(result) <= len(content) else content
