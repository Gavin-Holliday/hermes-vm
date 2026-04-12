import asyncio
import base64
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote as url_quote

import httpx

if TYPE_CHECKING:
    from proxy.config import Config


# ── Tool Schemas ───────────────────────────────────────────────────────────────


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


ALL_TOOL_SCHEMAS = [
    _schema(
        "web_search",
        "Search the web for current information. Use when the user asks about recent events, live data, or facts that may have changed since your training data cutoff.",
        {"query": {"type": "string", "description": "The search query string"}},
        ["query"],
    ),
    _schema(
        "web_extract",
        "Fetch and read the full text content of a URL. Use to read articles, docs, or any webpage after web_search finds relevant URLs.",
        {
            "url": {"type": "string", "description": "The URL to fetch"},
            "max_chars": {"type": "integer", "description": "Max characters to return (default 3000)"},
        },
        ["url"],
    ),
    _schema(
        "execute_code",
        "Execute Python code and return stdout/stderr. Use for calculations, data processing, or anything that benefits from code execution.",
        {
            "code": {"type": "string", "description": "Python code to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
        },
        ["code"],
    ),
    _schema(
        "terminal",
        "Run a shell command and return its output. Use for system operations, file management, or any shell task.",
        {
            "command": {"type": "string", "description": "Shell command to run"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
        },
        ["command"],
    ),
    _schema(
        "process",
        "List running processes or kill a process by PID.",
        {
            "action": {"type": "string", "description": "Action: 'list' or 'kill'"},
            "pid": {"type": "integer", "description": "Process ID (required for kill)"},
        },
        ["action"],
    ),
    _schema(
        "read_file",
        "Read the contents of a file from the persistent workspace.",
        {"path": {"type": "string", "description": "File path relative to workspace (e.g. 'notes.txt')"}},
        ["path"],
    ),
    _schema(
        "patch",
        "Write or overwrite a file in the persistent workspace. Creates directories as needed.",
        {
            "path": {"type": "string", "description": "File path relative to workspace"},
            "content": {"type": "string", "description": "Content to write"},
        },
        ["path", "content"],
    ),
    _schema(
        "memory",
        "Persistent key-value memory across conversations. Actions: 'set', 'get', 'delete', 'list'.",
        {
            "action": {"type": "string", "description": "Action: 'set', 'get', 'delete', or 'list'"},
            "key": {"type": "string", "description": "Memory key (required for set/get/delete)"},
            "value": {"type": "string", "description": "Value to store (required for set)"},
        },
        ["action"],
    ),
    _schema(
        "session_search",
        "Search through stored memories for information matching a query.",
        {"query": {"type": "string", "description": "Search query to match against memory keys and values"}},
        ["query"],
    ),
    _schema(
        "todo",
        "Manage a persistent todo/task list. Actions: 'add', 'list', 'done', 'delete', 'clear'.",
        {
            "action": {"type": "string", "description": "Action: 'add', 'list', 'done', 'delete', 'clear'"},
            "task": {"type": "string", "description": "Task description (required for add)"},
            "id": {"type": "integer", "description": "Task ID (required for done/delete)"},
        },
        ["action"],
    ),
    _schema(
        "vision_analyze",
        "Analyze an image using a vision model. Fetches the image from a URL and answers questions about it.",
        {
            "image_url": {"type": "string", "description": "URL of the image to analyze"},
            "question": {"type": "string", "description": "Question about the image (default: 'Describe this image in detail')"},
        },
        ["image_url"],
    ),
    _schema(
        "clarify",
        "Ask the user a clarifying question when more information is needed to complete a task well.",
        {"question": {"type": "string", "description": "The clarifying question to ask the user"}},
        ["question"],
    ),
    _schema(
        "discord_send",
        "Send a message to a Discord channel by name or ID.",
        {
            "channel": {"type": "string", "description": "Channel name or ID"},
            "content": {"type": "string", "description": "Message content (max 2000 chars)"},
        },
        ["channel", "content"],
    ),
    _schema(
        "discord_channels",
        "List all Discord channels the bot can see.",
        {},
        [],
    ),
    _schema(
        "discord_members",
        "List Discord server members (requires members intent to be enabled).",
        {},
        [],
    ),
    _schema(
        "discord_poll",
        "Create a native Discord poll in a channel.",
        {
            "channel": {"type": "string", "description": "Channel name or ID"},
            "question": {"type": "string", "description": "Poll question"},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Poll answer options (2–10 items)",
            },
            "duration_hours": {"type": "integer", "description": "Poll duration in hours (default 24)"},
        },
        ["channel", "question", "options"],
    ),
    _schema(
        "discord_react",
        "Add an emoji reaction to a Discord message. Omit message_id to react to the last bot message.",
        {
            "emoji": {"type": "string", "description": "Emoji to react with (e.g. '👍', '🔥', '✅')"},
            "message_id": {"type": "string", "description": "ID of the message to react to (optional)"},
            "channel": {"type": "string", "description": "Channel name or ID (optional, defaults to main channel)"},
        },
        ["emoji"],
    ),
    _schema(
        "discord_thread",
        "Create a thread from a Discord message. Omit message_id to thread from the last bot message.",
        {
            "name": {"type": "string", "description": "Thread name (max 100 chars)"},
            "message_id": {"type": "string", "description": "ID of the message to thread from (optional)"},
        },
        ["name"],
    ),
    _schema(
        "discord_pin",
        "Pin a Discord message. Omit message_id to pin the last bot message.",
        {
            "message_id": {"type": "string", "description": "ID of the message to pin (optional)"},
        },
        [],
    ),
    _schema(
        "discord_delete",
        "Delete recent bot messages. Omit message_id to delete by count.",
        {
            "message_id": {"type": "string", "description": "ID of specific message to delete (optional)"},
            "count": {"type": "integer", "description": "Number of recent bot messages to delete (default 1)"},
        },
        [],
    ),
    _schema(
        "discord_dm",
        "Send a direct message to a Discord server member by name or user ID.",
        {
            "user": {"type": "string", "description": "Member display name or user ID"},
            "content": {"type": "string", "description": "Message to send (max 2000 chars)"},
        },
        ["user", "content"],
    ),
    _schema(
        "discord_gif",
        "Search for a GIF and post it to a Discord channel.",
        {
            "query": {"type": "string", "description": "Search query for the GIF"},
            "channel": {"type": "string", "description": "Channel name or ID"},
        },
        ["query", "channel"],
    ),
    _schema(
        "discord_history",
        "Read recent chat history from a Discord channel. Returns messages with IDs, authors, content, and timestamps. Use before/after to navigate to a specific time window.",
        {
            "limit": {"type": "integer", "description": "Number of messages to fetch (default 25, max 100)"},
            "channel": {"type": "string", "description": "Channel name or ID (defaults to main channel)"},
            "before": {"type": "string", "description": "Fetch messages before this ISO timestamp (e.g. '2024-03-15T14:00:00')"},
            "after": {"type": "string", "description": "Fetch messages after this ISO timestamp (e.g. '2024-03-15T12:00:00')"},
        },
        [],
    ),
    _schema(
        "discord_fetch_message",
        "Fetch a specific Discord message by ID.",
        {
            "message_id": {"type": "string", "description": "ID of the message to fetch"},
            "channel": {"type": "string", "description": "Channel name or ID (defaults to main channel)"},
        },
        ["message_id"],
    ),
    _schema(
        "weather",
        "Get the current weather and today's forecast for a location using the free Open-Meteo API.",
        {
            "location": {"type": "string", "description": "City name or location (e.g. 'London', 'New York')"},
        },
        ["location"],
    ),
    _schema(
        "news",
        "Fetch top 5 news headlines from BBC News RSS. Optionally filter by topic (e.g. 'technology', 'science', 'health', 'world', 'business').",
        {
            "topic": {"type": "string", "description": "Optional topic category (e.g. 'technology', 'science', 'health', 'world', 'business')"},
        },
        [],
    ),
    _schema(
        "qr_code",
        "Generate a QR code for any text or URL and post it to a Discord channel as an embedded image.",
        {
            "text": {"type": "string", "description": "The text or URL to encode in the QR code"},
            "channel": {"type": "string", "description": "Channel name or ID to post the QR code to"},
        },
        ["text", "channel"],
    ),
    _schema(
        "discord_embed",
        "Send a rich Discord embed message to a channel with a title, description, optional color, fields, and thumbnail.",
        {
            "channel": {"type": "string", "description": "Channel name or ID"},
            "title": {"type": "string", "description": "Embed title"},
            "description": {"type": "string", "description": "Embed description/body text"},
            "color": {"type": "string", "description": "Embed color as hex string like '#5865F2' (default: Discord blurple)"},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": "string"},
                        "inline": {"type": "boolean"},
                    },
                    "required": ["name", "value"],
                },
                "description": "Optional list of embed fields with name, value, and optional inline flag",
            },
            "thumbnail": {"type": "string", "description": "Optional URL for embed thumbnail image"},
        },
        ["channel", "title", "description"],
    ),
    _schema(
        "remind",
        "Set a reminder that sends a message to a channel after a delay. Supports 'in X minutes/hours/days', ISO datetime strings.",
        {
            "message": {"type": "string", "description": "Reminder message to send"},
            "when": {"type": "string", "description": "When to send: 'in 30 minutes', 'in 2 hours', 'in 1 day', or ISO datetime like '2024-03-15T14:00:00'"},
            "channel": {"type": "string", "description": "Channel name or ID to send the reminder to (optional, defaults to main channel)"},
        },
        ["message", "when"],
    ),
    _schema(
        "ollama_models",
        "List all models currently available on the Ollama server with their sizes.",
        {},
        [],
    ),
    _schema(
        "github_list_issues",
        "List GitHub issues for a repository. Requires GITHUB_TOKEN to be set.",
        {
            "repo": {"type": "string", "description": "Repository in 'owner/repo' format (e.g. 'octocat/Hello-World')"},
            "state": {"type": "string", "description": "Issue state: 'open', 'closed', or 'all' (default: 'open')"},
        },
        ["repo"],
    ),
    _schema(
        "github_get_issue",
        "Get details of a specific GitHub issue. Requires GITHUB_TOKEN to be set.",
        {
            "repo": {"type": "string", "description": "Repository in 'owner/repo' format"},
            "number": {"type": "integer", "description": "Issue number"},
        },
        ["repo", "number"],
    ),
    _schema(
        "github_create_issue",
        "Create a new GitHub issue. Provide structured fields — the tool assembles the formatted body.",
        {
            "repo": {"type": "string", "description": "Repository in 'owner/repo' format"},
            "title": {"type": "string", "description": "Issue title"},
            "summary": {"type": "string", "description": "1-3 sentences describing the problem or feature request"},
            "context": {"type": "string", "description": "Why this matters, what triggered it, relevant background (optional)"},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of specific, measurable outcomes that define done (optional)",
            },
            "technical_notes": {"type": "string", "description": "Implementation hints, affected files, constraints (optional)"},
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Labels to apply — choose from: bug, feat, improvement, research, infra, docs",
            },
        },
        ["repo", "title", "summary"],
    ),
    _schema(
        "github_comment_issue",
        "Add a comment to a GitHub issue. Requires GITHUB_TOKEN to be set.",
        {
            "repo": {"type": "string", "description": "Repository in 'owner/repo' format"},
            "number": {"type": "integer", "description": "Issue number"},
            "body": {"type": "string", "description": "Comment text"},
        },
        ["repo", "number", "body"],
    ),
    _schema(
        "crypto_price",
        "Get the current price, 24h change %, and market cap for one or more cryptocurrencies using CoinGecko (no API key required).",
        {
            "symbols": {"type": "string", "description": "Comma-separated coin names/ids (e.g. 'bitcoin,ethereum,solana')"},
            "vs_currency": {"type": "string", "description": "Quote currency (default: 'usd')"},
        },
        ["symbols"],
    ),
    _schema(
        "crypto_trending",
        "Get the top 7 trending cryptocurrencies on CoinGecko right now.",
        {},
        [],
    ),
    _schema(
        "crypto_chart",
        "Get a price history summary (high, low, current, % change) for a cryptocurrency over a period of days.",
        {
            "symbol": {"type": "string", "description": "Coin name or id (e.g. 'bitcoin', 'ethereum')"},
            "days": {"type": "integer", "description": "Number of days of history (default 7, max 30)"},
        },
        ["symbol"],
    ),
    _schema(
        "stock_quote",
        "Get the current price, change, % change, volume, and market cap for a stock ticker using Yahoo Finance.",
        {
            "symbol": {"type": "string", "description": "Stock ticker symbol (e.g. 'AAPL', 'TSLA', 'MSFT')"},
        },
        ["symbol"],
    ),
    _schema(
        "stock_info",
        "Get company fundamentals for a stock ticker: sector, industry, P/E ratio, 52-week range, dividend yield, and description.",
        {
            "symbol": {"type": "string", "description": "Stock ticker symbol (e.g. 'AAPL', 'TSLA')"},
        },
        ["symbol"],
    ),
    _schema(
        "polymarket_markets",
        "Browse or search top Polymarket prediction markets by volume.",
        {
            "query": {"type": "string", "description": "Search query to filter markets (optional)"},
            "limit": {"type": "integer", "description": "Number of markets to return (default 10)"},
        },
        [],
    ),
    _schema(
        "polymarket_market",
        "Get full details of a specific Polymarket prediction market by its slug.",
        {
            "slug": {"type": "string", "description": "Market slug (the URL identifier for the market)"},
        },
        ["slug"],
    ),
    _schema(
        "deep_research",
        "Start comprehensive multi-round research on a topic. Runs in background, posts a cited Discord embed report when complete. Use for questions needing thorough sourcing rather than a quick web search.",
        {
            "topic": {"type": "string", "description": "Research topic or question"},
            "channel": {"type": "string", "description": "Discord channel name to post results to"},
            "researcher_model": {"type": "string", "description": "Override agent model (optional)"},
            "orchestrator_model": {"type": "string", "description": "Override orchestrator model (optional)"},
            "max_rounds": {"type": "integer", "description": "Override max research rounds (optional)"},
        },
        ["topic", "channel"],
    ),
    _schema(
        "deepdive",
        "Deep dive into a previously researched topic or specific URLs for more detailed analysis. Use after deep_research to go deeper on a specific aspect.",
        {
            "topic": {"type": "string", "description": "Topic title from a saved research report"},
            "channel": {"type": "string", "description": "Discord channel name to post results to"},
            "urls": {"type": "array", "items": {"type": "string"}, "description": "Optional seed URLs"},
        },
        ["topic", "channel"],
    ),
]

