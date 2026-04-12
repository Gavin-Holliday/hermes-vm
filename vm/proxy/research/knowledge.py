import hashlib
import re
from dataclasses import dataclass, field

from proxy.research.validators import ResearcherOutput


@dataclass
class Finding:
    text: str
    source_indices: list
    relevance: float
    contradicts_topic: bool
    round_found: int
    content_hash: str


class FindingStore:
    def __init__(self):
        self._findings: list = []
        self._hashes: set = set()

    def add(self, finding: Finding) -> bool:
        if finding.content_hash in self._hashes:
            return False
        self._hashes.add(finding.content_hash)
        self._findings.append(finding)
        return True

    def prune(self, max_size: int = 200) -> None:
        if len(self._findings) <= max_size:
            return
        # Count how many findings support each source index
        index_counts: dict = {}
        for f in self._findings:
            for idx in f.source_indices:
                index_counts[idx] = index_counts.get(idx, 0) + 1

        def is_sole_support(f: Finding) -> bool:
            return any(index_counts.get(i, 0) == 1 for i in f.source_indices)

        sorted_findings = sorted(self._findings, key=lambda f: f.relevance)
        pruned = []
        removed = 0
        target = len(self._findings) - max_size
        for f in sorted_findings:
            if removed < target and not is_sole_support(f):
                self._hashes.discard(f.content_hash)
                removed += 1
            else:
                pruned.append(f)
        self._findings = pruned

    def all(self) -> list:
        return list(self._findings)

    def by_relevance(self) -> list:
        return sorted(self._findings, key=lambda f: f.relevance, reverse=True)


class KnowledgeBase:
    def __init__(self, topic: str):
        self._topic = topic
        self._store = FindingStore()
        self._sources: list = []
        self._source_urls: set = set()
        self._round = 0
        self._round_added: int = 0
        self._round_total: int = 0

    def ingest(self, outputs: list) -> None:
        self._round_added = 0
        self._round_total = 0
        for output in outputs:
            for src in output.citations:
                url = src.get("url", "")
                if url and url not in self._source_urls:
                    self._sources.append(src)
                    self._source_urls.add(url)
            for text in output.findings:
                self._round_total += 1
                h = hashlib.sha256(text.lower().encode()).hexdigest()
                finding = Finding(
                    text=text,
                    source_indices=[c["index"] for c in output.citations],
                    relevance=output.relevance_score,
                    contradicts_topic=bool(output.contradictions),
                    round_found=self._round,
                    content_hash=h,
                )
                if self._store.add(finding):
                    self._round_added += 1
        self._store.prune()

    def coverage_score(self) -> float:
        terms = [t.lower() for t in self._topic.split() if len(t) > 2]
        if not terms:
            return 0.0
        all_text = " ".join(f.text.lower() for f in self._store.all())
        covered = sum(1 for t in terms if t in all_text)
        return covered / len(terms)

    def novelty_rate(self) -> float:
        if self._round_total == 0:
            return 1.0
        return self._round_added / self._round_total

    def compact_summary(self, max_tokens: int = 2000) -> str:
        max_chars = max_tokens * 4
        findings = self._store.by_relevance()
        lines = [
            f"## Knowledge Base: {self._topic}",
            f"Coverage: {self.coverage_score():.0%} | Sources: {len(self._sources)} | Findings: {len(findings)}",
            "",
        ]
        for f in findings:
            line = f"- [{f.relevance:.2f}] {f.text}"
            if f.contradicts_topic:
                line += " [CONTRADICTS]"
            lines.append(line)
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[truncated]"
        return text

    def all_sources(self) -> list:
        return list(self._sources)

    def validated_urls(self) -> set:
        return set(self._source_urls)

    def contradicting_findings(self) -> list:
        return [f.text for f in self._store.all() if f.contradicts_topic]

    def findings_count(self) -> int:
        return len(self._store.all())

    def increment_round(self) -> None:
        self._round += 1
