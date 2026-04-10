import pytest
from proxy.research.processors import ContentProcessor, ProcessedContent


@pytest.fixture
def proc():
    return ContentProcessor()


def test_strip_boilerplate_removes_nav(proc):
    html = "<nav>Menu</nav><main><p>Real content here</p></main><footer>Footer</footer>"
    result = proc.strip_boilerplate(html)
    assert "Menu" not in result
    assert "Footer" not in result
    assert "Real content" in result


def test_extract_dates_iso(proc):
    text = "The event happened on 2024-01-10 and ended 2024-03-15."
    dates = proc.extract_dates(text)
    assert "2024-01-10" in dates
    assert "2024-03-15" in dates


def test_extract_dates_natural(proc):
    text = "Published January 10, 2024 by Reuters."
    dates = proc.extract_dates(text)
    assert any("2024" in d for d in dates)


def test_tfidf_score_relevant(proc):
    topic = "bitcoin ETF approval"
    text = "The bitcoin ETF was approved by the SEC. Bitcoin ETF trading began immediately."
    score = proc.tfidf_score(text, topic)
    assert score > 0.3


def test_tfidf_score_irrelevant(proc):
    topic = "bitcoin ETF approval"
    text = "The weather today is sunny with a chance of rain in the afternoon."
    score = proc.tfidf_score(text, topic)
    assert score < 0.1


def test_language_detection_english(proc):
    assert proc.detect_language("The quick brown fox jumps over the lazy dog.") == "en"


def test_language_detection_non_english(proc):
    assert proc.detect_language("日本語のテキストはここです。漢字が含まれています。") == "other"


def test_dedup_returns_none_second_time(proc):
    html = "<p>Some unique content about bitcoin</p>"
    first = proc.process(html, "bitcoin", "https://example.com")
    second = proc.process(html, "bitcoin", "https://example.com")
    assert first is not None
    assert second is None