# Backwards compat alias used in tests / old imports
SEARXNG_TOOL_SCHEMA = ALL_TOOL_SCHEMAS[0]


# ── Helper: HTML stripper (stdlib only) ────────────────────────────────────────


class _HTMLStripper(HTMLParser):
    _SKIP_TAGS = {"script", "style", "noscript", "head"}
    _BLOCK_TAGS = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "article", "section"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._depth = 0  # nesting depth of skip tags

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP_TAGS:
            self._depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()


# ── Helper: safe workspace path ────────────────────────────────────────────────


def _safe_path(base: Path, rel: str) -> Path | None:
    """Return resolved path only if it stays inside base (prevents traversal)."""
    base_resolved = base.resolve()
    rel_clean = rel.lstrip("/")  # prevent absolute-path injection
    try:
        candidate = (base / rel_clean).resolve()
        candidate.relative_to(base_resolved)  # raises ValueError if outside
        return candidate
    except (ValueError, Exception):
        return None


def _workspace(config: "Config") -> Path:
    p = Path(config.workspace_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _data(config: "Config") -> Path:
    p = Path(config.data_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── Helper: JSON stores (memory, todo) ────────────────────────────────────────


def _load_store(config: "Config", filename: str) -> dict:
    path = _data(config) / filename
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def _save_store(config: "Config", filename: str, data: dict) -> None:
    (_data(config) / filename).write_text(json.dumps(data, indent=2))


# ── Tool implementations ───────────────────────────────────────────────────────


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


async def execute_web_extract(url: str, max_chars: int = 3000) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Hermes/1.0)"},
            )
            resp.raise_for_status()

        ctype = resp.headers.get("content-type", "")
        if "html" in ctype:
            stripper = _HTMLStripper()
            stripper.feed(resp.text)
            text = stripper.get_text()
        else:
            text = resp.text

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[truncated at {max_chars} chars]"
        return text or "(empty page)"
    except Exception as e:
        return f"Error fetching {url}: {e}"


