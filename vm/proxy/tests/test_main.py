import pytest
import httpx
import respx
from fastapi.testclient import TestClient
from proxy.config import Config, get_config
from proxy.main import create_app


@pytest.fixture
def cfg():
    return Config(
        ollama_host="http://mock-ollama:11434",
        allowed_models=["hermes3", "gemma4:27b"],
        searxng_url="http://mock-searxng:8080",
        rate_limit_burst=100,
        rate_limit_per_min=600,
        max_tool_rounds=10,
        tool_timeout_secs=30,
        system_prompt="You are Hermes.",
    )


@pytest.fixture
def client(cfg):
    app = create_app(cfg)
    return TestClient(app)


# --- Health ---

def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- Blocked endpoints ---

def test_pull_returns_403(client):
    resp = client.post("/api/pull", json={"name": "llama3"})
    assert resp.status_code == 403

def test_delete_returns_403(client):
    resp = client.request("DELETE", "/api/delete", json={"name": "llama3"})
    assert resp.status_code == 403

def test_copy_returns_403(client):
    resp = client.post("/api/copy", json={"source": "a", "destination": "b"})
    assert resp.status_code == 403

def test_unknown_endpoint_returns_403(client):
    resp = client.post("/api/unknown")
    assert resp.status_code == 403


# --- Rate limiting ---

def test_rate_limited_request_returns_429():
    burst_one_cfg = Config(
        ollama_host="http://mock-ollama:11434",
        allowed_models=["hermes3"],
        searxng_url="http://mock-searxng:8080",
        rate_limit_burst=1,
        rate_limit_per_min=1,
        max_tool_rounds=10,
        tool_timeout_secs=30,
        system_prompt="You are Hermes.",
    )
    burst_one_client = TestClient(create_app(burst_one_cfg))
    burst_one_client.get("/health")  # consumes the 1 token
    resp = burst_one_client.get("/health")  # should be rate limited
    assert resp.status_code == 429


# --- Passthrough endpoints ---

@respx.mock
def test_tags_passthrough_to_ollama(client):
    respx.get("http://mock-ollama:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "hermes3"}]})
    )
    resp = client.get("/api/tags")
    assert resp.status_code == 200
    assert resp.json()["models"][0]["name"] == "hermes3"


@respx.mock
def test_version_passthrough_to_ollama(client):
    respx.get("http://mock-ollama:11434/api/version").mock(
        return_value=httpx.Response(200, json={"version": "0.3.0"})
    )
    resp = client.get("/api/version")
    assert resp.status_code == 200
    assert resp.json()["version"] == "0.3.0"
