import asyncio
import base64
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    return f"Unknown tool: {name}"
