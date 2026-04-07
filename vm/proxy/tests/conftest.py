import pytest
from proxy.config import Config


@pytest.fixture
def cfg() -> Config:
    return Config(
        ollama_host="http://mock-ollama:11434",
        allowed_models=["hermes3", "gemma4:27b"],
        searxng_url="http://mock-searxng:8080",
        rate_limit_burst=20,
        rate_limit_per_min=60,
        max_tool_rounds=10,
        tool_timeout_secs=30,
        system_prompt="You are Hermes, a helpful assistant.",
    )
