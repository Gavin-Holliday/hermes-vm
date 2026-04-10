"""Tests for PollService parsing and validation."""
import pytest

from services.poll import PollService


class TestPollServiceParseAndValidate:
    """PollService.parse_and_validate() tests."""

    def test_valid_poll_minimal(self):
        """Parse poll with minimum required parts."""
        data, error = PollService.parse_and_validate("Should we adopt Rust? | Yes | No")
        assert error is None
        assert data is not None
        assert data.question == "Should we adopt Rust?"
        assert data.options == ["Yes", "No"]

    def test_valid_poll_many_options(self):
        """Parse poll with up to 10 options."""
        args = "Favorite language? | Python | Go | Rust | JS | Java | C++ | Ruby | PHP | Zig | Kotlin"
        data, error = PollService.parse_and_validate(args)
        assert error is None
        assert data is not None
        assert len(data.options) == 10

    def test_poll_max_10_options_enforced(self):
        """Poll is capped at 10 options, extras discarded."""
        parts = ["Question?"] + [f"Option{i}" for i in range(15)]
        args = " | ".join(parts)
        data, error = PollService.parse_and_validate(args)
        assert error is None
        assert len(data.options) == 10

    def test_question_truncated_to_300_chars(self):
        """Question is truncated to 300 characters."""
        long_question = "a" * 500
        args = f"{long_question} | Yes | No"
        data, error = PollService.parse_and_validate(args)
        assert error is None
        assert len(data.question) == 300

    def test_options_truncated_to_55_chars_each(self):
        """Each option is truncated to 55 characters."""
        long_option = "x" * 100
        args = f"Question? | {long_option} | {long_option}"
        data, error = PollService.parse_and_validate(args)
        assert error is None
        assert all(len(opt) <= 55 for opt in data.options)

    def test_too_few_parts_rejected(self):
        """Less than 3 parts (question + 2 options) rejected."""
        data, error = PollService.parse_and_validate("Question? | Option1")
        assert error is not None
        assert data is None
        assert "2 options required" in error

    def test_only_question_rejected(self):
        """Single part (question only) rejected."""
        data, error = PollService.parse_and_validate("Question?")
        assert error is not None
        assert data is None

    def test_empty_question_rejected(self):
        """Empty question is rejected."""
        data, error = PollService.parse_and_validate(" | Yes | No")
        assert error is not None
        assert data is None

    def test_whitespace_only_question_rejected(self):
        """Whitespace-only question is rejected."""
        data, error = PollService.parse_and_validate("   |   | Yes")
        assert error is not None
        assert data is None

    def test_whitespace_stripped_from_parts(self):
        """Leading/trailing whitespace stripped from question and options."""
        data, error = PollService.parse_and_validate(
            "  Question?  |  Option 1  |  Option 2  "
        )
        assert error is None
        assert data.question == "Question?"
        assert data.options == ["Option 1", "Option 2"]

    def test_empty_option_preserved(self):
        """Empty options are included in results (Discord will reject them)."""
        data, error = PollService.parse_and_validate("Question? |  | No")
        assert error is None
        assert "" in data.options