async def execute_code(code: str, timeout: int = 30) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Execution timed out after {timeout}s"

        out = stdout.decode(errors="replace") if stdout else ""
        err = stderr.decode(errors="replace") if stderr else ""
        result = out
        if err:
            result += ("\n" if result else "") + f"[stderr]\n{err}"
        return result.strip() or f"(exit {proc.returncode}, no output)"
    except Exception as e:
        return f"Error: {e}"


async def execute_terminal(command: str, timeout: int = 30) -> str:
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Command timed out after {timeout}s"

        out = stdout.decode(errors="replace") if stdout else ""
        err = stderr.decode(errors="replace") if stderr else ""
        result = out
        if err:
            result += ("\n" if result else "") + f"[stderr]\n{err}"
        return result.strip() or f"(exit {proc.returncode})"
    except Exception as e:
        return f"Error: {e}"


async def execute_process(action: str, pid: int | None = None) -> str:
    if action == "list":
        return await execute_terminal("ps aux --no-headers 2>/dev/null || ps aux | tail -n +2 | head -30")
    if action == "kill":
        if pid is None:
            return "pid is required for kill"
        return await execute_terminal(f"kill {pid} && echo 'Sent SIGTERM to {pid}'")
    return f"Unknown action '{action}'. Use 'list' or 'kill'."


async def execute_read_file(path: str, config: "Config") -> str:
    base = _workspace(config)
    safe = _safe_path(base, path)
    if safe is None:
        return "Access denied: path is outside workspace"
    if not safe.exists():
        return f"File not found: {path}"
    try:
        content = safe.read_text(errors="replace")
        if len(content) > 5000:
            content = content[:5000] + "\n\n[truncated]"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


async def execute_patch(path: str, content: str, config: "Config") -> str:
    base = _workspace(config)
    safe = _safe_path(base, path)
    if safe is None:
        return "Access denied: path is outside workspace"
    try:
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content)
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def execute_memory(
    action: str, key: str | None, value: str | None, config: "Config"
) -> str:
    store = _load_store(config, "memory.json")

    if action == "set":
        if not key:
            return "key is required for set"
        store[key] = value or ""
        _save_store(config, "memory.json", store)
        return f"Stored: {key}"
    if action == "get":
        if not key:
            return "key is required for get"
        val = store.get(key)
        return str(val) if val is not None else f"No memory found for key: {key}"
    if action == "delete":
        if not key:
            return "key is required for delete"
        if key in store:
            del store[key]
            _save_store(config, "memory.json", store)
            return f"Deleted: {key}"
        return f"Key not found: {key}"
    if action == "list":
        if not store:
            return "Memory is empty"
        return "\n".join(f"- {k}: {str(v)[:100]}" for k, v in store.items())
    return f"Unknown action '{action}'. Use 'set', 'get', 'delete', or 'list'."


async def execute_session_search(query: str, config: "Config") -> str:
    store = _load_store(config, "memory.json")
    q = query.lower()
    matches = [
        (k, v) for k, v in store.items()
        if q in k.lower() or q in str(v).lower()
    ]
    if not matches:
        return f"No memories found matching: {query}"
    return "\n".join(f"- {k}: {str(v)[:200]}" for k, v in matches[:10])


