import json
import socket
import pytest
import respx
import httpx
from proxy.research.engine import ResearchEngine
from proxy.research.memory import MemoryGuard
from proxy.research.storage import ResearchStore
from proxy.research.validators import SecurityValidator


AGENT_OUTPUT = {
    "findings": ["Bitcoin ETF approved by SEC [[1]](https://reuters.com/a)"],
    "prose_summary": "The SEC approved 11 spot Bitcoin ETFs in January 2024.",
    "citations": [{"index": 1, "title": "Reuters", "url": "https://reuters.com/a",
                   "domain": "reuters.com", "date": "2024-01-10"}],
    "relevance_score": 0.9,
    "contradictions": [],
    "gaps": [],
    "failed_sources": [],
}

ORCHESTRATOR_OUTPUT = {"satisfied": True, "new_queries": [], "reasoning": "sufficient coverage"}
REVIEWER_OUTPUT = {"issues": [], "approved": True}


@respx.mock
@pytest.mark.asyncio
async def test_full_research_job_completes(cfg, tmp_path, monkeypatch):
    # Monkeypatch socket.gethostbyname so SSRF check passes without real DNS
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "1.2.3.4")

    # SearxNG
    respx.get(f"{cfg.searxng_url}/search").mock(return_value=httpx.Response(200, json={
        "results": [{"title": "Reuters", "url": "https://reuters.com/a", "content": "Bitcoin ETF"}]
    }))
    # Source validation (HEAD)
    respx.head("https://reuters.com/a").mock(return_value=httpx.Response(
        200, headers={"content-type": "text/html", "content-length": "8000"}
    ))
    # Web extract (GET for content + source validation fallback)
    respx.get("https://reuters.com/a").mock(return_value=httpx.Response(
        200,
        text="<p>The SEC approved Bitcoin ETF applications in January 2024.</p>",
        headers={"content-type": "text/html"},
    ))
    # Ollama: all calls return appropriate responses
    call_count = 0

    def ollama_side_effect(request, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        body = json.loads(request.content)
        model = body.get("model", "")
        if model == cfg.research_agent_model:
            return httpx.Response(200, json={"message": {"content": json.dumps(AGENT_OUTPUT)}})
        # orchestrator model: alternate between orchestrator review and report synthesis/reviewer
        return httpx.Response(200, json={"message": {"content": json.dumps(ORCHESTRATOR_OUTPUT)}})

    respx.post(f"{cfg.ollama_host}/api/chat").mock(side_effect=ollama_side_effect)
    # Discord API
    respx.post(f"{cfg.discord_bot_api_url}/send").mock(return_value=httpx.Response(200, json={"ok": True}))
    respx.post(f"{cfg.discord_bot_api_url}/embed").mock(return_value=httpx.Response(200, json={"ok": True}))

    sec = SecurityValidator(cfg.research_max_pdf_size_mb)
    store = ResearchStore(str(tmp_path / "research"), sec)
    guard = MemoryGuard()
    engine = ResearchEngine(
        "test01", "bitcoin ETF", "general", cfg, guard, store,
        cfg.discord_bot_api_url,
    )
    await engine.run()

    # Verify report was saved
    reports = store.list_reports()
    assert len(reports) == 1
    assert "bitcoin" in reports[0]["title"].lower()

    # Verify Discord progress messages were posted
    send_calls = [r for r in respx.calls if "/send" in str(r.request.url)]
    assert len(send_calls) >= 1

    # Verify embed was posted to Discord
    embed_calls = [r for r in respx.calls if "/embed" in str(r.request.url)]
    assert len(embed_calls) >= 1
