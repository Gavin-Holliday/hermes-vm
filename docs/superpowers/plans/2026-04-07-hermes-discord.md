# Hermes Discord Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `hermes-discord` container service — a Discord bot that streams responses from hermes-proxy, maintains per-channel conversation history, and supports `!clear`.

**Architecture:** Single Python process using `discord.py` with async/await. Per-channel message history is kept in memory (capped at 20 messages). The bot POSTs to hermes-proxy `/api/chat` using NDJSON streaming via `httpx`, buffers tokens, and progressively edits the Discord reply message as chunks arrive. Responses exceeding 2000 characters are split into sequential messages.

**Tech Stack:** Python 3.12, discord.py 2.3, httpx 0.27, python-dotenv, pytest, pytest-asyncio

---

## File Map

```
vm/discord-bot/
├── __init__.py           # empty package marker
├── history.py            # ChannelHistory — per-channel message list capped at 20
├── client.py             # stream_response() — async generator yielding text chunks from proxy
├── bot.py                # Discord bot entry point, commands, message handler
├── requirements.txt      # discord.py, httpx, python-dotenv
├── requirements-dev.txt  # pytest, pytest-asyncio, respx
├── Dockerfile
├── .dockerignore
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_history.py   # unit tests for ChannelHistory
    └── test_client.py    # tests for stream_response with mocked httpx
```

---

### Task 1: Scaffold project structure

**Files:**
- Create: `vm/discord-bot/__init__.py`
- Create: `vm/discord-bot/requirements.txt`
- Create: `vm/discord-bot/requirements-dev.txt`
- Create: `vm/discord-bot/tests/__init__.py`
- Create: `vm/discord-bot/tests/conftest.py`
- Create: `vm/discord-bot/pytest.ini`

- [ ] **Step 1: Create the directory structure**

```bash
mkdir -p ~/Projects/hermes-vm/vm/discord-bot/tests
cd ~/Projects/hermes-vm
touch vm/discord-bot/__init__.py vm/discord-bot/tests/__init__.py
```

- [ ] **Step 2: Create `vm/discord-bot/requirements.txt`**

```
discord.py==2.3.2
httpx==0.27.0
python-dotenv==1.0.1
```

- [ ] **Step 3: Create `vm/discord-bot/requirements-dev.txt`**

```
-r requirements.txt
pytest==8.3.3
pytest-asyncio==0.24.0
respx==0.21.1
```

- [ ] **Step 4: Create `vm/discord-bot/tests/conftest.py`**

```python
import pytest
```

- [ ] **Step 5: Create `vm/discord-bot/pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 6: Install dev dependencies**

```bash
cd ~/Projects/hermes-vm/vm/discord-bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

- [ ] **Step 7: Verify pytest runs (zero tests = OK)**

```bash
cd ~/Projects/hermes-vm/vm/discord-bot
source .venv/bin/activate
python -m pytest tests/ -v
```

Expected: `no tests ran` (or 0 passed).

- [ ] **Step 8: Commit**

```bash
cd ~/Projects/hermes-vm
git add vm/discord-bot/
git commit -m "feat(discord): scaffold discord-bot project structure"
```

---

### Task 2: Channel history module

**Files:**
- Create: `vm/discord-bot/history.py`
- Create: `vm/discord-bot/tests/test_history.py`

- [ ] **Step 1: Write the failing tests**

Create `vm/discord-bot/tests/test_history.py`:

```python
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
    # oldest messages dropped
    assert msgs[0]["content"] == "msg 2"
    assert msgs[-1]["content"] == "msg 5"


def test_clear_removes_channel_history():
    h = ChannelHistory()
    h.add(123, "user", "hello")
    h.clear(123)
    assert h.get(123) == []


def test_clear_nonexistent_channel_is_noop():
    h = ChannelHistory()
    h.clear(999)  # should not raise
    assert h.get(999) == []


def test_get_returns_copy_not_reference():
    h = ChannelHistory()
    h.add(1, "user", "hello")
    msgs = h.get(1)
    msgs.append({"role": "user", "content": "injected"})
    # internal state should not be modified
    assert len(h.get(1)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Projects/hermes-vm/vm/discord-bot
source .venv/bin/activate
python -m pytest tests/test_history.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'history'`.

