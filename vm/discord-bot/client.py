import json
import httpx


async def stream_response(proxy_url: str, model: str, messages: list[dict]):
    """
    Async generator that yields text chunks from hermes-proxy /api/chat.

    The proxy returns NDJSON (application/x-ndjson). Each line is a JSON object:
      {"model": "...", "message": {"role": "assistant", "content": "token"}, "done": false}
    The final line has "done": true. Handles both multi-line streaming and single-line
    non-streaming responses (tool-call results).
    """
    payload = {"model": model, "messages": messages, "stream": True}
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{proxy_url}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                if chunk.get("done"):
                    return
