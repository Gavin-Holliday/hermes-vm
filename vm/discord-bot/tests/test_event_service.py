"""Tests for EventService parsing and validation."""
import datetime

import pytest

from services.event import EventService


class TestEventServiceParseAndValidate:
    """EventService.parse_and_validate() tests."""

    def test_valid_minimal_event(self):
        """Parse event with just name."""
        data, error = EventService.parse_and_validate("Team Meeting")
        assert error is None
        assert data is not None
        assert data.name == "Team Meeting"
        assert data.description == ""
        assert data.start_time > datetime.datetime.now(datetime.timezone.utc)

    def test_valid_event_with_description(self):
        """Parse event with name and description."""
        data, error = EventService.parse_and_validate(
            "Team Meeting | Quarterly planning"
        )
        assert error is None
        assert data is not None
        assert data.name == "Team Meeting"
        assert data.description == "Quarterly planning"

    def test_valid_event_with_custom_time(self):
        """Parse event with custom datetime."""
        data, error = EventService.parse_and_validate(
            "Team Meeting | Q1 Planning | 2026-05-15 14:30"
        )
        assert error is None
        assert data is not None
        assert data.name == "Team Meeting"
        assert data.description == "Q1 Planning"
        assert data.start_time == datetime.datetime(
            2026, 5, 15, 14, 30, tzinfo=datetime.timezone.utc
        )

    def test_name_truncated_to_100_chars(self):
        """Event name is truncated to 100 characters."""
        long_name = "a" * 200
        data, error = EventService.parse_and_validate(long_name)
        assert error is None
        assert len(data.name) == 100

    def test_description_truncated_to_1000_chars(self):
        """Event description is truncated to 1000 characters."""
        long_desc = "a" * 2000
        data, error = EventService.parse_and_validate(f"Event | {long_desc}")
        assert error is None
        assert len(data.description) == 1000

    def test_empty_name_rejected(self):
        """Empty event name is rejected."""
        data, error = EventService.parse_and_validate("")
        assert error is not None
        assert data is None
        assert "name" in error.lower()

    def test_whitespace_only_name_rejected(self):
        """Whitespace-only event name is rejected."""
        data, error = EventService.parse_and_validate("   |   ")
        assert error is not None
        assert data is None

    def test_invalid_datetime_format(self):
        """Invalid datetime format returns error."""
        data, error = EventService.parse_and_validate(
            "Event | Desc | 2026/05/15 14:30"
        )
        assert error is not None
        assert data is None
        assert "Invalid date format" in error

    def test_trailing_pipes_ignored(self):
        """Extra trailing pipes are ignored."""
        data, error = EventService.parse_and_validate("Event | Desc | 2026-05-15 14:30 | | ")
        assert error is None
        assert data is not None
        assert data.name == "Event"

    def test_whitespace_stripped_from_parts(self):
        """Leading/trailing whitespace is stripped from parts."""
        data, error = EventService.parse_and_validate(
            "  Event  |  Description  |  2026-05-15 14:30  "
        )
        assert error is None
        assert data.name == "Event"
        assert data.description == "Description"