async def execute_todo(
    action: str, task: str | None, task_id: int | None, config: "Config"
) -> str:
    store = _load_store(config, "todos.json")
    todos: list[dict] = store.get("todos", [])
    next_id: int = store.get("next_id", 1)

    if action == "add":
        if not task:
            return "task is required for add"
        todos.append({"id": next_id, "task": task, "done": False})
        store["todos"] = todos
        store["next_id"] = next_id + 1
        _save_store(config, "todos.json", store)
        return f"Added todo #{next_id}: {task}"
    if action == "list":
        if not todos:
            return "No todos"
        return "\n".join(
            f"{'✓' if t['done'] else '○'} #{t['id']}: {t['task']}" for t in todos
        )
    if action == "done":
        if task_id is None:
            return "id is required for done"
        for t in todos:
            if t["id"] == task_id:
                t["done"] = True
                store["todos"] = todos
                _save_store(config, "todos.json", store)
                return f"Marked #{task_id} as done"
        return f"Todo #{task_id} not found"
    if action == "delete":
        if task_id is None:
            return "id is required for delete"
        filtered = [t for t in todos if t["id"] != task_id]
        if len(filtered) == len(todos):
            return f"Todo #{task_id} not found"
        store["todos"] = filtered
        _save_store(config, "todos.json", store)
        return f"Deleted todo #{task_id}"
    if action == "clear":
        store["todos"] = []
        _save_store(config, "todos.json", store)
        return "All todos cleared"
    return f"Unknown action '{action}'. Use 'add', 'list', 'done', 'delete', or 'clear'."


async def execute_vision_analyze(
    image_url: str, question: str, ollama_host: str, vision_model: str
) -> str:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            img_b64 = base64.b64encode(img_resp.content).decode()

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{ollama_host}/api/chat",
                json={
                    "model": vision_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": question,
                            "images": [img_b64],
                        }
                    ],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("message", {}).get("content", "(no response)")
    except Exception as e:
        return f"Error analyzing image: {e}"


async def execute_clarify(question: str) -> str:
    return f"[CLARIFICATION NEEDED]: {question}"


# ── Discord bot API tools ──────────────────────────────────────────────────────


async def _discord_api(
    method: str, path: str, config: "Config", body: dict | None = None
) -> dict:
    url = f"{config.discord_bot_api_url}{path}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        if method == "GET":
            resp = await client.get(url)
        else:
            resp = await client.post(url, json=body or {})
        resp.raise_for_status()
        return resp.json()


async def execute_discord_send(channel: str, content: str, config: "Config") -> str:
    key = "channel_id" if channel.isdigit() else "channel_name"
    try:
        data = await _discord_api(
            "POST", "/send", config,
            {key: int(channel) if channel.isdigit() else channel, "content": content},
        )
        return f"Message sent (id={data.get('message_id')})"
    except Exception as e:
        return f"Error sending Discord message: {e}"


async def execute_discord_channels(config: "Config") -> str:
    try:
        data = await _discord_api("GET", "/channels", config)
        channels = data.get("channels", [])
        if not channels:
            return "No channels found."
        lines = [f"#{c['name']} ({c['type']}) — id:{c['id']}" for c in channels]
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing channels: {e}"


async def execute_discord_members(config: "Config") -> str:
    try:
        data = await _discord_api("GET", "/members", config)
        members = [m for m in data.get("members", []) if not m["bot"]]
        if not members:
            return "No members found (members intent may not be enabled)."
        return "\n".join(f"{m['display_name']} (@{m['name']})" for m in members[:50])
    except Exception as e:
        return f"Error listing members: {e}"


async def execute_discord_poll(
    channel: str, question: str, options: list[str], duration_hours: int, config: "Config"
) -> str:
    key = "channel_id" if channel.isdigit() else "channel_name"
    try:
        data = await _discord_api(
            "POST", "/poll", config,
            {
                key: int(channel) if channel.isdigit() else channel,
                "question": question,
                "options": options,
                "duration_hours": duration_hours,
            },
        )
        return f"Poll created (id={data.get('message_id')})"
    except Exception as e:
        return f"Error creating poll: {e}"


async def execute_discord_react(
    emoji: str, message_id: str | None, channel: str | None, config: "Config"
) -> str:
    body: dict = {"emoji": emoji}
    if message_id:
        body["message_id"] = int(message_id)
    if channel:
        key = "channel_id" if channel.isdigit() else "channel_name"
        body[key] = int(channel) if channel.isdigit() else channel
    try:
        await _discord_api("POST", "/react", config, body)
        return f"Reacted with {emoji}"
    except Exception as e:
        return f"Error adding reaction: {e}"


async def execute_discord_thread(
    name: str, message_id: str | None, config: "Config"
) -> str:
    body: dict = {"name": name[:100]}
    if message_id:
        body["message_id"] = int(message_id)
    try:
        data = await _discord_api("POST", "/thread", config, body)
        return f"Thread created: {data.get('thread_name', name)}"
    except Exception as e:
        return f"Error creating thread: {e}"


async def execute_discord_pin(message_id: str | None, config: "Config") -> str:
    body: dict = {}
    if message_id:
        body["message_id"] = int(message_id)
    try:
        await _discord_api("POST", "/pin", config, body)
        return "Message pinned"
    except Exception as e:
        return f"Error pinning message: {e}"


async def execute_discord_delete(
    message_id: str | None, count: int, config: "Config"
) -> str:
    body: dict = {"count": count}
    if message_id:
        body["message_id"] = int(message_id)
    try:
        data = await _discord_api("POST", "/delete", config, body)
        return f"Deleted {data.get('deleted', 0)} message(s)"
    except Exception as e:
        return f"Error deleting message(s): {e}"


