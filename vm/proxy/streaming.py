import httpx
from typing import AsyncGenerator


async def stream_from_ollama(
    ollama_host: str,
    endpoint: str,
    payload: dict,
) -> AsyncGenerator[bytes, None]:
    """
    Stream NDJSON response from Ollama. Yields each non-empty line as bytes.
    Forces stream=True in the payload regardless of what the caller passed.
    """
    forced_payload = {**payload, "stream": True}

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{ollama_host}{endpoint}",
            json=forced_payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    yield (line + "\n").encode()