- [ ] **Step 3: Create `vm/discord-bot/history.py`**

```python
MAX_HISTORY = 20


class ChannelHistory:
    def __init__(self, max_messages: int = MAX_HISTORY) -> None:
        self._max = max_messages
        self._history: dict[int, list[dict]] = {}

    def get(self, channel_id: int) -> list[dict]:
        return list(self._history.get(channel_id, []))

    def add(self, channel_id: int, role: str, content: str) -> None:
        msgs = self._history.setdefault(channel_id, [])
        msgs.append({"role": role, "content": content})
        if len(msgs) > self._max:
            self._history[channel_id] = msgs[-self._max:]

    def clear(self, channel_id: int) -> None:
        self._history.pop(channel_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/Projects/hermes-vm/vm/discord-bot
source .venv/bin/activate
python -m pytest tests/test_history.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/hermes-vm
git add vm/discord-bot/history.py vm/discord-bot/tests/test_history.py
git commit -m "feat(discord): add ChannelHistory with per-channel capped message list"
```

---

### Task 3: Proxy streaming client

**Files:**
- Create: `vm/discord-bot/client.py`
- Create: `vm/discord-bot/tests/test_client.py`

- [ ] **Step 1: Write the failing tests**

Create `vm/discord-bot/tests/test_client.py`:

```python
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
    """Non-streaming tool-call response: single JSON line with done=True."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Projects/hermes-vm/vm/discord-bot
source .venv/bin/activate
python -m pytest tests/test_client.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'client'`.

- [ ] **Step 3: Create `vm/discord-bot/client.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/Projects/hermes-vm/vm/discord-bot
source .venv/bin/activate
python -m pytest tests/test_client.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/hermes-vm
git add vm/discord-bot/client.py vm/discord-bot/tests/test_client.py
git commit -m "feat(discord): add proxy streaming client with NDJSON parsing"
```

---

### Task 4: Discord bot entry point

**Files:**
- Create: `vm/discord-bot/bot.py`

The bot cannot be unit-tested without a real Discord token. This task writes the bot and validates it at least imports correctly.

- [ ] **Step 1: Create `vm/discord-bot/bot.py`**

```python
import asyncio
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from history import ChannelHistory
from client import stream_response

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
PROXY_URL = os.environ.get("PROXY_URL", "http://hermes-proxy:8000")
MODEL = os.environ.get("MODEL", "hermes3")

# Edit the in-progress reply at most every EDIT_INTERVAL characters of new content.
# This prevents Discord API rate limits (5 edits / 5 seconds per message).
EDIT_EVERY_CHARS = 80

intents = discord.Intents.default()
intents.message_content = True  # required for reading message text (privileged intent)

bot = commands.Bot(command_prefix="!", intents=intents)
history = ChannelHistory()


def split_message(text: str, max_len: int = 1990) -> list[str]:
    """Split text into chunks of at most max_len characters."""
    if not text:
        return ["(no response)"]
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]


@bot.event
async def on_ready() -> None:
    print(f"Hermes connected as {bot.user} (id={bot.user.id})")


@bot.command(name="clear")
async def clear_history(ctx: commands.Context) -> None:
    """Reset conversation history for this channel."""
    if ctx.channel.id != CHANNEL_ID:
        return
    history.clear(ctx.channel.id)
    await ctx.send("Conversation history cleared.")


@bot.event
async def on_message(msg: discord.Message) -> None:
    # Ignore our own messages and other bots
    if msg.author.bot:
        return
    # Only respond in the configured channel
    if msg.channel.id != CHANNEL_ID:
        return

    # Process !commands first (e.g., !clear)
    await bot.process_commands(msg)
    if msg.content.startswith("!"):
        return

    history.add(msg.channel.id, "user", msg.content)

    # Send a placeholder that we'll edit progressively
    reply = await msg.channel.send("...")

    full_response = ""
    last_edit_len = 0

    try:
        async for chunk in stream_response(PROXY_URL, MODEL, history.get(msg.channel.id)):
            full_response += chunk
            # Edit every EDIT_EVERY_CHARS new characters to avoid rate limits
            if len(full_response) - last_edit_len >= EDIT_EVERY_CHARS:
                display = full_response[:1990] + ("…" if len(full_response) > 1990 else "")
                await reply.edit(content=display or "…")
                last_edit_len = len(full_response)
    except Exception as exc:
        await reply.edit(content=f"Error: {exc}")
        return

    if not full_response:
        await reply.edit(content="(no response)")
        return

    history.add(msg.channel.id, "assistant", full_response)

    # Final render — split into multiple messages if needed
    parts = split_message(full_response)
    await reply.edit(content=parts[0])
    for part in parts[1:]:
        await msg.channel.send(part)


if __name__ == "__main__":
    bot.run(TOKEN)
```