async def execute_discord_history(
    channel: str | None, limit: int, before: str | None, after: str | None, config: "Config"
) -> str:
    qs = f"limit={min(limit, 100)}"
    if channel:
        key = "channel_id" if channel.isdigit() else "channel_name"
        qs += f"&{key}={channel}"
    if before:
        qs += f"&before={before}"
    if after:
        qs += f"&after={after}"
    try:
        data = await _discord_api("GET", f"/history?{qs}", config)
        messages = data.get("messages", [])
        if not messages:
            return "No messages found."
        lines = [
            f"[{m['timestamp'][:16]}] {m['author']}{'(bot)' if m['bot'] else ''} (id:{m['id']}): {m['content'][:200]}"
            for m in reversed(messages)
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching history: {e}"


async def execute_discord_fetch_message(message_id: str, channel: str | None, config: "Config") -> str:
    path = f"/message?message_id={message_id}"
    if channel:
        key = "channel_id" if channel.isdigit() else "channel_name"
        path += f"&{key}={channel}"
    try:
        m = await _discord_api("GET", path, config)
        if "error" in m:
            return f"Error: {m['error']}"
        return f"[{m['timestamp'][:16]}] {m['author']} (id:{m['id']}): {m['content']}"
    except Exception as e:
        return f"Error fetching message: {e}"


async def execute_discord_dm(user: str, content: str, config: "Config") -> str:
    key = "user_id" if user.isdigit() else "user_name"
    try:
        data = await _discord_api("POST", "/dm", config, {key: user, "content": content})
        if "error" in data:
            return f"DM failed: {data['error']}"
        return f"DM sent to {data.get('user', user)}"
    except Exception as e:
        return f"Error sending DM: {e}"


async def execute_discord_gif(query: str, channel: str, config: "Config") -> str:
    # Use TENOR_API_KEY if set, otherwise fall back to Tenor's public demo key
    api_key = (getattr(config, "tenor_api_key", None) or "LIVDSRZULELA")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.tenor.com/v1/search",
                params={"q": query, "key": api_key, "limit": 1, "media_filter": "minimal"},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
        if not results:
            return f"No GIF found for '{query}'"
        gif_url = results[0]["media"][0]["gif"]["url"]
        # Discord auto-embeds tenor GIF URLs inline
        return await execute_discord_send(channel, gif_url, config)
    except Exception as e:
        return f"Error fetching GIF: {e}"


# ── WMO weather code descriptions ─────────────────────────────────────────────

_WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def _wmo_description(code: int) -> str:
    return _WMO_CODES.get(code, f"Unknown (WMO {code})")


# ── New tool implementations ───────────────────────────────────────────────────


async def execute_weather(location: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            geo_resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1},
            )
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()

        results = geo_data.get("results")
        if not results:
            return f"Location not found: {location}"

        place = results[0]
        lat = place["latitude"]
        lon = place["longitude"]
        place_name = place.get("name", location)
        country = place.get("country", "")

        async with httpx.AsyncClient(timeout=10.0) as client:
            wx_resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": "true",
                    "hourly": "temperature_2m,weathercode,precipitation_probability",
                    "timezone": "auto",
                    "forecast_days": 1,
                },
            )
            wx_resp.raise_for_status()
            wx = wx_resp.json()

        current = wx.get("current_weather", {})
        temp = current.get("temperature", "?")
        windspeed = current.get("windspeed", "?")
        wmo = int(current.get("weathercode", 0))
        condition = _wmo_description(wmo)

        hourly = wx.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        precip_probs = hourly.get("precipitation_probability", [])
        wcodes = hourly.get("weathercode", [])

        if temps:
            max_t = max(temps)
            min_t = min(temps)
        else:
            max_t = min_t = "?"

        max_precip = max(precip_probs) if precip_probs else 0

        lines = [
            f"**Weather for {place_name}, {country}**",
            f"Current: {temp}°C — {condition}",
            f"Wind: {windspeed} km/h",
            f"Today's range: {min_t}°C – {max_t}°C",
            f"Max precipitation chance: {max_precip}%",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching weather: {e}"


async def execute_news(topic: str | None = None) -> str:
    if topic:
        url = f"http://feeds.bbci.co.uk/news/{topic}/rss.xml"
    else:
        url = "http://feeds.bbci.co.uk/news/rss.xml"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Hermes/1.0)"})
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        ns = {"media": "http://search.yahoo.com/mrss/"}
        channel_el = root.find("channel")
        if channel_el is None:
            return "Could not parse RSS feed."

        items = channel_el.findall("item")[:5]
        if not items:
            return "No news items found."

        lines = [f"**BBC News{' — ' + topic.title() if topic else ''}** (top {len(items)} headlines)\n"]
        for i, item in enumerate(items, 1):
            title = (item.findtext("title") or "").strip()
            desc = (item.findtext("description") or "").strip()
            desc = re.sub(r"<[^>]+>", "", desc)[:200]
            lines.append(f"{i}. **{title}**\n   {desc}")

        return "\n\n".join(lines)
    except Exception as e:
        return f"Error fetching news: {e}"


async def execute_qr_code(text: str, channel: str, config: "Config") -> str:
    try:
        encoded = url_quote(text)
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?data={encoded}&size=300x300"
        return await execute_discord_send(channel, qr_url, config)
    except Exception as e:
        return f"Error generating QR code: {e}"


async def execute_discord_embed(
    channel: str,
    title: str,
    description: str,
    color: str | None,
    fields: list[dict] | None,
    thumbnail: str | None,
    config: "Config",
) -> str:
    key = "channel_id" if channel.isdigit() else "channel_name"
    body: dict = {
        key: int(channel) if channel.isdigit() else channel,
        "title": title,
        "description": description,
    }
    if color:
        body["color"] = color
    if fields:
        body["fields"] = fields
    if thumbnail:
        body["thumbnail"] = thumbnail
    try:
        data = await _discord_api("POST", "/embed", config, body)
        return f"Embed sent (id={data.get('message_id')})"
    except Exception as e:
        return f"Error sending embed: {e}"


def _parse_when(when: str) -> int:
    """Parse a 'when' string and return delay in seconds. Defaults to 60 on failure."""
    when_lower = when.strip().lower()
    m = re.match(r"in\s+(\d+(?:\.\d+)?)\s+(minute|minutes|hour|hours|day|days)", when_lower)
    if m:
        amount = float(m.group(1))
        unit = m.group(2)
        if "minute" in unit:
            return max(1, int(amount * 60))
        if "hour" in unit:
            return max(1, int(amount * 3600))
        if "day" in unit:
            return max(1, int(amount * 86400))
    # Try ISO datetime
    try:
        target = datetime.fromisoformat(when)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        delta = (target - now).total_seconds()
        return max(1, int(delta))
    except Exception:
        pass
    return 60


async def execute_remind(
    message: str, when: str, channel: str | None, config: "Config"
) -> str:
    delay = _parse_when(when)
    body: dict = {"message": message, "delay_seconds": delay}
    if channel:
        key = "channel_id" if channel.isdigit() else "channel_name"
        body[key] = int(channel) if channel.isdigit() else channel
    try:
        await _discord_api("POST", "/remind", config, body)
        mins = delay // 60
        secs = delay % 60
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
        return f"Reminder set for {time_str} from now."
    except Exception as e:
        return f"Error setting reminder: {e}"


