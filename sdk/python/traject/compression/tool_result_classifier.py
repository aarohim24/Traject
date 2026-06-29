"""Command-aware tool result classification and summarization (RTK-inspired).

Sub-classifies TOOL_RESULT segments by the type of command that produced
them, then applies a domain-specific mini-compressor tuned for each output
format instead of the one-size-fits-all prose extractor.

Supported types:
- GIT_DIFF    — ``git diff`` / patch output with hunk markers
- GIT_LOG     — ``git log`` history (full or ``--oneline``)
- GIT_STATUS  — ``git status`` working-tree summary
- PYTEST      — pytest / unittest test-runner output
- FILE_TREE   — ``ls`` / ``find`` / ``tree`` directory listings
- BUILD       — npm / pip / cargo / make build output
- GENERIC     — fallback prose-extraction path
"""

from __future__ import annotations

import re
from enum import Enum

# ── Tuning constants ──────────────────────────────────────────────────────────

_MAX_DIFF_HUNK_LINES: int = 8  # added/removed lines to keep per hunk
_MAX_LOG_COMMITS: int = 15  # max log entries to retain
_MAX_TREE_ENTRIES: int = 30  # max file listing lines to retain
_SUMMARY_MAX_CHARS: int = 300  # max chars in the generic prose summary body

# ── Code extension set (mirrors engine.py) ────────────────────────────────────

