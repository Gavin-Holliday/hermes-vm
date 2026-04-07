import httpx
from typing import Any


SEARXNG_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current information. Use when the user asks about "
            "recent events, live data, or facts that may have changed since your "
            "training data cutoff."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string",
                }
            },
            "required": ["query"],
        },
    },
}


async def execute_web_search(query: str, searxng_url: str) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{searxng_url}/search",
            params={"q": query, "format": "json", "categories": "general"},
        )
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])[:5]
    if not results:
        return "No results found."

    lines = []
    for r in results:
        title = r.get("title", "")
        url = r.get("url", "")
        content = (r.get("content", "") or "")[:200]
        lines.append(f"**{title}**\n{url}\n{content}")

    return "\n\n".join(lines)


async def dispatch_tool(name: str, args: dict[str, Any], searxng_url: str) -> str:
    if name == "web_search":
        return await execute_web_search(args["query"], searxng_url)
    return f"Unknown tool: {name}"
