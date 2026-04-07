import pytest
import httpx
import respx
from proxy.streaming import stream_from_ollama


@pytest.mark.asyncio
@respx.mock
async def test_stream_yields_ndjson_lines():
    ndjson = (
        '{"message":{"role":"assistant","content":"Hello"},"done":false}\n'
        '{"message":{"role":"assistant","content":"!"},"done":true}\n'
    )
    respx.post("http://mock-ollama:11434/api/chat").mock(
        return_value=httpx.Response(200, text=ndjson)
    )

    chunks = []
    async for chunk in stream_from_ollama(
        "http://mock-ollama:11434", "/api/chat",
        {"model": "hermes3", "messages": []}
    ):
        chunks.append(chunk.decode())

    assert len(chunks) == 2
    assert '"done":false' in chunks[0]
    assert '"done":true' in chunks[1]


@pytest.mark.asyncio
@respx.mock
async def test_stream_skips_empty_lines():
    ndjson = (
        '{"message":{"role":"assistant","content":"Hi"},"done":false}\n'
        '\n'
        '{"done":true}\n'
    )
    respx.post("http://mock-ollama:11434/api/chat").mock(
        return_value=httpx.Response(200, text=ndjson)
    )

    chunks = []
    async for chunk in stream_from_ollama(
        "http://mock-ollama:11434", "/api/chat",
        {"model": "hermes3", "messages": []}
    ):
        chunks.append(chunk.decode())

    assert len(chunks) == 2


@pytest.mark.asyncio
@respx.mock
async def test_stream_forces_stream_true_in_payload():
    captured_body = {}

    def capture(request):
        import json
        captured_body.update(json.loads(request.content))
        return httpx.Response(200, text='{"done":true}\n')

    respx.post("http://mock-ollama:11434/api/chat").mock(side_effect=capture)

    async for _ in stream_from_ollama(
        "http://mock-ollama:11434", "/api/chat",
        {"model": "hermes3", "messages": [], "stream": False}
    ):
        pass

    assert captured_body["stream"] is True
