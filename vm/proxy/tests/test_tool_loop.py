import asyncio
import pytest
import httpx
import respx
from proxy.tool_loop import run_tool_loop
from proxy.config import Config


@pytest.fixture
def cfg():
    return Config(
        ollama_host="http://mock-ollama:11434",
        searxng_url="http://mock-searxng:8080",
        allowed_models=["hermes3"],
        max_tool_rounds=10,
        tool_timeout_secs=30,
        system_prompt="You are Hermes.",
    )


@pytest.mark.asyncio
@respx.mock
async def test_loop_returns_plain_response_with_no_tool_calls(cfg):
    respx.post("http://mock-ollama:11434/api/chat").mock(
        return_value=httpx.Response(200, json={
            "message": {"role": "assistant", "content": "Paris is the capital of France."},
            "done": True,
        })
    )
    messages = [{"role": "user", "content": "What is the capital of France?"}]
    final_messages, had_tool_calls = await run_tool_loop(messages, "hermes3", cfg)

    assert had_tool_calls is False
    assert final_messages[-1]["content"] == "Paris is the capital of France."


@pytest.mark.asyncio
@respx.mock
async def test_loop_executes_tool_and_loops(cfg):
    call_count = 0

    def ollama_side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "web_search", "arguments": '{"query": "Python 3.13"}'}}
                    ],
                },
                "done": True,
            })
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": "Python 3.13 was released in 2024."},
            "done": True,
        })

    respx.post("http://mock-ollama:11434/api/chat").mock(side_effect=ollama_side_effect)
    respx.get("http://mock-searxng:8080/search").mock(
        return_value=httpx.Response(200, json={
            "results": [{"title": "Python 3.13", "url": "https://python.org", "content": "Released Oct 2024."}]
        })
    )

    messages = [{"role": "user", "content": "What's new in Python 3.13?"}]
    final_messages, had_tool_calls = await run_tool_loop(messages, "hermes3", cfg)

    assert had_tool_calls is True
    assert call_count == 2
    assert final_messages[-1]["content"] == "Python 3.13 was released in 2024."
    tool_msgs = [m for m in final_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "Python 3.13" in tool_msgs[0]["content"]


@pytest.mark.asyncio
@respx.mock
async def test_loop_raises_on_max_rounds_exceeded(cfg):
    respx.post("http://mock-ollama:11434/api/chat").mock(
        return_value=httpx.Response(200, json={
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "web_search", "arguments": '{"query": "loop"}'}}],
            },
            "done": True,
        })
    )
    respx.get("http://mock-searxng:8080/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    cfg_low = Config(
        ollama_host="http://mock-ollama:11434",
        searxng_url="http://mock-searxng:8080",
        allowed_models=["hermes3"],
        max_tool_rounds=3,
        tool_timeout_secs=30,
        system_prompt="You are Hermes.",
    )
    messages = [{"role": "user", "content": "search forever"}]
    with pytest.raises(RuntimeError, match="exceeded"):
        await run_tool_loop(messages, "hermes3", cfg_low)


@pytest.mark.asyncio
@respx.mock
async def test_loop_raises_on_timeout(cfg):
    async def slow_ollama(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": "done"},
            "done": True,
        })

    respx.post("http://mock-ollama:11434/api/chat").mock(side_effect=slow_ollama)

    cfg_fast = Config(
        ollama_host="http://mock-ollama:11434",
        searxng_url="http://mock-searxng:8080",
        allowed_models=["hermes3"],
        max_tool_rounds=10,
        tool_timeout_secs=1,
        system_prompt="You are Hermes.",
    )
    messages = [{"role": "user", "content": "hi"}]
    with pytest.raises(asyncio.TimeoutError):
        await run_tool_loop(messages, "hermes3", cfg_fast)