async def execute_ollama_models(config: "Config") -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{config.ollama_host}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models = data.get("models", [])
        if not models:
            return "No models found on Ollama server."

        lines = ["**Ollama Models**"]
        for m in models:
            name = m.get("name", "?")
            size_bytes = m.get("size", 0)
            if size_bytes >= 1_073_741_824:
                size_str = f"{size_bytes / 1_073_741_824:.1f} GB"
            else:
                size_str = f"{size_bytes / 1_048_576:.0f} MB"
            lines.append(f"- {name} ({size_str})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing Ollama models: {e}"


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def execute_github_list_issues(repo: str, state: str, config: "Config") -> str:
    if not config.github_token:
        return "GITHUB_TOKEN not set in hermes.env — add it to use GitHub tools"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/issues",
                params={"state": state, "per_page": 20},
                headers=_github_headers(config.github_token),
            )
            resp.raise_for_status()
            issues = resp.json()

        if not issues:
            return f"No {state} issues found in {repo}."

        lines = [f"**{repo} — {state} issues ({len(issues)})**"]
        for issue in issues:
            number = issue.get("number")
            title = issue.get("title", "")
            labels = ", ".join(l["name"] for l in issue.get("labels", []))
            label_str = f" [{labels}]" if labels else ""
            lines.append(f"#{number}: {title}{label_str}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing issues: {e}"


async def execute_github_get_issue(repo: str, number: int, config: "Config") -> str:
    if not config.github_token:
        return "GITHUB_TOKEN not set in hermes.env — add it to use GitHub tools"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/issues/{number}",
                headers=_github_headers(config.github_token),
            )
            resp.raise_for_status()
            issue = resp.json()

        title = issue.get("title", "")
        state = issue.get("state", "")
        body = (issue.get("body") or "").strip()[:1000]
        labels = ", ".join(l["name"] for l in issue.get("labels", []))
        author = issue.get("user", {}).get("login", "?")
        created = issue.get("created_at", "")[:10]
        comments = issue.get("comments", 0)

        lines = [
            f"**#{number}: {title}**",
            f"State: {state} | Author: {author} | Created: {created} | Comments: {comments}",
        ]
        if labels:
            lines.append(f"Labels: {labels}")
        if body:
            lines.append(f"\n{body}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching issue: {e}"


async def execute_github_create_issue(
    repo: str, title: str, summary: str,
    context: str | None, acceptance_criteria: list[str] | None,
    technical_notes: str | None, labels: list[str] | None, config: "Config"
) -> str:
    if not config.github_token:
        return "GITHUB_TOKEN not set in hermes.env — add it to use GitHub tools"
    sections = [f"## Summary\n{summary}"]
    if context:
        sections.append(f"## Context\n{context}")
    if acceptance_criteria:
        criteria = "\n".join(f"- [ ] {c}" for c in acceptance_criteria)
        sections.append(f"## Acceptance Criteria\n{criteria}")
    if technical_notes:
        sections.append(f"## Technical Notes\n{technical_notes}")
    body = "\n\n".join(sections)
    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.github.com/repos/{repo}/issues",
                json=payload,
                headers=_github_headers(config.github_token),
            )
            resp.raise_for_status()
            issue = resp.json()

        number = issue.get("number")
        url = issue.get("html_url", "")
        return f"Issue created: #{number} — {title}\n{url}"
    except Exception as e:
        return f"Error creating issue: {e}"


async def execute_github_comment_issue(
    repo: str, number: int, body: str, config: "Config"
) -> str:
    if not config.github_token:
        return "GITHUB_TOKEN not set in hermes.env — add it to use GitHub tools"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.github.com/repos/{repo}/issues/{number}/comments",
                json={"body": body},
                headers=_github_headers(config.github_token),
            )
            resp.raise_for_status()
            comment = resp.json()

        url = comment.get("html_url", "")
        return f"Comment added to #{number}.\n{url}"
    except Exception as e:
        return f"Error adding comment: {e}"


# ── Financial data tools ──────────────────────────────────────────────────────


async def _coingecko_search_id(client: httpx.AsyncClient, symbol: str) -> str | None:
    """Search CoinGecko for a coin and return its id, or None if not found."""
    try:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": symbol},
        )
        if resp.status_code == 429:
            return None
        resp.raise_for_status()
        coins = resp.json().get("coins", [])
        if not coins:
            return None
        # Prefer exact id/symbol match, otherwise take the first result
        symbol_lower = symbol.lower()
        for coin in coins:
            if coin.get("id", "").lower() == symbol_lower or coin.get("symbol", "").lower() == symbol_lower:
                return coin["id"]
        return coins[0]["id"]
    except Exception:
        return None


def _fmt_large(n: float) -> str:
    """Format a large number as $X.XXB / $X.XXT etc."""
    if n >= 1_000_000_000_000:
        return f"${n / 1_000_000_000_000:.2f}T"
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.2f}M"
    return f"${n:,.2f}"


async def execute_crypto_price(symbols: str, vs_currency: str = "usd") -> str:
    try:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            return "No symbols provided."

        async with httpx.AsyncClient(timeout=15.0) as client:
            ids = []
            id_to_input: dict[str, str] = {}
            for sym in symbol_list:
                coin_id = await _coingecko_search_id(client, sym)
                if coin_id is None:
                    ids.append(sym)
                    id_to_input[sym] = sym
                else:
                    ids.append(coin_id)
                    id_to_input[coin_id] = sym

            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": ",".join(ids),
                    "vs_currencies": vs_currency,
                    "include_24hr_change": "true",
                    "include_market_cap": "true",
                },
            )
            if resp.status_code == 429:
                return "CoinGecko rate limit reached (429). Please retry in a moment."
            resp.raise_for_status()
            data = resp.json()

        if not data:
            return "No price data returned. Check the coin names and try again."

        lines = []
        vs = vs_currency.lower()
        for coin_id, prices in data.items():
            price = prices.get(vs)
            change = prices.get(f"{vs}_24h_change")
            cap = prices.get(f"{vs}_market_cap")

            price_str = f"${price:,.2f}" if price is not None else "N/A"
            change_str = (
                f"{'+' if change >= 0 else ''}{change:.2f}%"
                if change is not None else "N/A"
            )
            cap_str = _fmt_large(cap) if cap else "N/A"
            label = coin_id.replace("-", " ").title()
            lines.append(f"{label}: {price_str} | 24h: {change_str} | Cap: {cap_str}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching crypto price: {e}"


async def execute_crypto_trending() -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.coingecko.com/api/v3/search/trending")
            if resp.status_code == 429:
                return "CoinGecko rate limit reached (429). Please retry in a moment."
            resp.raise_for_status()
            data = resp.json()

        coins = data.get("coins", [])[:7]
        if not coins:
            return "No trending coins found."

        lines = ["**Trending on CoinGecko**"]
        for i, entry in enumerate(coins, 1):
            item = entry.get("item", {})
            name = item.get("name", "?")
            symbol = item.get("symbol", "?")
            data_block = item.get("data", {})
            price_change = data_block.get("price_change_percentage_24h", {})
            change_val = price_change.get("usd") if isinstance(price_change, dict) else None
            change_str = (
                f"{'+' if change_val >= 0 else ''}{change_val:.2f}%"
                if change_val is not None else "N/A"
            )
            lines.append(f"{i}. {name} ({symbol}) — 24h: {change_str}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching trending coins: {e}"


async def execute_crypto_chart(symbol: str, days: int = 7) -> str:
    days = min(max(days, 1), 30)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            coin_id = await _coingecko_search_id(client, symbol)
            if coin_id is None:
                return f"Could not find coin: {symbol}"

            resp = await client.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
                params={"vs_currency": "usd", "days": days},
            )
            if resp.status_code == 429:
                return "CoinGecko rate limit reached (429). Please retry in a moment."
            resp.raise_for_status()
            data = resp.json()

        prices = [p[1] for p in data.get("prices", []) if p[1] is not None]
        if not prices:
            return f"No price data available for {symbol} over {days} days."

        high = max(prices)
        low = min(prices)
        current = prices[-1]
        start = prices[0]
        pct_change = ((current - start) / start * 100) if start else 0
        direction = "+" if pct_change >= 0 else ""

        label = coin_id.replace("-", " ").title()
        return (
            f"**{label} — {days}d chart summary**\n"
            f"Current: ${current:,.2f}\n"
            f"High: ${high:,.2f} | Low: ${low:,.2f}\n"
            f"Period change: {direction}{pct_change:.2f}%"
        )
    except Exception as e:
        return f"Error fetching crypto chart: {e}"


_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}


