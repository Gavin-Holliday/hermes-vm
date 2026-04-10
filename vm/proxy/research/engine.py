import json
import logging

import httpx

from proxy.research.validators import (
    SecurityValidator, SourceValidator, OutputValidator, ResearcherOutput
)
from proxy.research.processors import ContentProcessor

log = logging.getLogger("hermes.research.engine")

AGENT_SYSTEM_PROMPT = """You are a research agent. Given a search query and web content, extract findings.

You MUST respond with valid JSON matching this exact schema:
{
  "findings": ["finding text with [[1]](url) citation"],
  "prose_summary": "narrative of what was found and why it matters",
  "citations": [{"index": 1, "title": "...", "url": "...", "domain": "...", "date": "YYYY-MM-DD"}],
  "relevance_score": 0.0,
  "contradictions": [],
  "gaps": [],
  "failed_sources": []
}
Only include findings supported by the provided content. Do not hallucinate facts."""


class ResearchAgent:
    def __init__(self, config, security: SecurityValidator,
                 source_validator: SourceValidator,
                 content_processor: ContentProcessor,
                 output_validator: OutputValidator):
        self._config = config
        self._security = security
        self._source_val = source_validator
        self._processor = content_processor
        self._output_val = output_validator

    async def run(self, query: str, topic: str) -> "ResearcherOutput | None":
        results = await self._search(query)
        content_parts = []
        failed = []
        for r in results[:5]:
            url = r.get("url", "")
            if not url:
                continue
            if not self._security.check_ssrf(url):
                continue
            val = await self._source_val.validate_url(url)
            if not val.valid:
                failed.append({"url": url, "reason": val.reason})
                continue
            extracted = await self._extract(url)
            if not extracted:
                continue
            processed = self._processor.process(extracted, topic, url)
            if processed:
                content_parts.append(
                    f"URL: {url}\nScore: {processed.tfidf_score:.2f}\n{processed.text[:2000]}"
                )

        if not content_parts:
            return await self._retry(query, topic, failed)

        output = await self._ollama_extract(query, content_parts)
        if output is None:
            return await self._retry(query, topic, failed)
        return output

    async def _retry(self, query: str, topic: str, failed: list) -> "ResearcherOutput | None":
        rephrased = await self._rephrase_query(query)
        if rephrased == query:
            return None
        results = await self._search(rephrased)
        content_parts = []
        for r in results[:5]:
            url = r.get("url", "")
            if not url or not self._security.check_ssrf(url):
                continue
            val = await self._source_val.validate_url(url)
            if not val.valid:
                continue
            extracted = await self._extract(url)
            if not extracted:
                continue
            processed = self._processor.process(extracted, topic, url)
            if processed:
                content_parts.append(f"URL: {url}\n{processed.text[:2000]}")
        if not content_parts:
            return None
        return await self._ollama_extract(rephrased, content_parts)

    async def _search(self, query: str) -> list:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._config.searxng_url}/search",
                    params={"q": query, "format": "json", "categories": "general"},
                )
                resp.raise_for_status()
                return resp.json().get("results", [])[:5]
        except Exception as e:
            log.warning("Search failed for %r: %s", query, e)
            return []

    async def _extract(self, url: str) -> "str | None":
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code != 200:
                    return None
                ct = resp.headers.get("content-type", "")
                if not self._security.enforce_content_type(ct):
                    return None
                if not self._security.enforce_size_limit(resp.content, ct):
                    return None
                if "pdf" in ct:
                    from proxy.research.processors import PDFProcessor
                    return PDFProcessor(self._security).process(resp.content)
                return resp.text
        except Exception:
            return None

    async def _ollama_extract(self, query: str, content_parts: list) -> "ResearcherOutput | None":
        content_text = "\n\n---\n\n".join(content_parts)
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Query: {query}\n\nContent:\n{content_text}"},
        ]
        raw = await self._ollama_call(self._config.research_agent_model, messages)
        try:
            data = json.loads(raw)
            return self._output_val.validate(data)
        except Exception:
            return None

    async def _rephrase_query(self, query: str) -> str:
        messages = [
            {"role": "system", "content": "Rephrase search queries. Return only the rephrased query, nothing else."},
            {"role": "user", "content": f"Rephrase this search query to find the same information differently: {query}"},
        ]
        result = await self._ollama_call(self._config.research_agent_model, messages)
        return result.strip() or query

    async def _ollama_call(self, model: str, messages: list) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._config.ollama_host}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
