# Deep Research System — Design Spec
**Date:** 2026-04-10
**Status:** Approved for implementation

---

## 1. Overview

A multi-agent deep research system for Hermes that performs iterative, source-validated web research and delivers a formatted Discord embed report with inline citations. Research runs as a background asyncio task so chat continues uninterrupted. A companion deep dive mode focuses narrowly on high-quality validated sources from a prior report or user-supplied URLs.

**Design principle:** If a machine can verify it objectively, a model never touches it. Every deterministic check (URL validation, schema enforcement, citation cross-reference, SSRF protection, prompt injection scanning) is handled in pure Python. Models are only invoked for tasks that genuinely require judgment: relevance scoring, synthesis, gap analysis, and report writing.

---

## 2. Trigger Modes

### Slash Command (user-initiated)
```
/research <topic> [researcher_model] [orchestrator_model] [max_rounds] [timeout_mins]
/deepdive <topic> [url] [researcher_model] [orchestrator_model]
```

### Model-initiated (tool call)
The model may call `deep_research(topic, channel)` or `deepdive(topic, channel, urls)` autonomously when a question warrants deep research. Both tools spawn a background task and return immediately with a confirmation string. The model acknowledges this to the user and the conversation continues normally.

---

## 3. Architecture & Data Flow

```
User triggers /research "topic"
        │
        ▼
JobManager
  - checks active_jobs < max_concurrent
  - if at limit: queues job, posts "Queued (#N in line)"
  - else: spawns ResearchEngine as asyncio background task
  - posts "Research started on '[topic]'..."
        │
        ▼
ResearchEngine.__init__
  - QueryManager.expand(topic) → initial query list
  - KnowledgeBase initialized (empty)
  - MemoryGuard checked
        │
        ▼
Round Loop — exit priority order (first condition met wins):
  1. timeout_mins elapsed → exit immediately, build report from current KB
  2. max_rounds hit → exit, build report
  3. novelty_rate < RESEARCH_NOVELTY_THRESHOLD → diminishing returns, exit
  4. orchestrator satisfied → force one verification round, then exit
  (novelty threshold takes precedence over orchestrator satisfaction to prevent
   runaway loops where the orchestrator keeps finding marginal new queries)
  │
  ├─ 0. MemoryGuard.check() — pause here (not mid-round) if PRESSURE state
  │
  ├─ 1. QueryManager issues N queries for this round (deduplicated, cached)
  │
  ├─ 2. Dispatch N ResearchAgents in parallel (asyncio.gather)
  │       Each agent:
  │         a. web_search(query) → 5 results (title, url, snippet)
  │         b. SecurityValidator.check_ssrf(url) per result → discard private IPs
  │         c. SourceValidator.validate_url(url) → HTTP status, content-type,
  │            content-length, paywall detection, redirect depth
  │         d. ContentProcessor.process(url) → boilerplate strip, entity extract,
  │            date extract, TF-IDF pre-score, PDF handling if applicable
  │         e. Ollama call (agent model, clean context):
  │            input: query + processed content + TF-IDF scores
  │            output: ResearcherOutput (structured JSON + prose_summary)
  │         f. OutputValidator.validate_schema(output) → enforce schema
  │         g. Agent-level retry: if all sources failed validation →
  │            rephrase query, retry once
  │         h. Escalate to orchestrator if retry also fails
  │
  ├─ 3. KnowledgeBase.ingest(all agent outputs)
  │       - deduplicate findings by hash
  │       - claim pattern detection → flag potential contradictions
  │       - source agreement counting → confidence signals
  │       - coverage score updated (% of topic key terms addressed)
  │       - novelty rate calculated (% of new findings this round)
  │
  ├─ 4. Orchestrator review (orchestrator model)
  │       input: compact KB summary + coverage score + novelty rate + gap list
  │       output: { satisfied: bool, new_queries: [...], reasoning: str }
  │       NOTE: orchestrator never sees raw web text — only KB summary
  │
  ├─ 5. If satisfied → force one verification round
  │       adversarial queries: challenge assumptions, look for contradictions,
  │       search for opposing viewpoints
  │       then → exit loop
  │
  └─ 6. Exit conditions evaluated after each round (see priority order above)
        │
        ▼
ReportBuilder
  ├─ Orchestrator synthesizes draft report with inline [[N]](url) citations
  ├─ CitationAuditor.audit(report, sources):
  │    - every [N] in text has a corresponding source entry
  │    - every source URL was validated (HTTP 200)
  │    - no orphaned citations
  │    - minimum source count enforced
  ├─ SecurityValidator.scan_prompt_injection(report) on final text
  ├─ Separate reviewer Ollama call (same orchestrator model, skeptic prompt):
  │    "Find unsupported claims, missing context, logical gaps, weak citations"
  │    → orchestrator revises if issues flagged
  ├─ ReportValidator.validate_structure():
  │    - required sections present (title, summary, findings, sources)
  │    - character budget enforced
  │    - readability score (Flesch-Kincaid)
  └─ discord_embed posted (overflow → sequential embeds)
        │
        ▼
ResearchStore.save(report, knowledge_base, metadata)
  - filename: YYYY-MM-DD-{sanitized-title}.json
  - index.json updated
  - memory KV store updated (title → filepath)
```

