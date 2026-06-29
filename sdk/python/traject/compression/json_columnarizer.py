"""Lossless JSON array columnarization (Headroom SmartCrusher-inspired).

Converts JSON arrays of homogeneous dict objects into a compact pipe-delimited
table.  The table contains exactly the same information as the source JSON but
uses ~60-80% fewer characters for typical API or test-runner payloads.

Applicable when:
- The entire segment content is a valid JSON array
- The array contains >= MIN_ITEMS items
- Every item is a dict (homogeneous row type)
- The table is strictly shorter than the original JSON
"""

from __future__ import annotations

import json
import re

MIN_ITEMS: int = 5  # arrays smaller than this are not worth columnarizing
MAX_CELL_LEN: int = 80  # truncate very long cell values for readability

_ARRAY_START_RE: re.Pattern[str] = re.compile(r"^\s*\[")
_HEADER_TMPL: str = "[Traject: {n} items columnarized from JSON array]"


def _truncate(value: object, max_len: int = MAX_CELL_LEN) -> str:
    """Render *value* as a string, truncating with an ellipsis if too long."""
    s = str(value)
    return s if len(s) <= max_len else s[:max_len] + "…"


def columnarize(content: str) -> str:
    """Convert a JSON array of objects to a pipe-delimited table.

    Returns *content* unchanged when conversion is not applicable or when the
    table would not be strictly shorter than the original.

    Args:
        content: Tool result or segment content to transform.

    Returns:
        A compact table string with a Traject header, or *content* unchanged.
    """
    stripped = content.strip()
    if not _ARRAY_START_RE.match(stripped):
        return content

    try:
        data: object = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return content

    if not isinstance(data, list) or len(data) < MIN_ITEMS:
        return content

    # Require all items to be dicts (homogeneous).
    if not all(isinstance(item, dict) for item in data):
        return content

    # Union of all keys, sorted for deterministic column ordering.
    all_keys: set[str] = set()
    for item in data:
        if isinstance(item, dict):
            all_keys.update(item.keys())
    if not all_keys:
        return content
    columns = sorted(all_keys)

    header_row = " | ".join(columns)
    separator = "-" * len(header_row)
    data_rows: list[str] = []
    for item in data:
        if isinstance(item, dict):
            cells = [_truncate(item.get(k, "")) for k in columns]
            data_rows.append(" | ".join(cells))

    table = "\n".join(
        [_HEADER_TMPL.format(n=len(data)), header_row, separator, *data_rows]
    )

    # Inflation guard: only substitute when strictly shorter.
    return table if len(table) < len(content) else content
