"""Unit tests for traject.compression.prose_filter."""

from __future__ import annotations

from traject.compression.prose_filter import strip_filler


class TestStripFiller:
    def test_removes_certainly_opener(self) -> None:
        result = strip_filler("Certainly! Let me look at the file.")
        assert result == "Let me look at the file."

    def test_removes_absolutely_opener(self) -> None:
        result = strip_filler("Absolutely! Here is the fix.")
        assert result == "Here is the fix."

    def test_removes_of_course_opener(self) -> None:
        result = strip_filler("Of course! I'll run the tests.")
        assert result == "I'll run the tests."

    def test_removes_no_problem_opener(self) -> None:
        result = strip_filler("No problem. Moving on.")
        assert result == "Moving on."

    def test_removes_let_me_know_closer(self) -> None:
        result = strip_filler("Here is the fix. Let me know if you have any questions!")
        assert "Let me know" not in result
        assert "Here is the fix" in result

    def test_removes_i_hope_this_helps(self) -> None:
        result = strip_filler("Done. I hope this helps!")
        assert "I hope this helps" not in result
        assert "Done" in result

    def test_removes_dont_hesitate_closer(self) -> None:
        result = strip_filler("Fixed it. Don't hesitate to ask if anything is unclear.")
        assert "Don't hesitate" not in result

    def test_removes_worth_noting(self) -> None:
        result = strip_filler("It's worth noting that this function is recursive.")
        assert "worth noting" not in result
        assert "recursive" in result

    def test_removes_important_to_note(self) -> None:
        result = strip_filler("It is important to note that the list is 1-indexed.")
        assert "important to note" not in result
        assert "1-indexed" in result

    def test_removes_please_note_that(self) -> None:
        result = strip_filler("Please note that the API requires authentication.")
        assert "Please note that" not in result
        assert "authentication" in result

    def test_removes_as_you_can_see(self) -> None:
        result = strip_filler("As you can see, the test fails on line 42.")
        assert "As you can see" not in result
        assert "line 42" in result

    def test_removes_as_mentioned(self) -> None:
        result = strip_filler("As mentioned earlier, the bug is in the parser.")
        assert "As mentioned" not in result
        assert "parser" in result

    def test_removes_i_think(self) -> None:
        result = strip_filler("I think the issue is in the comparison.")
        assert "I think" not in result
        assert "issue" in result

    def test_removes_i_believe(self) -> None:
        result = strip_filler("I believe this approach is cleaner.")
        assert "I believe" not in result
        assert "cleaner" in result

    def test_skips_content_with_code_blocks(self) -> None:
        content = "Certainly!\n```python\nx = 1\n```"
        assert strip_filler(content) == content

    def test_never_returns_longer_string(self) -> None:
        inputs = [
            "Certainly! Let me check.",
            "Plain message with no filler.",
            "I think this is correct.",
            "",
        ]
        for content in inputs:
            result = strip_filler(content)
            assert len(result) <= len(content), (
                f"Result is longer than input for: {content!r}"
            )

    def test_idempotent(self) -> None:
        content = "Certainly! As you can see, the bug is on line 5."
        once = strip_filler(content)
        twice = strip_filler(once)
        assert once == twice

    def test_empty_string(self) -> None:
        assert strip_filler("") == ""

    def test_plain_message_unchanged(self) -> None:
        content = "The test fails because the list is not sorted."
        assert strip_filler(content) == content

    def test_case_insensitive_opener(self) -> None:
        result = strip_filler("certainly! Let me look.")
        assert "certainly" not in result.lower()