async def execute_stock_quote(symbol: str) -> str:
    sym = symbol.upper()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                params={"interval": "1d", "range": "1d"},
                headers=_YAHOO_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()

        result = data.get("chart", {}).get("result")
        if not result:
            error = data.get("chart", {}).get("error", {})
            return f"No data found for {sym}: {error.get('description', 'unknown error')}"

        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        change = meta.get("regularMarketChange")
        change_pct = meta.get("regularMarketChangePercent")
        volume = meta.get("regularMarketVolume")
        market_cap = meta.get("marketCap")

        price_str = f"${price:,.2f}" if price is not None else "N/A"
        change_str = (
            f"{'+' if change >= 0 else ''}{change:.2f} ({'+' if change_pct >= 0 else ''}{change_pct:.2f}%)"
            if change is not None and change_pct is not None else "N/A"
        )
        vol_str = f"{volume / 1_000_000:.1f}M" if volume else "N/A"
        cap_str = _fmt_large(market_cap) if market_cap else "N/A"

        return f"{sym}: {price_str} | {change_str} | Vol: {vol_str} | Cap: {cap_str}"
    except Exception as e:
        return f"Error fetching quote for {sym}: {e}"


async def execute_stock_info(symbol: str) -> str:
    sym = symbol.upper()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}",
                params={"modules": "price,summaryDetail,assetProfile"},
                headers=_YAHOO_HEADERS,
            )
            resp.raise_for_status()
            data = resp.json()

        result = data.get("quoteSummary", {}).get("result")
        if not result:
            error = data.get("quoteSummary", {}).get("error", {})
            return f"No data found for {sym}: {error.get('message', 'unknown error') if error else 'unknown error'}"

        modules = result[0]
        price_mod = modules.get("price", {})
        summary = modules.get("summaryDetail", {})
        profile = modules.get("assetProfile", {})

        company_name = price_mod.get("longName") or price_mod.get("shortName") or sym
        sector = profile.get("sector", "N/A")
        industry = profile.get("industry", "N/A")
        description = (profile.get("longBusinessSummary") or "")[:300]

        pe_ratio = summary.get("trailingPE", {})
        pe_val = pe_ratio.get("raw") if isinstance(pe_ratio, dict) else pe_ratio
        pe_str = f"{pe_val:.2f}" if isinstance(pe_val, (int, float)) else "N/A"

        high_52 = summary.get("fiftyTwoWeekHigh", {})
        low_52 = summary.get("fiftyTwoWeekLow", {})
        high_val = high_52.get("raw") if isinstance(high_52, dict) else high_52
        low_val = low_52.get("raw") if isinstance(low_52, dict) else low_52
        range_str = f"${low_val:,.2f} – ${high_val:,.2f}" if isinstance(high_val, (int, float)) and isinstance(low_val, (int, float)) else "N/A"

        div_yield = summary.get("dividendYield", {})
        div_val = div_yield.get("raw") if isinstance(div_yield, dict) else div_yield
        div_str = f"{div_val * 100:.2f}%" if isinstance(div_val, (int, float)) and div_val else "N/A"

        lines = [
            f"**{company_name} ({sym})**",
            f"Sector: {sector} | Industry: {industry}",
            f"P/E Ratio: {pe_str} | 52w Range: {range_str} | Dividend Yield: {div_str}",
        ]
        if description:
            lines.append(f"\n{description}{'...' if len(profile.get('longBusinessSummary', '')) > 300 else ''}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching info for {sym}: {e}"


def _fmt_polymarket_date(date_str: str | None) -> str:
    if not date_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return date_str[:10] if date_str else "N/A"


def _fmt_polymarket_volume(vol) -> str:
    try:
        v = float(vol)
    except (TypeError, ValueError):
        return "N/A"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.2f}"


def _format_market(market: dict) -> str:
    question = market.get("question", "?")
    outcomes = market.get("outcomes")
    outcome_prices = market.get("outcomePrices")
    volume = market.get("volume")
    end_date = market.get("endDate") or market.get("end_date_iso")

    lines = [f"**{question}**"]

    if outcomes and outcome_prices:
        try:
            outcome_list = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
            price_list = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            for name, prob in zip(outcome_list, price_list):
                pct = float(prob) * 100
                lines.append(f"  • {name}: {pct:.1f}%")
        except Exception:
            pass

    vol_str = _fmt_polymarket_volume(volume)
    date_str = _fmt_polymarket_date(end_date)
    lines.append(f"  Volume: {vol_str} | Ends: {date_str}")
    return "\n".join(lines)


async def execute_polymarket_markets(query: str | None = None, limit: int = 10) -> str:
    limit = min(max(limit, 1), 50)
    try:
        params: dict = {
            "active": "true",
            "order": "volume",
            "ascending": "false",
            "limit": limit,
        }
        if query:
            params["search"] = query

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://gamma-api.polymarket.com/markets", params=params)
            resp.raise_for_status()
            markets = resp.json()

        if not markets:
            return "No markets found."

        header = f"**Top {len(markets)} Polymarket markets" + (f" matching '{query}'" if query else " by volume") + "**\n"
        sections = [_format_market(m) for m in markets]
        return header + "\n\n".join(sections)
    except Exception as e:
        return f"Error fetching Polymarket markets: {e}"


