import json
import pytest
from pathlib import Path
from proxy.research.storage import ResearchStore
from proxy.research.validators import SecurityValidator


@pytest.fixture
def store(tmp_path):
    return ResearchStore(str(tmp_path / "research"), SecurityValidator())


def test_save_creates_file(store, tmp_path):
    store.save("bitcoin ETF", "report text", [], {}, {"duration_secs": 100})
    files = [f for f in (tmp_path / "research").glob("*.json") if f.name != "index.json"]
    assert len(files) == 1


def test_save_updates_index(store, tmp_path):
    store.save("bitcoin ETF", "report text", [], {}, {})
    index_path = tmp_path / "research" / "index.json"
    assert index_path.exists()
    index = json.loads(index_path.read_text())
    assert len(index) == 1


def test_load_by_exact_title(store):
    store.save("bitcoin ETF", "report text", [], {}, {})
    result = store.load_by_title("bitcoin ETF")
    assert result is not None
    assert result["report_text"] == "report text"


def test_load_by_fuzzy_title(store):
    store.save("Bitcoin ETF Approval 2024", "report text", [], {}, {})
    result = store.load_by_title("bitcoin etf approval")
    assert result is not None


def test_load_missing_returns_none(store):
    result = store.load_by_title("nonexistent topic xyz")
    assert result is None


def test_filename_sanitized(store, tmp_path):
    store.save("Hello World! 2025?", "text", [], {}, {})
    files = [f for f in (tmp_path / "research").glob("*.json") if f.name != "index.json"]
    assert len(files) == 1
    assert "!" not in files[0].name
    assert "?" not in files[0].name
