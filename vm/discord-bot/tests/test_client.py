import json
import pytest
import respx
import httpx
from client import stream_response


def ndjson_lines(*chunks: dict) -> bytes:
    """Build a fake NDJSON response body."""
    return b"".join(json.dumps(c).encode() + b"\n" for c in chunks)


@pytest.mark.asyncio
async def test_stream_yields_content_chunks():
    chunks = [
        {"model": "hermes3", "message": {"role": "assistant", "content": "Hello"}, "done": False},
        {"model": "hermes3", "message": {"role": "assistant", "content": " world"}, "done": False},
        {"model": "hermes3", "message": {"role": "assistant", "content": ""}, "done": True},
    ]
    with respx.mock:
        respx.post("http://proxy:8000/api/chat").mock(
            return_value=httpx.Response(200, content=ndjson_lines(*chunks))
        )
        results = []
        async for chunk in stream_response("http://proxy:8000", "hermes3", [{"role": "user", "content": "hi"}]):
            results.append(chunk)
    assert results == ["Hello", " world"]


@pytest.mark.asyncio
async def test_stream_handles_single_json_response():
    single = {"model": "hermes3", "message": {"role": "assistant", "content": "Answer here"}, "done": True}
    with respx.mock:
        respx.post("http://proxy:8000/api/chat").mock(
            return_value=httpx.Response(200, content=ndjson_lines(single))
        )
        results = []
        async for chunk in stream_response("http://proxy:8000", "hermes3", []):
            results.append(chunk)
    assert results == ["Answer here"]


@pytest.mark.asyncio
async def test_stream_skips_empty_content():
    chunks = [
        {"model": "hermes3", "message": {"role": "assistant", "content": ""}, "done": False},
        {"model": "hermes3", "message": {"role": "assistant", "content": "Hi"}, "done": True},
    ]
    with respx.mock:
        respx.post("http://proxy:8000/api/chat").mock(
            return_value=httpx.Response(200, content=ndjson_lines(*chunks))
        )
        results = []
        async for chunk in stream_response("http://proxy:8000", "hermes3", []):
            results.append(chunk)
    assert results == ["Hi"]


@pytest.mark.asyncio
async def test_stream_raises_on_http_error():
    with respx.mock:
        respx.post("http://proxy:8000/api/chat").mock(
            return_value=httpx.Response(403, json={"error": "model not permitted"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in stream_response("http://proxy:8000", "hermes3", []):
                pass


@pytest.mark.asyncio
async def test_stream_sends_correct_payload():
    messages = [{"role": "user", "content": "hello"}]
    captured = {}

    def capture(request: httpx.Request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=ndjson_lines(
            {"model": "hermes3", "message": {"role": "assistant", "content": "hi"}, "done": True}
        ))

    with respx.mock:
        respx.post("http://proxy:8000/api/chat").mock(side_effect=capture)
        async for _ in stream_response("http://proxy:8000", "hermes3", messages):
            pass

    assert captured["body"]["model"] == "hermes3"
    assert captured["body"]["messages"] == messages
    assert captured["body"]["stream"] is True
