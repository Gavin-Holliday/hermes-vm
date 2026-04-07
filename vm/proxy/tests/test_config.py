import os
import pytest
from proxy.config import Config, get_config


def test_config_reads_allowed_models_from_env(monkeypatch):
    monkeypatch.setenv("ALLOWED_MODELS", "hermes3,gemma4:27b")
    c = Config()
    assert c.allowed_models == ["hermes3", "gemma4:27b"]


def test_config_trims_model_whitespace(monkeypatch):
    monkeypatch.setenv("ALLOWED_MODELS", "hermes3, gemma4:27b ")
    c = Config()
    assert c.allowed_models == ["hermes3", "gemma4:27b"]


def test_config_defaults_ollama_host():
    c = Config()
    assert c.ollama_host == "http://host.containers.internal:11434"


def test_config_explicit_values_override_env():
    c = Config(ollama_host="http://custom:11434", allowed_models=["mymodel"])
    assert c.ollama_host == "http://custom:11434"
    assert c.allowed_models == ["mymodel"]


def test_get_config_returns_same_instance():
    get_config.cache_clear()
    a = get_config()
    b = get_config()
    assert a is b