_CODE_EXTENSIONS: frozenset[str] = frozenset(
    [".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".sh"]
)


# ── CommandType enum ──────────────────────────────────────────────────────────


class CommandType(Enum):
    """Classification of a TOOL_RESULT by the command that produced it."""

    GIT_DIFF = "git_diff"
    GIT_LOG = "git_log"
    GIT_STATUS = "git_status"
    PYTEST = "pytest"
    FILE_TREE = "file_tree"
    BUILD = "build"
    GENERIC = "generic"


# ── Detection regexes ─────────────────────────────────────────────────────────

_GIT_DIFF_RE: re.Pattern[str] = re.compile(r"^diff --git ", re.MULTILINE)
_GIT_DIFF_PATCH_RE: re.Pattern[str] = re.compile(r"^--- a/", re.MULTILINE)
_GIT_LOG_COMMIT_RE: re.Pattern[str] = re.compile(r"^commit [0-9a-f]{40}$", re.MULTILINE)
_GIT_LOG_ONELINE_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{7,12} \S", re.MULTILINE)
_GIT_STATUS_RE: re.Pattern[str] = re.compile(
    r"On branch |Changes to be committed:|Changes not staged for commit:"
)
_PYTEST_HEADER_RE: re.Pattern[str] = re.compile(
    r"={3,} test session starts ={3,}", re.IGNORECASE
)
_PYTEST_SUMMARY_RE: re.Pattern[str] = re.compile(
    r"\d+ (?:passed|failed|error)", re.IGNORECASE
)
_PYTEST_ITEM_RE: re.Pattern[str] = re.compile(
    r"(?:PASSED|FAILED|ERROR)\s+tests?/", re.IGNORECASE
)
_FILE_LS_RE: re.Pattern[str] = re.compile(
    r"^(?:total \d+|[-drwxlsp]{10})", re.MULTILINE
)
_FILE_FIND_RE: re.Pattern[str] = re.compile(r"^\.?/[^\n]+\.[a-zA-Z0-9]+$", re.MULTILINE)
_BUILD_NPM_RE: re.Pattern[str] = re.compile(
    r"npm (?:warn|error|info)|added \d+ packages", re.IGNORECASE
)
_BUILD_PIP_RE: re.Pattern[str] = re.compile(
    r"(?:Collecting|Installing|Successfully installed)", re.IGNORECASE
)
_BUILD_MAKE_RE: re.Pattern[str] = re.compile(
    r"^(?:make|gcc|g\+\+|clang|cargo)\[", re.MULTILINE
)


# ── Public classifier ─────────────────────────────────────────────────────────


def classify(content: str) -> CommandType:
    """Classify tool result content by the command that produced it.

    Args:
        content: Raw tool result text.

    Returns:
        The best-matching :class:`CommandType` for *content*.
    """
    if _GIT_DIFF_RE.search(content) or _GIT_DIFF_PATCH_RE.search(content):
        return CommandType.GIT_DIFF
    if _GIT_LOG_COMMIT_RE.search(content):
        return CommandType.GIT_LOG
    if _GIT_STATUS_RE.search(content):
        return CommandType.GIT_STATUS
    if _PYTEST_HEADER_RE.search(content) or (
        _PYTEST_SUMMARY_RE.search(content) and _PYTEST_ITEM_RE.search(content)
    ):
        return CommandType.PYTEST
    # --oneline git log: many short lines each starting with a short hash
    if _GIT_LOG_ONELINE_RE.search(content) and len(content.splitlines()) > 3:
        return CommandType.GIT_LOG
    if _FILE_LS_RE.search(content) or _FILE_FIND_RE.search(content):
        return CommandType.FILE_TREE
    if (
        _BUILD_NPM_RE.search(content)
        or _BUILD_PIP_RE.search(content)
        or _BUILD_MAKE_RE.search(content)
    ):
        return CommandType.BUILD
    return CommandType.GENERIC


# ── Domain-specific summarizers ───────────────────────────────────────────────


def _summarize_git_diff(content: str) -> str:
    """Keep file headers, hunk headers, and the first N changed lines per hunk."""
    lines = content.splitlines()
    kept: list[str] = []
    hunk_lines = 0
    file_count = 0

    for line in lines:
        if line.startswith("diff --git"):
            file_count += 1
            kept.append(line)
            hunk_lines = 0
        elif line.startswith(
            ("--- ", "+++ ", "index ", "new file", "deleted file", "rename ")
        ):
            kept.append(line)
        elif line.startswith("@@"):
            kept.append(line)
            hunk_lines = 0
        elif line.startswith(("+", "-", " ")):
            if hunk_lines < _MAX_DIFF_HUNK_LINES:
                kept.append(line)
            elif hunk_lines == _MAX_DIFF_HUNK_LINES:
                kept.append("... [hunk truncated by Traject]")
            hunk_lines += 1
        else:
            kept.append(line)

    summary = "\n".join(kept)
    chars_removed = len(content) - len(summary)
    if chars_removed > 0:
        summary += f"\n[Traject: {file_count} file(s), {chars_removed} chars removed]"
    return summary


def _summarize_git_log(content: str) -> str:
    """Reduce git log to commit hash + first subject line per entry."""
    lines = content.splitlines()
    entries: list[str] = []
    current_hash: str | None = None

    for line in lines:
        if _GIT_LOG_COMMIT_RE.match(line):
            # Full log: "commit <40-char hash>"
            current_hash = line.split()[1][:7]
            continue
        if current_hash is not None:
            if line.startswith(("Author:", "Date:", "Merge:")):
                continue
            msg = line.strip()
            if msg:
                entries.append(f"{current_hash} {msg}")
                current_hash = None
        elif _GIT_LOG_ONELINE_RE.match(line):
            entries.append(line)

        if len(entries) >= _MAX_LOG_COMMITS:
            break

    if not entries:
        return "\n".join(lines[:_MAX_LOG_COMMITS]) + "\n[Traject: log truncated]"

    total = len([ln for ln in lines if ln.strip()])
    summary = "\n".join(entries)
    if total > len(entries):
        omitted = total - len(entries)
        summary += f"\n[Traject: {omitted} additional entries omitted]"
    return summary


def _summarize_pytest(content: str) -> str:
    """Compress pytest output while preserving all fact-bearing failure detail.

    The verbose, low-value part of a pytest run is the per-test PASSED line
    listing during collection. The load-bearing parts — which carry file:line
    references, error/exception types, and failing test names — live in the
    FAILURES section, the short-summary section, and the final result line.
    This keeps all three verbatim and drops only the collection noise.
    """
    lines = content.splitlines()
    kept: list[str] = []
    in_failures = False
    in_summary = False

    for line in lines:
        low = line.lower()
        # Section toggles.
        if re.match(r"=+ FAILURES =+", line):
            in_failures = True
            in_summary = False
            kept.append(line)
            continue
        if re.match(r"=+ short test summary", line, re.IGNORECASE):
            in_failures = False
            in_summary = True
            kept.append(line)
            continue
        # A new banner line ends the current detail section.
        if line.startswith("=") and (in_failures or in_summary):
            # The final "N passed, M failed in Xs" banner is itself valuable.
            if re.search(r"\d+ (?:passed|failed|error)", low):
                kept.append(line)
            in_failures = False
            in_summary = False
            continue
        if in_failures or in_summary:
            kept.append(line)
            continue
        # Outside detail sections: keep explicit FAILED/ERROR lines and the
        # final result banner; drop PASSED collection noise.
        is_failed_line = re.match(r"(?:FAILED|ERROR) ", line) is not None
        is_result_banner = line.startswith("=") and bool(
            re.search(r"\d+ (?:passed|failed|error)", low)
        )
        if is_failed_line or is_result_banner:
            kept.append(line)

    if not kept:
        non_empty = [ln for ln in lines if ln.strip()]
        head = non_empty[:5]
        tail = non_empty[-3:] if len(non_empty) > 8 else []
        kept = head + (["..."] if tail else []) + tail

    return "\n".join(kept)


def _summarize_file_tree(content: str) -> str:
    """Keep the first N file listing entries and count the rest."""
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if len(lines) <= _MAX_TREE_ENTRIES:
        return content
    kept = lines[:_MAX_TREE_ENTRIES]
    omitted = len(lines) - _MAX_TREE_ENTRIES
    return "\n".join(kept) + f"\n[Traject: {omitted} more entries omitted]"


def _summarize_build(content: str) -> str:
    """Keep error/warning lines and the final status line from build output."""
    lines = content.splitlines()
    important: list[str] = []
    last_nonempty: str | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        last_nonempty = line
        if any(
            kw in stripped.lower()
            for kw in ("error", "failed", "failure", "fatal", "warning:")
        ):
            important.append(line)

    result: list[str] = list(important)
    if last_nonempty and (not result or result[-1] != last_nonempty):
        result.append(last_nonempty)

    if not result:
        non_empty = [ln for ln in lines if ln.strip()]
        return "\n".join(non_empty[:10])

    return "\n".join(result)


def _summarize_generic(content: str) -> str:
    """Generic prose-extraction fallback (mirrors the original engine summarizer)."""
    has_sep = "/" in content or "\\" in content
    has_code_ext = any(ext in content for ext in _CODE_EXTENSIONS)

    summary_body: str

    if has_sep and has_code_ext:
        path_lines: list[str] = []
        for line in content.splitlines():
            s = line.strip()
            if ("/" in s or "\\" in s) and any(ext in s for ext in _CODE_EXTENSIONS):
                path_lines.append(s)
                if len(path_lines) >= 5:
                    break
        summary_body = (
            ("\n".join(path_lines) + "\n...") if path_lines else content[:100]
        )

    elif "Error:" in content or "Exception:" in content or "Traceback" in content:
        lines = content.splitlines()
        error_idx: int | None = None
        for idx, line in enumerate(lines):
            if "Error:" in line or "Exception:" in line or "Traceback" in line:
                error_idx = idx
                break
        if error_idx is not None:
            summary_body = "\n".join(lines[error_idx : error_idx + 3])
        else:
            summary_body = content[:100]

    elif "```" in content:
        block_lines: list[str] = []
        inside = False
        for line in content.splitlines():
            if line.strip().startswith("```"):
                inside = not inside
                continue
            if inside:
                block_lines.append(line)
                if len(block_lines) >= 3:
                    break
        summary_body = "\n".join(block_lines) if block_lines else content[:100]

    else:
        sentences = [
            s.strip() for s in re.split(r"(?<=[.!?])\s+", content.strip()) if s.strip()
        ]
        if len(sentences) <= 1:
            summary_body = sentences[0] if sentences else content[:100]
        else:
            summary_body = sentences[0] + " " + sentences[-1]

    if len(summary_body) > _SUMMARY_MAX_CHARS:
        summary_body = summary_body[:_SUMMARY_MAX_CHARS]

    chars_removed = len(content) - len(summary_body)
    return f"{summary_body} [summarized by Traject, {chars_removed} chars removed]"


# ── Public API ────────────────────────────────────────────────────────────────


def summarize(content: str) -> str:
    """Summarize tool result content using the appropriate domain compressor.

    Classifies *content* and delegates to the matching mini-compressor.

    Args:
        content: Raw tool result text.

    Returns:
        Compressed representation of *content*.  The inflation guard in the
        engine ensures this is never substituted when it is not shorter.
    """
    cmd_type = classify(content)
    if cmd_type == CommandType.GIT_DIFF:
        return _summarize_git_diff(content)
    if cmd_type == CommandType.GIT_LOG:
        return _summarize_git_log(content)
    if cmd_type == CommandType.GIT_STATUS:
        return content  # usually short and dense; keep verbatim
    if cmd_type == CommandType.PYTEST:
        return _summarize_pytest(content)
    if cmd_type == CommandType.FILE_TREE:
        return _summarize_file_tree(content)
    if cmd_type == CommandType.BUILD:
        return _summarize_build(content)
    return _summarize_generic(content)
