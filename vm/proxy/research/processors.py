import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_BLOCK_TAGS = {"nav", "header", "footer", "script", "style", "aside", "noscript"}

_DATE_PATTERNS = [
    re.compile(r'\b(\d{4}-\d{2}-\d{2})\b'),
    re.compile(r'\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})\b'),
    re.compile(r'\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b'),
]

_ORG_SUFFIX = re.compile(r'\b[A-Z][A-Za-z]+(?: Inc\.?| Corp\.?| Ltd\.?| LLC\.?| Co\.?)\b')
_TITLE_CASE = re.compile(r'\b([A-Z][a-z]+ [A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b')


class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in _BLOCK_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in _BLOCK_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._text.append(data)

    def get_text(self) -> str:
        return re.sub(r'\s+', ' ', ''.join(self._text)).strip()


@dataclass
class ProcessedContent:
    text: str
    entities: list
    dates: list
    tfidf_score: float
    content_hash: str


class ContentProcessor:
    def __init__(self):
        self._seen: set = set()

    def process(self, html: str, topic: str, url: str) -> "ProcessedContent | None":
        text = self.strip_boilerplate(html)
        h = self.sha256_hash(text)
        if h in self._seen:
            return None
        self._seen.add(h)
        return ProcessedContent(
            text=text,
            entities=self.extract_entities(text),
            dates=self.extract_dates(text),
            tfidf_score=self.tfidf_score(text, topic),
            content_hash=h,
        )

    def strip_boilerplate(self, html: str) -> str:
        s = _Stripper()
        s.feed(html)
        return s.get_text()

    def extract_dates(self, text: str) -> list:
        found = []
        for p in _DATE_PATTERNS:
            found.extend(p.findall(text))
        return list(dict.fromkeys(found))

    def extract_entities(self, text: str) -> list:
        entities = set()
        entities.update(_ORG_SUFFIX.findall(text))
        entities.update(_TITLE_CASE.findall(text))
        return list(entities)

    def tfidf_score(self, text: str, topic: str) -> float:
        topic_terms = [t.lower() for t in topic.split() if len(t) > 2]
        if not topic_terms:
            return 0.0
        words = re.findall(r'\b\w+\b', text.lower())
        if not words:
            return 0.0
        tf = sum(words.count(t) for t in topic_terms) / len(words)
        return min(tf * 100, 1.0)

    def detect_language(self, text: str) -> str:
        if not text:
            return "other"
        ascii_count = sum(1 for c in text if c.isascii() and c.isprintable())
        return "en" if ascii_count / len(text) > 0.60 else "other"

    def sha256_hash(self, text: str) -> str:
        return hashlib.sha256(text.lower().encode()).hexdigest()


import logging
from io import BytesIO

log = logging.getLogger("hermes.research.pdf")


class PDFProcessor:
    def __init__(self, security, clamav_socket: str = "/var/run/clamav/clamd.ctl"):
        self._security = security
        self._clamav_socket = clamav_socket

    def process(self, content_bytes: bytes) -> "str | None":
        if not self._security.enforce_size_limit(content_bytes, "application/pdf"):
            log.warning("PDF rejected: exceeds size limit (%d bytes)", len(content_bytes))
            return None
        if not self._scan_clamav(content_bytes):
            log.warning("PDF rejected: ClamAV detected threat")
            return None
        try:
            import pdfplumber
            with pdfplumber.open(BytesIO(content_bytes)) as pdf:
                parts = [p.extract_text() or "" for p in pdf.pages]
            text = "\n".join(parts).strip()
            if not text:
                log.info("PDF rejected: no text layer (scanned image PDF — see issue #1)")
                return None
            return text
        except Exception as e:
            log.warning("PDF extraction failed: %s", e)
            return None

    def _scan_clamav(self, content_bytes: bytes) -> bool:
        try:
            import clamd
            cd = clamd.ClamdUnixSocket(self._clamav_socket)
            result = cd.instream(BytesIO(content_bytes))
            status = list(result.values())[0][0]
            return status != "FOUND"
        except Exception as e:
            log.warning("ClamAV unavailable (%s) — skipping scan", e)
            return True
