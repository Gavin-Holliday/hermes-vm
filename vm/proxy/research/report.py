import json
import logging
import re
from dataclasses import dataclass

import httpx

log = logging.getLogger("hermes.research.report")

_CITATION_RE = re.compile(r'\[\[(\d+)\]\]\([^)]+\)')


@dataclass
class ResearchReport:
    title: str
    summary: str
    findings_text: str
    contradictions_text: str
    sources: list
    rounds: int
    duration_secs: float
    source_count: int


class ReportValidator:
    MAX_CHARS = 5800

    def validate(self, report: ResearchReport) -> list:
        errors = []
        if not report.title.strip():
            errors.append("title is empty")
        if not report.summary.strip():
            errors.append("summary is empty")
        if not report.findings_text.strip():
            errors.append("findings text is empty")
        total = len(report.title) + len(report.summary) + len(report.findings_text)
        if total > self.MAX_CHARS:
            errors.append(f"total chars {total} exceeds budget {self.MAX_CHARS}")
        return errors


class ReportBuilder:
    def __init__(self, config, ollama_sem=None):
        self._config = config
        self._validator = ReportValidator()
        self._ollama_sem = ollama_sem

    async def build(self, topic: str, kb, rounds: int, duration_secs: float) -> ResearchReport:
        summary_text = kb.compact_summary()
        sources = kb.all_sources()

        # Synthesize report via orchestrator
        report_text = await self._ollama_synthesize(topic, summary_text)

        # Reviewer pass
        approved, issues = await self._ollama_review(report_text)
        if not approved:
            report_text = await self._ollama_revise(report_text, issues)

        # Extract summary (first sentence) and findings
        sentences = report_text.split(". ")
        summary = sentences[0] + "." if sentences else report_text[:300]
        findings = report_text[len(summary):].strip() or report_text

        return ResearchReport(
            title=topic[:256],
            summary=summary[:400],
            findings_text=findings,
            contradictions_text=self._extract_contradictions(kb),
            sources=sources,
            rounds=rounds,
            duration_secs=duration_secs,
            source_count=len(sources),
        )

    def build_embeds(self, report: ResearchReport) -> list:
        sources_text = "\n".join(
            f"[{s['index']}] {s.get('title', 'Source')} ({s.get('domain', '')})\n{s.get('url', '')}"
            for s in report.sources
        )
        footer = {
            "text": f"{report.source_count} sources · {report.rounds} rounds · "
                    f"{int(report.duration_secs // 60)}m {int(report.duration_secs % 60)}s"
        }
        main_content = f"{report.summary}\n\n**Findings**\n{report.findings_text}"

        # Chunk main_content into 4096-char pages
        pages = _chunk_text(main_content, 4096)
        embeds = []
        for i, page in enumerate(pages):
            e = {
                "title": report.title if i == 0 else f"{report.title} (cont.)",
                "description": page,
                "color": 0x4F8EF7,
                "fields": [],
            }
            # Attach sources/contradictions as fields on the last content embed
            if i == len(pages) - 1:
                if report.contradictions_text:
                    e["fields"].append({
                        "name": "Alternative Views",
                        "value": report.contradictions_text[:1024],
                        "inline": False,
                    })
                e["fields"].append({
                    "name": "Sources",
                    "value": sources_text[:1024] or "No sources",
                    "inline": False,
                })
                e["footer"] = footer
            embeds.append(e)

        # If sources overflow the field (>1024), paginate into dedicated source embeds
        if len(sources_text) > 1024:
            source_pages = _chunk_text(sources_text, 4096)
            for j, src_page in enumerate(source_pages):
                src_embed = {
                    "title": f"{report.title} — Sources" if j == 0 else f"{report.title} — Sources (cont.)",
                    "description": src_page,
                    "color": 0x4F8EF7,
                    "fields": [],
                }
                if j == len(source_pages) - 1:
                    src_embed["footer"] = footer
                embeds.append(src_embed)

        return embeds

    def _extract_contradictions(self, kb) -> str:
        contradicting = kb.contradicting_findings()
        if not contradicting:
            return ""
        return "\n".join(f"• {t}" for t in contradicting[:5])

    async def _ollama_synthesize(self, topic: str, summary: str) -> str:
        prompt = (
            f"Write a comprehensive research report on: {topic}\n\n"
            f"Use this knowledge base:\n{summary}\n\n"
            f"Include inline citations as [[N]](url) for every factual claim. "
            f"Be accurate and concise."
        )
        return await self._ollama_call([
            {"role": "system", "content": "You are a research report writer. Write factual, well-cited reports."},
            {"role": "user", "content": prompt},
        ])

    async def _ollama_review(self, report_text: str) -> tuple:
        from proxy.research.engine import _strip_json_fences
        prompt = f"Review this report for unsupported claims and missing citations:\n\n{report_text}"
        raw = await self._ollama_call([
            {"role": "system", "content": 'You are a fact-checker. Respond with JSON: {"issues": [], "approved": true}'},
            {"role": "user", "content": prompt},
        ], fmt="json")
        try:
            data = json.loads(_strip_json_fences(raw))
            return data.get("approved", False), data.get("issues", [])
        except Exception:
            return True, []

    async def _ollama_revise(self, report_text: str, issues: list) -> str:
        prompt = (
            f"Revise this report to fix these issues:\n{chr(10).join(issues)}\n\n"
            f"Original report:\n{report_text}"
        )
        return await self._ollama_call([
            {"role": "system", "content": "You are a research report writer. Fix the identified issues."},
            {"role": "user", "content": prompt},
        ])

    async def _ollama_call(self, messages: list, fmt: str = None) -> str:
        from proxy.research.engine import ollama_call
        return await ollama_call(
            self._config.ollama_host,
            self._config.research_report_model,
            messages,
            self._ollama_sem,
            fmt,
            timeout=300.0,
        )


def _chunk_text(text: str, max_len: int) -> list:
    """Split text into chunks of at most max_len chars, breaking on newlines where possible."""
    chunks = []
    while len(text) > max_len:
        split = text.rfind("\n", 0, max_len)
        if split == -1:
            split = max_len
        chunks.append(text[:split])
        text = text[split:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks
