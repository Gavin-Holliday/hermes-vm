import pytest
from proxy.research.knowledge import KnowledgeBase, Finding, FindingStore
from proxy.research.validators import ResearcherOutput


def _make_output(findings, sources, relevance=0.8):
    return ResearcherOutput(
        findings=findings,
        prose_summary="summary",
        citations=[
            {"index": i + 1, "title": f"T{i}", "url": s, "domain": "x.com", "date": "2024-01-01"}
            for i, s in enumerate(sources)
        ],
        relevance_score=relevance,
        contradictions=[],
        gaps=[],
        failed_sources=[],
    )


def test_ingest_adds_findings():
    kb = KnowledgeBase("bitcoin ETF")
    output = _make_output(["Bitcoin ETF approved"], ["https://reuters.com"])
    kb.ingest([output])
    assert len(kb._store.all()) == 1


def test_ingest_deduplicates():
    kb = KnowledgeBase("bitcoin ETF")
    output = _make_output(["Bitcoin ETF approved"], ["https://reuters.com"])
    kb.ingest([output])
    kb.ingest([output])
    assert len(kb._store.all()) == 1


def test_coverage_score_full():
    kb = KnowledgeBase("bitcoin etf")
    output = _make_output(["bitcoin etf approved"], ["https://x.com"])
    kb.ingest([output])
    assert kb.coverage_score() > 0.8


def test_coverage_score_partial():
    kb = KnowledgeBase("bitcoin etf approval sec")
    output = _make_output(["bitcoin price rose"], ["https://x.com"])
    kb.ingest([output])
    assert 0.0 < kb.coverage_score() < 1.0


def test_novelty_rate_first_round():
    kb = KnowledgeBase("topic")
    output = _make_output(["new finding"], ["https://x.com"])
    kb.ingest([output])
    assert kb.novelty_rate() == 1.0


def test_novelty_rate_no_new():
    kb = KnowledgeBase("topic")
    output = _make_output(["same finding"], ["https://x.com"])
    kb.ingest([output])
    kb.increment_round()
    kb.ingest([output])
    assert kb.novelty_rate() == 0.0


def test_compact_summary_is_string():
    kb = KnowledgeBase("bitcoin ETF")
    output = _make_output(["Bitcoin ETF approved by SEC"], ["https://reuters.com"])
    kb.ingest([output])
    summary = kb.compact_summary()
    assert isinstance(summary, str)
    assert len(summary) > 0


def test_compact_summary_within_limit():
    kb = KnowledgeBase("topic")
    for i in range(50):
        output = _make_output(
            [f"finding number {i} about various topics"],
            [f"https://src{i}.com"]
        )
        kb.ingest([output])
    summary = kb.compact_summary(max_tokens=4000)
    assert len(summary) <= 4000 * 4


def test_finding_store_prune_keeps_sole_support():
    store = FindingStore()
    for i in range(5):
        store.add(Finding(f"finding {i}", [i], 0.1, False, 1, f"hash{i}"))
    store.add(Finding("important sole finding", [99], 0.9, False, 1, "hashimportant"))
    store.prune(max_size=3)
    texts = [f.text for f in store.all()]
    assert "important sole finding" in texts
