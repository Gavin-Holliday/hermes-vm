"""PollService — parsing and validation for Discord polls."""
import datetime
from dataclasses import dataclass


@dataclass
class PollData:
    """Validated poll data ready for Discord API."""
    question: str
    options: list[str]


class PollService:
    """Service for parsing, validating, and constructing Discord polls."""

    @staticmethod
    def parse_and_validate(args: str) -> tuple[PollData | None, str | None]:
        """
        Parse poll args into PollData.

        Args:
            args: Pipe-separated string: "question | option1 | option2 | ..."

        Returns:
            (PollData, None) on success
            (None, error_message) on failure
        """
        parts = [p.strip() for p in args.split("|")]

        if len(parts) < 3:
            return (
                None,
                "Minimum 2 options required. Usage: `question | option1 | option2 [| ...]`",
            )

        question = parts[0][:300]
        options = [opt[:55] for opt in parts[1:11]]  # max 10 options, 55 chars each

        if not question or len(options) < 2:
            return None, "Question and at least 2 options required."

        return PollData(question, options), None

    @staticmethod
    def create_discord_poll(poll_data: PollData):
        """
        Build a Discord.Poll object from parsed data.

        Args:
            poll_data: Validated poll data

        Returns:
            discord.Poll ready to send
        """
        import discord

        poll = discord.Poll(
            question=poll_data.question,
            duration=datetime.timedelta(hours=24),
        )
        for opt in poll_data.options:
            poll.add_answer(text=opt)
        return poll