async def execute_polymarket_market(slug: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://gamma-api.polymarket.com/markets",
                params={"slug": slug},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data:
            return f"No market found with slug: {slug}"

        market = data[0] if isinstance(data, list) else data
        question = market.get("question", "?")
        description = (market.get("description") or "").strip()[:500]
        outcomes = market.get("outcomes")
        outcome_prices = market.get("outcomePrices")
        volume = market.get("volume")
        end_date = market.get("endDate") or market.get("end_date_iso")
        resolution = (market.get("resolutionCriteria") or market.get("resolution_source") or "").strip()[:300]

        lines = [f"**{question}**"]

        if outcomes and outcome_prices:
            try:
                outcome_list = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
                price_list = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                for name, prob in zip(outcome_list, price_list):
                    pct = float(prob) * 100
                    lines.append(f"  • {name}: {pct:.1f}%")
            except Exception:
                pass

        vol_str = _fmt_polymarket_volume(volume)
        date_str = _fmt_polymarket_date(end_date)
        lines.append(f"Volume: {vol_str} | Ends: {date_str}")

        if description:
            lines.append(f"\n{description}{'...' if len(market.get('description', '')) > 500 else ''}")
        if resolution:
            lines.append(f"\n**Resolution criteria:** {resolution}{'...' if len(market.get('resolutionCriteria', '') or '') > 300 else ''}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching market '{slug}': {e}"


# ── Research executors ─────────────────────────────────────────────────────────

_job_manager = None


def _get_job_manager(config: "Config"):
    global _job_manager
    if _job_manager is None:
        from proxy.research.validators import SecurityValidator
        from proxy.research.storage import ResearchStore
        from proxy.research.memory import MemoryGuard
        from proxy.research.engine import JobManager
        security = SecurityValidator(config.research_max_pdf_size_mb)
        store = ResearchStore(config.research_data_path, security)
        guard = MemoryGuard(
            config.research_memory_threshold_pct,
            config.research_memory_critical_pct,
            config.ollama_host,
        )
        guard.start()
        _job_manager = JobManager(config, guard, store, config.discord_bot_api_url)
    return _job_manager


async def execute_deep_research(topic: str, channel: str, config: "Config",
                                 researcher_model=None,
                                 orchestrator_model=None,
                                 max_rounds=None,
                                 verbosity: str = "normal") -> str:
    from proxy.research.validators import SecurityValidator
    sv = SecurityValidator(config.research_max_pdf_size_mb)
    if sv.scan_prompt_injection(topic):
        return "Research topic rejected: potential prompt injection detected."
    jm = _get_job_manager(config)
    return await jm.submit(topic, channel, mode="research", verbosity=verbosity)


async def execute_deepdive(topic: str, channel: str, config: "Config",
                            urls=None) -> str:
    from proxy.research.validators import SecurityValidator
    sv = SecurityValidator(config.research_max_pdf_size_mb)
    if sv.scan_prompt_injection(topic):
        return "Research topic rejected: potential prompt injection detected."
    jm = _get_job_manager(config)
    return await jm.submit(topic, channel, mode="deepdive", seed_urls=urls or [])


# ── Dispatcher ─────────────────────────────────────────────────────────────────


async def dispatch_tool(name: str, args: dict[str, Any], config: "Config") -> str:
    if name == "web_search":
        return await execute_web_search(args["query"], config.searxng_url)
    if name == "web_extract":
        return await execute_web_extract(args["url"], args.get("max_chars", 3000))
    if name == "execute_code":
        return await execute_code(args["code"], args.get("timeout", 30))
    if name == "terminal":
        return await execute_terminal(args["command"], args.get("timeout", 30))
    if name == "process":
        return await execute_process(args["action"], args.get("pid"))
    if name == "read_file":
        return await execute_read_file(args["path"], config)
    if name == "patch":
        return await execute_patch(args["path"], args["content"], config)
    if name == "memory":
        return await execute_memory(args["action"], args.get("key"), args.get("value"), config)
    if name == "session_search":
        return await execute_session_search(args["query"], config)
    if name == "todo":
        return await execute_todo(args["action"], args.get("task"), args.get("id"), config)
    if name == "vision_analyze":
        return await execute_vision_analyze(
            args["image_url"],
            args.get("question", "Describe this image in detail"),
            config.ollama_host,
            config.vision_model,
        )
    if name == "clarify":
        return await execute_clarify(args["question"])
    if name == "discord_send":
        return await execute_discord_send(args["channel"], args["content"], config)
    if name == "discord_channels":
        return await execute_discord_channels(config)
    if name == "discord_members":
        return await execute_discord_members(config)
    if name == "discord_poll":
        return await execute_discord_poll(
            args["channel"],
            args["question"],
            args["options"],
            args.get("duration_hours", 24),
            config,
        )
    if name == "discord_react":
        return await execute_discord_react(
            args["emoji"], args.get("message_id"), args.get("channel"), config
        )
    if name == "discord_thread":
        return await execute_discord_thread(args["name"], args.get("message_id"), config)
    if name == "discord_pin":
        return await execute_discord_pin(args.get("message_id"), config)
    if name == "discord_delete":
        return await execute_discord_delete(
            args.get("message_id"), args.get("count", 1), config
        )
    if name == "discord_dm":
        return await execute_discord_dm(args["user"], args["content"], config)
    if name == "discord_gif":
        return await execute_discord_gif(args["query"], args["channel"], config)
    if name == "discord_history":
        return await execute_discord_history(
            args.get("channel"), args.get("limit", 25),
            args.get("before"), args.get("after"), config
        )
    if name == "discord_fetch_message":
        return await execute_discord_fetch_message(args["message_id"], args.get("channel"), config)
    if name == "weather":
        return await execute_weather(args["location"])
    if name == "news":
        return await execute_news(args.get("topic"))
    if name == "qr_code":
        return await execute_qr_code(args["text"], args["channel"], config)
    if name == "discord_embed":
        return await execute_discord_embed(
            args["channel"],
            args["title"],
            args["description"],
            args.get("color"),
            args.get("fields"),
            args.get("thumbnail"),
            config,
        )
    if name == "remind":
        return await execute_remind(args["message"], args["when"], args.get("channel"), config)
    if name == "ollama_models":
        return await execute_ollama_models(config)
    if name == "github_list_issues":
        return await execute_github_list_issues(args["repo"], args.get("state", "open"), config)
    if name == "github_get_issue":
        return await execute_github_get_issue(args["repo"], args["number"], config)
    if name == "github_create_issue":
        return await execute_github_create_issue(
            args["repo"], args["title"], args["summary"],
            args.get("context"), args.get("acceptance_criteria"),
            args.get("technical_notes"), args.get("labels"), config
        )
    if name == "github_comment_issue":
        return await execute_github_comment_issue(args["repo"], args["number"], args["body"], config)
    if name == "crypto_price":
        return await execute_crypto_price(args["symbols"], args.get("vs_currency", "usd"))
    if name == "crypto_trending":
        return await execute_crypto_trending()
    if name == "crypto_chart":
        return await execute_crypto_chart(args["symbol"], args.get("days", 7))
    if name == "stock_quote":
        return await execute_stock_quote(args["symbol"])
    if name == "stock_info":
        return await execute_stock_info(args["symbol"])
    if name == "polymarket_markets":
        return await execute_polymarket_markets(args.get("query"), args.get("limit", 10))
    if name == "polymarket_market":
        return await execute_polymarket_market(args["slug"])
    if name == "deep_research":
        return await execute_deep_research(
            args["topic"], args["channel"], config,
            args.get("researcher_model"), args.get("orchestrator_model"), args.get("max_rounds"),
        )
    if name == "deepdive":
        return await execute_deepdive(
            args["topic"], args["channel"], config, args.get("urls"),
        )
    return f"Unknown tool: {name}"