---

## 4. ResearcherOutput Schema

Each agent returns structured JSON with a prose supplement. The orchestrator receives parsed structured data; prose is included for nuanced review.

```json
{
  "findings": [
    "The SEC approved 11 spot Bitcoin ETFs on January 10, 2024 [[1]](url)"
  ],
  "prose_summary": "Narrative of what was found and why it matters in context of the research topic",
  "citations": [
    {
      "index": 1,
      "title": "SEC Approves Bitcoin ETFs",
      "url": "https://reuters.com/...",
      "domain": "reuters.com",
      "date": "2024-01-10"
    }
  ],
  "relevance_score": 0.92,
  "contradictions": [
    "Source claims X while the premise assumes Y — notable because..."
  ],
  "gaps": [
    "Still unclear about Z — suggest follow-up query: 'Z explanation 2025'"
  ],
  "failed_sources": [
    { "url": "https://...", "reason": "404" }
  ]
}
```

`OutputValidator` enforces this schema strictly. Any agent output that fails schema validation is discarded and logged — the orchestrator never sees malformed output.

---

## 5. Module Breakdown

### `engine.py` — ResearchEngine, ResearchAgent, JobManager

**JobManager:**
- Tracks `active_jobs: dict[job_id, ResearchEngine]`
- Enforces `RESEARCH_MAX_CONCURRENT` limit
- Queues overflow jobs with Discord status messages
- Releases slot and starts next queued job when a job completes
- Each job identified by UUID, posted in Discord progress updates

**ResearchEngine:**
- Owns the round loop, orchestrator Ollama calls, progress posting
- Never touches raw web text — receives `ResearcherOutput` objects only
- Posts progress messages: `"[Research: 'topic'] Round 2 — researching 4 subtopics..."`
- Calls `MemoryGuard.check()` before each round — pauses between rounds if `PRESSURE`

**ResearchAgent:**
- Clean isolated context per invocation
- System prompt: explicit JSON output schema with example
- Performs web_search → validate → extract → Ollama call → validate output
- Agent-level retry: if all sources fail validation, makes a second Ollama call
  with prompt "rephrase this query to find the same information differently: {query}"
  then retries web_search with the rephrased query once
- Escalates failure report to engine if rephrased retry also fails

### `validators.py` — All deterministic validators

**SourceValidator:**
- HTTP HEAD then GET (follows up to 3 redirects, blocks deeper chains)
- Status code: 200 only (redirects to non-200 = rejected)
- Content-Type: `text/html`, `text/plain`, `application/pdf` only
- Content-Length header check: reject if exceeds type-specific limits
- Paywall pattern regex: "subscribe to read", "members only", "sign in to continue", etc.
- Minimum content threshold: extracted text < 200 words = discard
- Domain circuit breaker: 3 failures from same domain → skip domain for session
- `Last-Modified` / `Date` header extraction → recency metadata

