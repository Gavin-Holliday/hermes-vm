import pytest
from proxy.research.report import ReportBuilder, ReportValidator, ResearchReport
from proxy.research.knowledge import KnowledgeBase
from proxy.research.validators import ResearcherOutput
from proxy.config import Config


def _make_kb(topic="bitcoin ETF"):
    kb = KnowledgeBase(topic)
    output = ResearcherOutput(
        findings=["Bitcoin ETF approved [[1]](https://reuters.com/a)"],
        prose_summary="The SEC approved Bitcoin ETFs.",
        citations=[{"index": 1, "title": "Reuters", "url": "https://reuters.com/a",
                    "domain": "reuters.com", "date": "2024-01-10"}],
        relevance_score=0.9,
        contradictions=[],
        gaps=[],
        failed_sources=[],
    )
    kb.ingest([output])
    return kb


def _make_cfg():
    return Config(
        ollama_host="http://mock:11434",
        research_orchestrator_model="gemma4:26b",
        research_min_sources=1,
        allowed_models=["hermes3"],
    )


def test_report_validator_all_sections():
    report = ResearchReport(
        title="Bitcoin ETF",
        summary="Summary here.",
        findings_text="Findings text [[1]](https://x.com).",
        contradictions_text="",
        sources=[{"index": 1, "title": "T", "url": "https://x.com", "domain": "x.com", "date": "2024-01-01"}],
        rounds=2,
        duration_secs=120.0,
        source_count=1,
    )
    errors = ReportValidator().validate(report)
    assert errors == []


def test_report_validator_missing_summary():
    report = ResearchReport("T", "", "findings", "", [], 1, 60.0, 0)
    errors = ReportValidator().validate(report)
    assert any("summary" in e.lower() for e in errors)


def test_build_embeds_single():
    report = ResearchReport(
        title="Bitcoin ETF",
        summary="Short summary.",
        findings_text="Finding one. Finding two.",
        contradictions_text="",
        sources=[{"index": 1, "title": "T", "url": "https://x.com", "domain": "x.com", "date": "2024-01-01"}],
        rounds=2,
        duration_secs=90.0,
        source_count=1,
    )
    builder = ReportBuilder(_make_cfg())
    embeds = builder.build_embeds(report)
    assert len(embeds) == 1
    assert embeds[0]["title"] == "Bitcoin ETF"
    assert embeds[0]["color"] == 0x4F8EF7


def test_build_embeds_overflow():
    long_findings = "This is a finding. " * 400
    report = ResearchReport("T", "Summary.", long_findings, "Contradiction.", [], 3, 200.0, 5)
    builder = ReportBuilder(_make_cfg())
    embeds = builder.build_embeds(report)
    assert len(embeds) > 1
    # footer only on last embed
    assert embeds[-1].get("footer") is not None
