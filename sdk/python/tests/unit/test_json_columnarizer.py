"""Unit tests for traject.compression.json_columnarizer."""

from __future__ import annotations

import json

from traject.compression.json_columnarizer import MIN_ITEMS, columnarize


def _make_array(n: int) -> str:
    items = [{"id": i, "status": "ok", "value": i * 10} for i in range(n)]
    return json.dumps(items)


class TestColumnarize:
    def test_columnarizes_large_array(self) -> None:
        content = _make_array(10)
        result = columnarize(content)
        assert "id | status | value" in result
        assert "[Traject: 10 items columnarized" in result

    def test_returns_original_for_small_array(self) -> None:
        content = _make_array(MIN_ITEMS - 1)
        assert columnarize(content) == content

    def test_returns_original_for_non_array(self) -> None:
        content = json.dumps({"key": "value", "n": 42})
        assert columnarize(content) == content

    def test_returns_original_for_non_json(self) -> None:
        content = "this is not json"
        assert columnarize(content) == content

    def test_returns_original_for_array_of_primitives(self) -> None:
        content = json.dumps(list(range(10)))
        assert columnarize(content) == content

    def test_inflation_guard(self) -> None:
        # A tiny JSON array — columnarized form might be longer.
        items = [{"a": "b"} for _ in range(MIN_ITEMS)]
        content = json.dumps(items)
        result = columnarize(content)
        assert len(result) <= len(content)

    def test_result_contains_all_values(self) -> None:
        items = [
            {"name": "alice", "score": 95},
            {"name": "bob", "score": 87},
            {"name": "carol", "score": 92},
            {"name": "dave", "score": 78},
            {"name": "eve", "score": 88},
        ]
        content = json.dumps(items)
        result = columnarize(content)
        for item in items:
            assert str(item["name"]) in result
            assert str(item["score"]) in result

    def test_handles_mixed_keys(self) -> None:
        items = [
            {"a": 1, "b": 2},
            {"a": 3, "c": 4},
            {"b": 5, "c": 6},
            {"a": 7, "b": 8},
            {"a": 9, "c": 10},
        ]
        content = json.dumps(items)
        result = columnarize(content)
        # All keys should appear as columns
        assert "a" in result
        assert "b" in result
        assert "c" in result

    def test_result_is_shorter_for_large_array(self) -> None:
        content = _make_array(20)
        result = columnarize(content)
        assert len(result) < len(content)

    def test_whitespace_stripped_before_parse(self) -> None:
        content = "  \n" + _make_array(10) + "\n  "
        result = columnarize(content)
        assert "[Traject:" in result
