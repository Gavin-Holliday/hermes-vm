"""Concrete implementations of injectable state objects."""
import collections
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord


class ModelState:
    """Mutable model selection state — satisfies IModelState."""

    def __init__(
        self,
        default: str,
        allowed: list[str],
        aliases: dict[str, str],
    ) -> None:
        self._current = default
        self._allowed = allowed
        self._aliases = aliases

    @property
    def current(self) -> str:
        return self._current

    @property
    def allowed(self) -> list[str]:
        return self._allowed

    @property
    def aliases(self) -> dict[str, str]:
        return self._aliases

    def resolve(self, name: str) -> str | None:
        """Expand alias, return None if the resolved name is not in allowed."""
        resolved = self._aliases.get(name, name)
        return resolved if resolved in self._allowed else None

    def switch(self, name: str) -> str:
        """Switch active model. Raises ValueError if not permitted."""
        resolved = self.resolve(name)
        if resolved is None:
            raise ValueError(f"Model '{name}' is not permitted")
        self._current = resolved
        return resolved


class MessageTracker:
    """Tracks recent bot messages per channel — satisfies IMessageTracker."""

    def __init__(self, maxlen: int = 20) -> None:
        self._queues: dict[int, collections.deque] = {}

    def track(self, msg: "discord.Message") -> None:
        q = self._queues.setdefault(msg.channel.id, collections.deque(maxlen=20))
        q.append(msg)

    def last(self, channel_id: int) -> "discord.Message | None":
        q = self._queues.get(channel_id)
        return q[-1] if q else None

    def pop_recent(self, channel_id: int, n: int) -> list:
        q = self._queues.get(channel_id)
        if not q:
            return []
        msgs = []
        while q and len(msgs) < n:
            msgs.append(q.pop())
        return msgs