**OutputValidator:**
- JSON schema enforcement on all agent outputs
- Required fields presence check
- Citation index continuity (no gaps in [1],[2],[3]...)
- Relevance score range check (0.0–1.0)
- Discards and logs invalid outputs — never passes to orchestrator

**CitationAuditor:**
- Parses all `[[N]](url)` patterns in report text via regex
- Cross-checks every N has corresponding source entry
- Cross-checks every source URL is in the validated-URL set
- Checks no source entry is unused (orphaned source)
- Enforces minimum source count (`RESEARCH_MIN_SOURCES`)
- Checks every source has: title, url, domain, date

**SecurityValidator:**
- `check_ssrf(url)`: resolves hostname to IP, blocks RFC 1918 ranges
  (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16), localhost, link-local
- `sanitize_filename(title)`: alphanumeric + hyphens only, max 80 chars
- `scan_prompt_injection(text)`: regex + keyword patterns for known injection
  phrases ("ignore previous instructions", "disregard", "new instructions", etc.)
- `enforce_content_type(response)`: hard reject anything not text/html, text/plain, application/pdf
- `enforce_size_limit(response, type)`: hard cap before decompression
  (HTML: 2MB, PDF: 10MB configurable via `RESEARCH_MAX_PDF_SIZE_MB`)

### `processors.py` — ContentProcessor, PDFProcessor

**ContentProcessor:**
- HTML boilerplate stripping: removes nav, header, footer, cookie banners, ads
  (CSS selector + heuristic block detection)
- Table extraction: HTML tables preserved as structured text before stripping
- Date extraction: regex scan for ISO dates, common date formats → recency signal
- Named entity extraction: regex patterns for people (Title Lastname), orgs
  (Inc/Corp/Ltd suffix), places (known country/city list), dates
- TF-IDF pre-scoring: score extracted content against original research topic
  using term frequency — gives agents an objective relevance hint
- Duplicate content detection: SHA-256 hash of normalized text — skip if seen
- Language detection: character frequency analysis — discard non-English

**PDFProcessor:**
- Triggered when content-type is `application/pdf` or URL ends in `.pdf`
- Downloads to in-memory bytes buffer (never touches disk as binary)
- ClamAV scan via `clamd` socket before any parsing
  - infected → discard, log, flag source as rejected
  - ClamAV unavailable → skip PDF with warning log
- `pdfplumber` text extraction (text layer only — no rendering, no JS)
- `has_text_layer()` check: if no extractable text → discard with reason
  "scanned image PDF — OCR not supported (see GitHub issue #X)"
- Strip all metadata, annotations, embedded objects from extracted text
- Temp bytes deleted immediately after extraction

### `knowledge.py` — KnowledgeBase, FindingStore

**KnowledgeBase:**
- `ingest(outputs: list[ResearcherOutput])`: processes all agent outputs for a round
- SHA-256 deduplication of finding text (normalized, lowercased)
- Claim pattern detection: regex for "X is Y", "X does Y", "X has Y" structures
  → flags pairs where same subject has contradicting predicates
- Source agreement counting: findings supported by N+ sources get confidence boost
- `coverage_score()`: % of original topic's key terms present in KB
- `novelty_rate()`: % of this round's findings not already in KB
- `compact_summary()`: produces the KB summary the orchestrator reads
  — findings grouped by shared key entities/terms (extracted by ContentProcessor's
    NER pass — deterministic grouping, no model required)
  — includes contradiction flags, confidence signals, coverage gaps
  — total summary kept under 4000 tokens to fit orchestrator context cleanly

**FindingStore:**
- Holds findings as `Finding` dataclass:
  `{text, sources: list[int], relevance: float, contradicts_topic: bool, round_found: int}`
- Findings sorted by relevance score descending
- Low-relevance findings (below threshold) pruned when KB grows large
  — pruning rule: remove lowest-relevance findings first, never remove
  findings that are the sole support for a claim

### `queries.py` — QueryManager

