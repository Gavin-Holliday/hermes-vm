import json
import pytest
import respx
import httpx
from proxy.research.engine import ResearchAgent
from proxy.research.validators import SecurityValidator, SourceValidator, OutputValidator
from proxy.research.processors import ContentProcessor


VALID_OUTPUT = {
    "findings": ["Bitcoin ETF approved [[1]](https://reuters.com/a)"],
    "prose_summary": "SEC approved Bitcoin ETFs in January 2024.",
    "citations": [{"index": 1, "title": "Reuters", "url": "https://reuters.com/a",
                   "domain": "reuters.com", "date": "2024-01-10"}],
    "relevance_score": 0.9,
    "contradictions": [],
    "gaps": [],
    "failed_sources": [],
}


@pytest.fixture
def agent(cfg):
    sec = SecurityValidator()
    sv = SourceValidator(sec)
    cp = ContentProcessor()
    ov = OutputValidator()
    return ResearchAgent(cfg, sec, sv, cp, ov)


@respx.mock
@pytest.mark.asyncio
async def test_agent_run_success(agent, cfg):
    # SearxNG returns a result
    respx.get(f"{cfg.searxng_url}/search").mock(return_value=httpx.Response(200, json={
        "results": [{"title": "Reuters", "url": "https://reuters.com/a", "content": "Bitcoin ETF approved"}]
    }))
    # Source validation (HEAD)
    respx.head("https://reuters.com/a").mock(return_value=httpx.Response(
        200, headers={"content-type": "text/html", "content-length": "5000"}
    ))
    # Web extract (GET)
    respx.get("https://reuters.com/a").mock(return_value=httpx.Response(
        200, text="<p>Bitcoin ETF approved by SEC in January 2024.</p>",
        headers={"content-type": "text/html"}
    ))
    # Ollama agent call
    respx.post(f"{cfg.ollama_host}/api/chat").mock(return_value=httpx.Response(200, json={
        "message": {"content": json.dumps(VALID_OUTPUT)}
    }))
    result = await agent.run("bitcoin ETF approval", "bitcoin ETF")
    assert result is not None
    assert len(result.findings) > 0


@respx.mock
@pytest.mark.asyncio
async def test_agent_returns_none_on_invalid_output(agent, cfg):
    respx.get(f"{cfg.searxng_url}/search").mock(return_value=httpx.Response(200, json={
        "results": [{"title": "T", "url": "https://reuters.com/b", "content": "content"}]
    }))
    respx.head("https://reuters.com/b").mock(return_value=httpx.Response(
        200, headers={"content-type": "text/html"}
    ))
    respx.get("https://reuters.com/b").mock(return_value=httpx.Response(
        200, text="<p>Content</p>", headers={"content-type": "text/html"}
    ))
    # Ollama returns invalid JSON — first call (extraction), second call (rephrase), third call (retry extraction)
    respx.post(f"{cfg.ollama_host}/api/chat").mock(return_value=httpx.Response(200, json={
        "message": {"content": "not valid json at all"}
    }))
    result = await agent.run("query", "topic")
    assert result is None


from proxy.research.engine import JobManager
from proxy.research.memory import MemoryGuard
from proxy.research.storage import ResearchStore
from proxy.research.validators import SecurityValidator


@pytest.fixture
def job_manager(cfg, tmp_path):
    sec = SecurityValidator()
    store = ResearchStore(str(tmp_path / "research"), sec)
    guard = MemoryGuard()
    return JobManager(cfg, guard, store, "http://mock-discord:8001")


@pytest.mark.asyncio
async def test_job_manager_submit_returns_message(job_manager):
    msg = await job_manager.submit("bitcoin ETF", "general")
    assert "bitcoin ETF" in msg


@pytest.mark.asyncio
async def test_job_manager_queues_at_limit(job_manager, cfg):
    cfg.research_max_concurrent = 1
    await job_manager.submit("topic 1", "general")
    msg = await job_manager.submit("topic 2", "general")
    assert "queue" in msg.lower() or "line" in msg.lower()
