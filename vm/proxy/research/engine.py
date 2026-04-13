import asyncio
import json
import logging
import time
import uuid

import httpx

from proxy.research.validators import (
    SecurityValidator, SourceValidator, OutputValidator, ResearcherOutput
)
from proxy.research.processors import ContentProcessor

log = logging.getLogger("hermes.research.engine")

def _strip_json_fences(text: str) -> str:
    """Strip markdown code fences that models often wrap JSON in."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = text[text.index("\n") + 1:] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[: text.rfind("```")]
    return text.strip()


async def ollama_call(ollama_host: str, model: str, messages: list,
                      sem: "asyncio.Semaphore | None" = None,
                      fmt: "str | None" = None,
                      timeout: float = 120.0) -> str:
    """Module-level Ollama chat helper shared by agents and orchestrator.

    Pass sem to serialize concurrent callers — Ollama runs one inference at a
    time, so parallel agents must queue rather than all timing out together.
    The semaphore is acquired before opening the connection so the timeout
    only starts once Ollama is actually free.
    Pass fmt="json" to engage Ollama's JSON mode and avoid markdown-wrapped output.
    Pass timeout to override the default 120s (use higher values for large models).
    """
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if fmt:
        payload["format"] = fmt

    async def _call() -> str:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{ollama_host}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    if sem is not None:
        async with sem:
            return await _call()
    return await _call()


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
                 output_validator: OutputValidator,
                 ollama_sem: asyncio.Semaphore):
        self._config = config
        self._security = security
        self._source_val = source_validator
        self._processor = content_processor
        self._output_val = output_validator
        self._ollama_sem = ollama_sem

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
        raw = await self._ollama_call(self._config.research_agent_model, messages, fmt="json")
        try:
            data = json.loads(_strip_json_fences(raw))
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

    async def _ollama_call(self, model: str, messages: list, fmt: str = None) -> str:
        return await ollama_call(self._config.ollama_host, model, messages, self._ollama_sem, fmt, timeout=240.0)


from proxy.research.knowledge import KnowledgeBase
from proxy.research.queries import QueryManager
from proxy.research.report import ReportBuilder
from proxy.research.memory import MemoryGuard
from proxy.research.storage import ResearchStore

ORCHESTRATOR_SYSTEM_PROMPT = """You are a research orchestrator reviewing agent findings.
Given a knowledge base summary, respond with JSON:
{"satisfied": false, "new_queries": ["query1", "query2"], "reasoning": "..."}
Set satisfied=true only when you have comprehensive coverage of the topic."""


class ResearchEngine:
    def __init__(self, job_id: str, topic: str, channel: str, config,
                 memory_guard: MemoryGuard, store: ResearchStore,
                 discord_api_url: str, mode: str = "research",
                 verbosity: str = "normal"):
        self.job_id = job_id
        self._topic = topic
        self._channel = channel
        self._report_channel = config.research_report_channel or channel
        self._verbosity = verbosity  # "silent" | "normal" | "verbose"
        self._config = config
        self._memory_guard = memory_guard
        self._store = store
        self._discord_api_url = discord_api_url
        self._mode = mode
        self._kb = KnowledgeBase(topic)
        self._qm = QueryManager()
        self._security = SecurityValidator(config.research_max_pdf_size_mb)
        self._source_val = SourceValidator(self._security, config.research_max_redirect_depth)
        self._processor = ContentProcessor()
        self._output_val = OutputValidator()
        # Limit concurrent Ollama calls to match OLLAMA_NUM_PARALLEL on the host
        self._ollama_sem = asyncio.Semaphore(config.research_ollama_parallel)
        self._agent = ResearchAgent(config, self._security, self._source_val,
                                    self._processor, self._output_val, self._ollama_sem)
        self._builder = ReportBuilder(config, self._ollama_sem)

    async def run(self) -> None:
        start = time.monotonic()
        await self._post_progress("Starting — generating research queries...")
        self._qm.expand(self._topic)
        satisfied = False
        verification_done = False
        round_num = 0

        for round_num in range(1, self._config.research_max_rounds + 1):
            elapsed_mins = (time.monotonic() - start) / 60
            if elapsed_mins >= self._config.research_timeout_mins:
                await self._post_progress("Time limit reached — building report...")
                break

            while self._memory_guard.should_pause_research():
                await asyncio.sleep(10)

            queries = self._qm.next_batch(5)
            if not queries:
                break

            await self._post_progress(f"Round {round_num} — researching {len(queries)} subtopics...")
            outputs = await asyncio.gather(*[self._agent.run(q, self._topic) for q in queries])
            valid = [o for o in outputs if o is not None]
            self._kb.ingest(valid)
            self._kb.increment_round()

            coverage = self._kb.coverage_score()
            novelty = self._kb.novelty_rate()
            failed_agents = sum(1 for o in outputs if o is None)

            for q, out in zip(queries, outputs):
                if out:
                    await self._post_progress(
                        f"  `{q}` → {len(out.findings)} findings (relevance {out.relevance_score:.0%})",
                        min_verbosity="verbose",
                    )
                else:
                    await self._post_progress(f"  `{q}` → no findings", min_verbosity="verbose")

            await self._post_progress(
                f"Round {round_num} complete — {len(valid)}/{len(queries)} agents found content"
                + (f" ({failed_agents} failed)" if failed_agents else "")
                + f" · {coverage:.0%} coverage · novelty {novelty:.0%}"
            )
            import psutil
            mem = psutil.virtual_memory()
            await self._post_progress(
                f"RAM {mem.percent:.0f}% used ({mem.available // (1024**3):.1f}GB free)",
                min_verbosity="verbose",
            )

            if novelty < self._config.research_novelty_threshold and round_num > 1:
                await self._post_progress(
                    f"Novelty {novelty:.0%} below threshold {self._config.research_novelty_threshold:.0%} — diminishing returns, building report...",
                )
                break

            if satisfied and not verification_done:
                verification_done = True
                await self._post_progress("Sufficient findings — running verification round...")
                self._qm.add_from_gaps([
                    f"criticism of {self._topic}",
                    f"{self._topic} problems issues counterargument",
                ])
                continue

            if satisfied and verification_done:
                break

            review = await self._orchestrator_review()
            if review.get("satisfied"):
                satisfied = True
            for q in review.get("new_queries", []):
                self._qm.add_from_gaps([q])

        duration = time.monotonic() - start
        await self._post_progress("Synthesizing report...")
        report = await self._builder.build(self._topic, self._kb, round_num, duration)
        await self._post_progress("Running self-review...")
        embeds = self._builder.build_embeds(report)
        for embed in embeds:
            await self._post_embed(embed)
        self._store.save(
            topic=self._topic,
            report_text=report.findings_text,
            sources=self._kb.all_sources(),
            kb_snapshot={"findings_count": self._kb.findings_count()},
            metadata={
                "agent_model": self._config.research_agent_model,
                "orchestrator_model": self._config.research_orchestrator_model,
                "duration_secs": int(duration),
                "rounds": round_num,
            },
        )
        await self._post_progress(
            f"Complete — {report.source_count} sources · {round_num} rounds · "
            f"{int(duration // 60)}m {int(duration % 60)}s"
        )

    async def _orchestrator_review(self) -> dict:
        summary = self._kb.compact_summary()
        messages = [
            {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Topic: {self._topic}\nCoverage: {self._kb.coverage_score():.0%}\n\n{summary}"
            )},
        ]
        raw = await ollama_call(self._config.ollama_host, self._config.research_orchestrator_model, messages, self._ollama_sem, fmt="json", timeout=300.0)
        try:
            return json.loads(_strip_json_fences(raw))
        except Exception:
            return {"satisfied": False, "new_queries": [], "reasoning": "parse error"}

    async def _post_progress(self, message: str, min_verbosity: str = "normal") -> None:
        if self._verbosity == "silent":
            return
        if min_verbosity == "verbose" and self._verbosity != "verbose":
            return
        text = f"[Research: '{self._topic}'] {message}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{self._discord_api_url}/send",
                    json={"channel_name": self._channel, "content": text},
                )
        except Exception:
            pass

    async def _post_embed(self, embed: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self._discord_api_url}/embed",
                    json={**embed, "channel_name": self._report_channel},
                )
        except Exception:
            pass


class JobManager:
    def __init__(self, config, memory_guard: MemoryGuard, store: ResearchStore,
                 discord_api_url: str):
        self._config = config
        self._memory_guard = memory_guard
        self._store = store
        self._discord_api_url = discord_api_url
        self._active: dict = {}
        self._queue: list = []

    async def submit(self, topic: str, channel: str, mode: str = "research",
                     seed_urls: list = None, verbosity: str = "normal") -> str:
        job_id = str(uuid.uuid4())[:8]
        if len(self._active) < self._config.research_max_concurrent:
            await self._start_job(job_id, topic, channel, mode, verbosity)
            return f"Research started on '{topic}' (job {job_id})"
        else:
            self._queue.append((job_id, topic, channel, mode, verbosity))
            return f"Research queued (#{len(self._queue)} in line) — '{topic}'"

    async def _start_job(self, job_id: str, topic: str, channel: str, mode: str,
                         verbosity: str = "normal") -> None:
        engine = ResearchEngine(
            job_id, topic, channel, self._config,
            self._memory_guard, self._store,
            self._discord_api_url, mode, verbosity,
        )
        self._active[job_id] = engine
        self._memory_guard.set_research_active({
            self._config.research_agent_model,
            self._config.research_orchestrator_model,
        })
        asyncio.create_task(self._run_job(job_id, engine))

    async def _run_job(self, job_id: str, engine: ResearchEngine) -> None:
        try:
            await engine.run()
        except Exception as exc:
            log.error("Research job %s failed: %s", job_id, exc, exc_info=True)
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        f"{self._discord_api_url}/send",
                        json={
                            "channel_name": engine._channel,
                            "content": f"Research on '{engine._topic}' failed: {exc}",
                        },
                    )
            except Exception:
                pass
        finally:
            self._active.pop(job_id, None)
            if not self._active:
                self._memory_guard.set_research_inactive()
            if self._queue:
                next_args = self._queue.pop(0)
                await self._start_job(*next_args)