- `expand(topic)`: generates initial query list deterministically:
  - base query (topic as-is)
  - year variants: `"topic 2024"`, `"topic 2025"`
  - question variants: `"what is topic"`, `"how does topic work"`, `"topic explained"`
  - source-type variants: `"topic site:reddit.com"`, `"topic site:arxiv.org"`,
    `"topic site:reuters.com"`
  - SearxNG category routing: classify query as news/academic/general → set categories param
- `add_from_gaps(gaps: list[str])`: adds orchestrator-identified gap queries
- `deduplicate(query)`: Levenshtein distance check against all previous queries —
  similarity > 0.85 = duplicate, rejected
- `is_cached(query)` / `cache_result(query, results)`: in-memory cache for session
- `mark_used(query)`: prevents repeating queries across rounds
- Domain diversity enforcement: if >3 queries in a round would hit the same domain
  (detected via SearxNG result domain analysis from cache), excess queries for that
  domain are dropped from the round and replaced with the next unused queries from
  the gap list that target different domains

### `report.py` — ReportBuilder

- Orchestrator Ollama call: synthesize findings into report with `[[N]](url)` citations
- `CitationAuditor.audit()` run after synthesis
- Reviewer Ollama call (skeptic system prompt): independent critique pass
- `ReportValidator` (inner class in `report.py` — not part of `validators.py`):
  validates structure, sections present, char budget, readability score
- `build_embed(report)`: assembles Discord embed
  - Title: original query (max 256 chars)
  - Color: `#4F8EF7`
  - Description: executive summary (max 400 chars)
  - Fields: Findings, Alternative Views (if contradictions found), Sources
  - Footer: `N sources · N rounds · Xm Ys`
- `split_overflow(embed)`: if total > 6000 chars → Part 1 (title + summary + findings),
  Part 2+ (contradictions + sources), footer only on last embed

### `memory.py` — MemoryGuard

- `psutil.virtual_memory()` polled every 30 seconds in background task
- States: `NORMAL` / `PRESSURE` (< `RESEARCH_MEMORY_THRESHOLD_PCT` available) /
  `CRITICAL` (< `RESEARCH_MEMORY_CRITICAL_PCT` available)
- On `PRESSURE` with active research:
  - Sets `memory_priority = True` flag
  - Proxy request handler checks flag → returns polite deferral for chat requests
  - Sends Ollama `keep_alive: 0` for any loaded model not in the research model set
- On `CRITICAL` (any state):
  - All non-essential Ollama calls blocked
  - Active research pauses between rounds until pressure drops
- On research complete: `memory_priority` cleared, chat resumes

### `storage.py` — ResearchStore

- Save path: `/app/data/research/YYYY-MM-DD-{sanitized-title}.json`
- `SecurityValidator.sanitize_filename()` applied to all paths
- Saved payload:
  ```json
  {
    "title": "original query",
    "timestamp": "2026-04-10T14:32:00Z",
    "rounds_completed": 3,
    "source_count": 12,
    "report_text": "...",
    "sources": [...],
    "knowledge_base_snapshot": {...},
    "metadata": { "agent_model": "...", "orchestrator_model": "...", "duration_secs": 154 }
  }
  ```
- `index.json`: `{ "title slug": "filepath", ... }` — updated on every save
- Memory KV store: `research:{title}` → filepath for model recall via `session_search`
- `load_by_title(title)`: fuzzy title match (Levenshtein) against index, returns stored report

---

## 6. Deep Dive Mode

Reuses `ResearchEngine` with `mode="deepdive"`. Differences:

- **Seed sources**: loaded from a saved report's validated source list, or user-supplied URLs, or both
- **QueryManager behavior**: narrow targeted queries only — no broad expansion
  Queries are derived from the seed sources: title keywords, entity names, date ranges
- **ContentProcessor**: higher `max_chars` per source (6000 vs 3000) — more depth per page
- **Link following**: for each seed source, extract outbound links to same/similar domains,
  validate and add as additional sources (one hop only — no recursive crawling)
- **KnowledgeBase**: pre-seeded with findings from the original research report if available
  — deep dive builds on top of prior knowledge, doesn't repeat it
- **Stopping logic**: same orchestrator satisfaction + verification round + novelty threshold

