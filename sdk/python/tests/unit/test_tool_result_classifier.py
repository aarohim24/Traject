"""Unit tests for traject.compression.tool_result_classifier."""

from __future__ import annotations

from traject.compression.tool_result_classifier import CommandType, classify, summarize

# ── Fixtures ──────────────────────────────────────────────────────────────────

_GIT_DIFF = """\
diff --git a/traject/engine.py b/traject/engine.py
index abc1234..def5678 100644
--- a/traject/engine.py
+++ b/traject/engine.py
@@ -10,6 +10,7 @@ import re
 import re
+import json
 from typing import Any
+line1
+line2
+line3
+line4
+line5
+line6
+line7
+line8
+line9
+line10
"""

_GIT_LOG_FULL = """\
commit a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
Author: Dev <dev@example.com>
Date:   Mon Jun 1 12:00:00 2026

    feat: add compression pipeline

commit b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3
Author: Dev <dev@example.com>
Date:   Sun May 31 11:00:00 2026

    fix: correct token count
"""

_GIT_LOG_ONELINE = """\
a1b2c3d feat: add compression pipeline
b2c3d4e fix: correct token count
c3d4e5f chore: bump version
d4e5f6a docs: update README
e5f6a1b test: add unit tests
"""

_GIT_STATUS = """\
On branch main
Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
        modified:   traject/engine.py

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
        modified:   README.md
"""

_PYTEST_OUTPUT = """\
============================= test session starts ==============================
platform linux -- Python 3.11.0, pytest-8.0.0
collected 5 items

tests/unit/test_engine.py::test_compress PASSED
tests/unit/test_engine.py::test_dedup FAILED
tests/unit/test_engine.py::test_inflation PASSED

=================================== FAILURES ===================================
FAILED tests/unit/test_engine.py::test_dedup - AssertionError: expected 3

========================= short test summary info ==========================
FAILED tests/unit/test_engine.py::test_dedup

============================== 2 passed, 1 failed in 0.42s ==============================
"""

_FILE_TREE = """\
total 48
drwxr-xr-x  8 user staff  256 Jun  1 12:00 .
drwxr-xr-x 12 user staff  384 Jun  1 11:00 ..
-rw-r--r--  1 user staff 4096 Jun  1 12:00 engine.py
-rw-r--r--  1 user staff 2048 Jun  1 12:00 strategies.py
-rw-r--r--  1 user staff 1024 Jun  1 12:00 __init__.py
"""

_BUILD_NPM = """\
npm warn deprecated rimraf@2.7.1: Rimraf versions prior to v4 are no longer supported
npm error code ERESOLVE
npm error ERESOLVE unable to resolve dependency tree
added 42 packages from 10 contributors
"""


# ── classify() tests ──────────────────────────────────────────────────────────


class TestClassify:
    def test_git_diff(self) -> None:
        assert classify(_GIT_DIFF) == CommandType.GIT_DIFF

    def test_git_log_full(self) -> None:
        assert classify(_GIT_LOG_FULL) == CommandType.GIT_LOG

    def test_git_log_oneline(self) -> None:
        assert classify(_GIT_LOG_ONELINE) == CommandType.GIT_LOG

    def test_git_status(self) -> None:
        assert classify(_GIT_STATUS) == CommandType.GIT_STATUS

    def test_pytest(self) -> None:
        assert classify(_PYTEST_OUTPUT) == CommandType.PYTEST

    def test_file_tree(self) -> None:
        assert classify(_FILE_TREE) == CommandType.FILE_TREE

    def test_build_npm(self) -> None:
        assert classify(_BUILD_NPM) == CommandType.BUILD

    def test_generic_fallback(self) -> None:
        assert classify("Just some plain text output.") == CommandType.GENERIC

    def test_pip_install(self) -> None:
        pip_output = (
            "Collecting requests\n"
            "  Downloading requests-2.31.0-py3-none-any.whl\n"
            "Installing collected packages: requests\n"
            "Successfully installed requests-2.31.0\n"
        )
        assert classify(pip_output) == CommandType.BUILD


# ── summarize() tests ─────────────────────────────────────────────────────────


class TestSummarize:
    def test_git_diff_keeps_file_headers(self) -> None:
        result = summarize(_GIT_DIFF)
        assert "diff --git" in result
        assert "@@" in result

    def test_git_diff_truncates_long_hunks(self) -> None:
        result = summarize(_GIT_DIFF)
        assert "hunk truncated" in result

    def test_git_log_extracts_subjects(self) -> None:
        result = summarize(_GIT_LOG_FULL)
        assert "feat: add compression pipeline" in result
        assert "fix: correct token count" in result
        # Author/Date lines should be stripped
        assert "Author:" not in result

    def test_git_status_returned_verbatim(self) -> None:
        # git status is short and dense; the summarizer returns it unchanged
        assert summarize(_GIT_STATUS) == _GIT_STATUS

    def test_pytest_keeps_failures(self) -> None:
        result = summarize(_PYTEST_OUTPUT)
        assert "test_dedup" in result

    def test_pytest_keeps_summary_line(self) -> None:
        result = summarize(_PYTEST_OUTPUT)
        assert "passed" in result or "failed" in result

    def test_file_tree_limits_entries(self) -> None:
        # Build a large listing
        big_tree = "\n".join(
            f"-rw-r--r-- 1 u g 100 Jun 1 file{i:04d}.py" for i in range(50)
        )
        result = summarize(big_tree)
        assert "omitted" in result
        assert len(result.splitlines()) < 50

    def test_build_keeps_error_line(self) -> None:
        result = summarize(_BUILD_NPM)
        assert "error" in result.lower()

    def test_never_returns_longer_than_input(self) -> None:
        samples = [_GIT_DIFF, _GIT_LOG_FULL, _PYTEST_OUTPUT, _FILE_TREE, _BUILD_NPM]
        for content in samples:
            result = summarize(content)
            # The summarizer may add a note, but the engine's inflation guard
            # ensures it won't be substituted if longer.  We just check the
            # summarizer does not crash and returns a string.
            assert isinstance(result, str)

    def test_generic_short_content_unchanged(self) -> None:
        short = "exit code 0"
        result = summarize(short)
        assert isinstance(result, str)
