import pytest
from proxy.config import Config


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        ollama_host="http://mock-ollama:11434",
        allowed_models=["hermes3", "gemma4:27b"],
        searxng_url="http://mock-searxng:8080",
        rate_limit_burst=20,
        rate_limit_per_min=60,
        max_tool_rounds=10,
        tool_timeout_secs=30,
        system_prompt="You are Hermes, a helpful assistant.",
        workspace_path=str(tmp_path / "workspace"),
        data_path=str(tmp_path / "data"),
        vision_model="gemma4:e4b",
        research_agent_model="gemma4:e4b",
        research_orchestrator_model="gemma4:26b",
        research_max_rounds=2,
        research_timeout_mins=5,
        research_novelty_threshold=0.20,
        research_max_concurrent=2,
        research_memory_threshold_pct=20,
        research_memory_critical_pct=10,
        research_max_pdf_size_mb=10,
        research_min_sources=3,
        research_max_redirect_depth=3,
        research_data_path=str(tmp_path / "research"),
        research_ollama_parallel=1,
    )
