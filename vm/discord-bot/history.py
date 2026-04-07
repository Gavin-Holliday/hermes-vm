MAX_HISTORY = 20


class ChannelHistory:
    def __init__(self, max_messages: int = MAX_HISTORY) -> None:
        self._max = max_messages
        self._history: dict[int, list[dict]] = {}

    def get(self, channel_id: int) -> list[dict]:
        return list(self._history.get(channel_id, []))

    def add(self, channel_id: int, role: str, content: str) -> None:
        msgs = self._history.setdefault(channel_id, [])
        msgs.append({"role": role, "content": content})
        if len(msgs) > self._max:
            self._history[channel_id] = msgs[-self._max:]

    def clear(self, channel_id: int) -> None:
        self._history.pop(channel_id, None)
