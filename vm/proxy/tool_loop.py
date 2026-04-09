import asyncio
import json
import httpx
from proxy.config import Config
from proxy.tools import ALL_TOOL_SCHEMAS, dispatch_tool


async def run_tool_loop(
    messages: list[dict],
    model: str,
    config: Config,
) -> tuple[list[dict], bool]:
    """
    Run non-streaming tool call loop against Ollama.

    Returns (final_messages, had_tool_calls).
    - had_tool_calls=False: no tools were used; caller may stream a fresh request.
    - had_tool_calls=True: final assistant message is in final_messages[-1].

    Raises RuntimeError if max_tool_rounds is exceeded.
    Raises asyncio.TimeoutError if the full loop exceeds tool_timeout_secs.
    """

    async def _loop() -> tuple[list[dict], bool]:
        current_messages = list(messages)
        had_tool_calls = False

        async with httpx.AsyncClient(timeout=60.0) as client:
            for _ in range(config.max_tool_rounds):
                resp = await client.post(
                    f"{config.ollama_host}/api/chat",
                    json={
                        "model": model,
                        "messages": current_messages,
                        "tools": ALL_TOOL_SCHEMAS,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                assistant_msg = data["message"]
                current_messages.append(assistant_msg)

                tool_calls = assistant_msg.get("tool_calls")
                if not tool_calls:
                    if had_tool_calls:
                        # Tool calls were made earlier; this is the final answer — keep it.
                        return current_messages, had_tool_calls
                    else:
                        # Pure probe with no tool calls — drop the assistant message so
                        # the caller can make a clean streaming request without a dangling
                        # assistant turn that would cause Ollama to return empty output.
                        return current_messages[:-1], had_tool_calls

                had_tool_calls = True
                for call in tool_calls:
                    fn_name = call["function"]["name"]
                    raw_args = call["function"]["arguments"]
                    # Ollama returns arguments as a JSON-encoded string, not a dict
                    fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    result = await dispatch_tool(fn_name, fn_args, config)
                    current_messages.append({"role": "tool", "content": result})

            raise RuntimeError(
                f"Tool call loop exceeded {config.max_tool_rounds} rounds"
            )

    return await asyncio.wait_for(_loop(), timeout=config.tool_timeout_secs)