**Trigger forms:**
- `/deepdive "bitcoin ETF"` — loads sources from saved report titled "bitcoin ETF"
- `/deepdive url:https://...` — user-supplied seed sources
- `/deepdive "bitcoin ETF" url:https://...` — both combined

---

## 7. Configuration

All settings configurable via `hermes.env` (server-wide defaults) and slash command arguments (per-request override).

```
# Model selection
RESEARCH_AGENT_MODEL=gemma4:e4b
RESEARCH_ORCHESTRATOR_MODEL=gemma4:26b

# Loop control
RESEARCH_MAX_ROUNDS=5
RESEARCH_TIMEOUT_MINS=15
RESEARCH_NOVELTY_THRESHOLD=0.20

# Concurrency
RESEARCH_MAX_CONCURRENT=2

# Memory management
RESEARCH_MEMORY_THRESHOLD_PCT=20
RESEARCH_MEMORY_CRITICAL_PCT=10

# Source validation
RESEARCH_MAX_PDF_SIZE_MB=10
RESEARCH_MIN_SOURCES=3
RESEARCH_MAX_REDIRECT_DEPTH=3

# Storage
RESEARCH_DATA_PATH=/app/data/research
```

---

## 8. Discord Progress Messages

Progress posts to the channel where research was triggered. Each message includes the job topic so concurrent jobs are distinguishable.

```
[Research: 'bitcoin ETF'] Starting — generating research queries...
[Research: 'bitcoin ETF'] Round 1 — researching 6 subtopics...
[Research: 'bitcoin ETF'] Round 1 complete — 8 findings, 82% coverage. Identifying gaps...
[Research: 'bitcoin ETF'] Round 2 — researching 4 gap topics...
[Research: 'bitcoin ETF'] Sufficient findings — running verification round...
[Research: 'bitcoin ETF'] Synthesizing report...
[Research: 'bitcoin ETF'] Running self-review...
[Research: 'bitcoin ETF'] Complete — 12 sources · 3 rounds · 2m 41s
[embed posted]
```

---

## 9. Security Summary

| Threat | Mitigation | Layer |
|---|---|---|
| SSRF | IP resolution + RFC 1918 block | SecurityValidator |
| Prompt injection | Regex pattern scan on all extracted text | SecurityValidator |
| Path traversal | Filename sanitization (alphanumeric + hyphens) | SecurityValidator |
| PDF malware | ClamAV scan before pdfplumber parsing | PDFProcessor |
| Response bombs | Hard byte limit before decompression | SecurityValidator |
| Malicious content-type | Strict allowlist enforcement | SecurityValidator |
| Redirect abuse | Max 3 hops, non-200 final = rejected | SourceValidator |
| Scanned PDFs (no text) | Detected and discarded gracefully | PDFProcessor |
| Domain flooding | Circuit breaker after 3 failures | SourceValidator |
| Query loops | Levenshtein dedup + used-query tracking | QueryManager |

---

## 10. File Structure

```
vm/proxy/research/
  __init__.py
  engine.py
  validators.py
  processors.py
  knowledge.py
  queries.py
  report.py
  memory.py
  storage.py

vm/proxy/tools.py
  + execute_deep_research(topic, channel, config)
  + execute_deepdive(topic, channel, config, urls)

vm/proxy/config.py
  + all RESEARCH_* env vars

vm/discord-bot/cogs/research.py
  + /research hybrid command
  + /deepdive hybrid command

vm/quadlets/hermes-proxy.container (Dockerfile section)
  + ClamAV install + definitions

docs/superpowers/specs/
  2026-04-10-deep-research-design.md  ← this file
```

---

## 11. Future Enhancements

- **OCR support for scanned PDFs**: add `tesseract` + `pytesseract` to extract text from
  image-based PDFs. Currently these are discarded with a logged reason.
  To be tracked in GitHub issue: "feat: OCR support for scanned PDFs in deep research"
  Tracked in: Gavin-Holliday/hermes-vm#1

---

## 12. Out of Scope

- Voice channel research readouts
- Multi-language source support
- Real-time collaborative research sessions
- Automatic research scheduling / cron triggers
