import pytest
import httpx
import respx
from proxy.config import Config
from proxy.tools import SEARXNG_TOOL_SCHEMA, ALL_TOOL_SCHEMAS, execute_web_search, dispatch_tool


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        ollama_host="http://mock-ollama:11434",
        allowed_models=["hermes3"],
        searxng_url="http://mock-searxng:8080",
        rate_limit_burst=20,
        rate_limit_per_min=60,
        max_tool_rounds=10,
        tool_timeout_secs=30,
        system_prompt="You are Hermes.",
        workspace_path=str(tmp_path / "workspace"),
        data_path=str(tmp_path / "data"),
        vision_model="gemma4:e4b",
    )


def test_tool_schema_has_required_fields():
    assert SEARXNG_TOOL_SCHEMA["type"] == "function"
    fn = SEARXNG_TOOL_SCHEMA["function"]
    assert fn["name"] == "web_search"
    assert "query" in fn["parameters"]["properties"]
    assert "query" in fn["parameters"]["required"]


def test_all_tool_schemas_are_valid():
    for schema in ALL_TOOL_SCHEMAS:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"


@pytest.mark.asyncio
@respx.mock
async def test_execute_web_search_returns_formatted_results():
    respx.get("http://mock-searxng:8080/search").mock(
        return_value=httpx.Response(200, json={
            "results": [
                {"title": "Python Docs", "url": "https://python.org", "content": "The Python programming language."},
                {"title": "PyPI", "url": "https://pypi.org", "content": "The Python Package Index."},
            ]
        })
    )
    result = await execute_web_search("python", "http://mock-searxng:8080")
    assert "Python Docs" in result
    assert "https://python.org" in result
    assert "PyPI" in result


@pytest.mark.asyncio
@respx.mock
async def test_execute_web_search_returns_no_results_message():
    respx.get("http://mock-searxng:8080/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    result = await execute_web_search("xyzzy404notfound", "http://mock-searxng:8080")
    assert result == "No results found."


@pytest.mark.asyncio
@respx.mock
async def test_dispatch_tool_calls_web_search(cfg):
    respx.get("http://mock-searxng:8080/search").mock(
        return_value=httpx.Response(200, json={
            "results": [{"title": "T", "url": "http://t.com", "content": "content"}]
        })
    )
    result = await dispatch_tool("web_search", {"query": "test"}, cfg)
    assert "T" in result


@pytest.mark.asyncio
async def test_dispatch_tool_unknown_tool_returns_error(cfg):
    result = await dispatch_tool("nonexistent_tool", {}, cfg)
    assert "Unknown tool" in result


@pytest.mark.asyncio
async def test_execute_code_returns_output(cfg):
    result = await dispatch_tool("execute_code", {"code": "print('hello')"}, cfg)
    assert "hello" in result


@pytest.mark.asyncio
async def test_terminal_returns_output(cfg):
    result = await dispatch_tool("terminal", {"command": "echo hi"}, cfg)
    assert "hi" in result


@pytest.mark.asyncio
async def test_memory_set_get(cfg):
    await dispatch_tool("memory", {"action": "set", "key": "foo", "value": "bar"}, cfg)
    result = await dispatch_tool("memory", {"action": "get", "key": "foo"}, cfg)
    assert "bar" in result


@pytest.mark.asyncio
async def test_todo_add_list(cfg):
    await dispatch_tool("todo", {"action": "add", "task": "buy milk"}, cfg)
    result = await dispatch_tool("todo", {"action": "list"}, cfg)
    assert "buy milk" in result


@pytest.mark.asyncio
async def test_patch_and_read_file(cfg):
    await dispatch_tool("patch", {"path": "test.txt", "content": "hello world"}, cfg)
    result = await dispatch_tool("read_file", {"path": "test.txt"}, cfg)
    assert "hello world" in result


@pytest.mark.asyncio
async def test_read_file_path_traversal_blocked(cfg):
    result = await dispatch_tool("read_file", {"path": "../../../etc/passwd"}, cfg)
    assert "Access denied" in result


@pytest.mark.asyncio
async def test_web_extract(cfg):
    import respx, httpx
    with respx.mock:
        respx.get("http://example.com").mock(
            return_value=httpx.Response(200, text="<html><body><p>Hello world</p></body></html>",
                                        headers={"content-type": "text/html"})
        )
        result = await dispatch_tool("web_extract", {"url": "http://example.com"}, cfg)
    assert "Hello world" in result