- [ ] **Step 2: Verify the module imports without error**

```bash
cd ~/Projects/hermes-vm/vm/discord-bot
source .venv/bin/activate
python -c "import bot" && echo "IMPORT_OK" || echo "IMPORT_FAIL"
```

Expected: `KeyError: 'DISCORD_TOKEN'` followed by `IMPORT_FAIL` — this means the app loaded all modules successfully; it only fails at runtime when the env var is absent. All other output means a real import error.

If you see `ModuleNotFoundError`, fix the import before continuing.

- [ ] **Step 3: Run the full test suite to confirm nothing regressed**

```bash
cd ~/Projects/hermes-vm/vm/discord-bot
source .venv/bin/activate
python -m pytest tests/ -v
```

Expected: 13 passed.

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/hermes-vm
git add vm/discord-bot/bot.py
git commit -m "feat(discord): add Discord bot with streaming replies and !clear command"
```

---

### Task 5: Dockerfile and smoke test

**Files:**
- Create: `vm/discord-bot/Dockerfile`
- Create: `vm/discord-bot/.dockerignore`

- [ ] **Step 1: Create `vm/discord-bot/.dockerignore`**

```
.venv/
__pycache__/
*.pyc
tests/
.env
.pytest_cache/
pytest.ini
requirements-dev.txt
```

- [ ] **Step 2: Create `vm/discord-bot/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source into /app/discord_bot/ so imports resolve as top-level modules
COPY . ./discord_bot/

WORKDIR /app/discord_bot

CMD ["python", "bot.py"]
```

- [ ] **Step 3: Build the image**

```bash
cd ~/Projects/hermes-vm/vm/discord-bot
docker build -t hermes-discord:smoke-test .
```

If docker isn't available: `podman build -t hermes-discord:smoke-test .`

Expected: build completes with no errors.

- [ ] **Step 4: Verify the image starts (missing env var error is expected and correct)**

```bash
docker run --rm hermes-discord:smoke-test python -c "import bot" 2>&1
```

Expected: `KeyError: 'DISCORD_TOKEN'` — this means the app loaded all modules successfully; it only fails at runtime when the env var is absent.

If you see `ModuleNotFoundError`, check that `COPY . ./discord_bot/` produced the right file layout and that `bot.py` imports `history` and `client` correctly (they must be at the same directory level).

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/hermes-vm
git add vm/discord-bot/Dockerfile vm/discord-bot/.dockerignore
git commit -m "build(discord): add Dockerfile for hermes-discord"
```

---

### Task 6: Final test run and push

- [ ] **Step 1: Run all discord-bot tests**

```bash
cd ~/Projects/hermes-vm/vm/discord-bot
source .venv/bin/activate
python -m pytest tests/ -v
```

Expected: 13 passed, 0 failed.

- [ ] **Step 2: Push to GitHub**

```bash
cd ~/Projects/hermes-vm
git push origin main
```

- [ ] **Step 3: Verify the push succeeded**

```bash
gh repo view Gavin-Holliday/hermes-vm --web
```

Or: `git log --oneline -5`
