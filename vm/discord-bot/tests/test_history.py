from history import ChannelHistory


def test_empty_channel_returns_empty_list():
    h = ChannelHistory()
    assert h.get(123) == []


def test_add_user_message():
    h = ChannelHistory()
    h.add(123, "user", "hello")
    assert h.get(123) == [{"role": "user", "content": "hello"}]


def test_add_multiple_messages_ordered():
    h = ChannelHistory()
    h.add(123, "user", "ping")
    h.add(123, "assistant", "pong")
    assert h.get(123) == [
        {"role": "user", "content": "ping"},
        {"role": "assistant", "content": "pong"},
    ]


def test_history_is_channel_isolated():
    h = ChannelHistory()
    h.add(111, "user", "channel 1")
    h.add(222, "user", "channel 2")
    assert h.get(111) == [{"role": "user", "content": "channel 1"}]
    assert h.get(222) == [{"role": "user", "content": "channel 2"}]


def test_history_capped_at_max_messages():
    h = ChannelHistory(max_messages=4)
    for i in range(6):
        h.add(1, "user", f"msg {i}")
    msgs = h.get(1)
    assert len(msgs) == 4
    assert msgs[0]["content"] == "msg 2"
    assert msgs[-1]["content"] == "msg 5"


def test_clear_removes_channel_history():
    h = ChannelHistory()
    h.add(123, "user", "hello")
    h.clear(123)
    assert h.get(123) == []


def test_clear_nonexistent_channel_is_noop():
    h = ChannelHistory()
    h.clear(999)
    assert h.get(999) == []


def test_get_returns_copy_not_reference():
    h = ChannelHistory()
    h.add(1, "user", "hello")
    msgs = h.get(1)
    msgs.append({"role": "user", "content": "injected"})
    assert len(h.get(1)) == 1
