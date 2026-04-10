"""EventService — parsing and validation for Discord server events."""
import datetime
from dataclasses import dataclass


@dataclass
class EventData:
    """Validated event data ready for Discord API."""
    name: str
    description: str
    start_time: datetime.datetime


class EventService:
    """Service for parsing and validating event arguments."""

    @staticmethod
    def parse_and_validate(args: str) -> tuple[EventData | None, str | None]:
        """
        Parse event args into EventData.

        Args:
            args: Pipe-separated string: "name | description | YYYY-MM-DD HH:MM"

        Returns:
            (EventData, None) on success
            (None, error_message) on failure
        """
        parts = [p.strip() for p in args.split("|")]

        if len(parts) < 1 or not parts[0]:
            return None, "Event name required."

        name = parts[0][:100]
        description = parts[1][:1000] if len(parts) > 1 else ""

        # Default to 1 hour from now
        start_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            hours=1
        )

        # Parse custom start time if provided
        if len(parts) > 2 and parts[2]:
            try:
                start_time = datetime.datetime.fromisoformat(parts[2]).replace(
                    tzinfo=datetime.timezone.utc
                )
            except ValueError:
                return None, "Invalid date format. Use: YYYY-MM-DD HH:MM"

        return EventData(name, description, start_time), None
