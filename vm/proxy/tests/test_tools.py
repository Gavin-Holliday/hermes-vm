import pytest
import httpx
import respx
from proxy.tools import SEARXNG_TOOL_SCHEMA, execute_web_search, dispatch_tool


def test_tool_schema_has_required_fields():
    assert SEARXNG_TOOL_SCHEMA["type"] == "function"
    fn = SEARXNG_TOOL_SCHEMA["function"]
    assert fn["name"] == "web_search"
    assert "query" in fn["parameters"]["properties"]
    assert "query" in fn["parameters"]["required"]


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
async def test_dispatch_tool_calls_web_search():
    respx.get("http://mock-searxng:8080/search").mock(
        return_value=httpx.Response(200, json={
            "results": [{"title": "T", "url": "http://t.com", "content": "content"}]
        })
    )
    result = await dispatch_tool("web_search", {"query": "test"}, "http://mock-searxng:8080")
    assert "T" in result


@pytest.mark.asyncio
async def test_dispatch_tool_unknown_tool_returns_error():
    result = await dispatch_tool("nonexistent_tool", {}, "http://mock-searxng:8080")
    assert "Unknown tool" in result
