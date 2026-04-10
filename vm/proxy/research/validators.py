import ipaddress
import re
import socket
from urllib.parse import urlparse

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior)",
    r"new\s+instructions",
    r"system\s+prompt",
    r"you\s+are\s+now\s+a",
    r"forget\s+(everything|all)",
    r"act\s+as\s+(if\s+you\s+are|a\s+)",
]

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
]

_ALLOWED_TYPES = {"text/html", "text/plain", "application/pdf"}
_HTML_LIMIT = 2 * 1024 * 1024


class SecurityValidator:
    def __init__(self, max_pdf_size_mb: int = 10):
        self._pdf_limit = max_pdf_size_mb * 1024 * 1024

    def check_ssrf(self, url: str) -> bool:
        try:
            hostname = urlparse(url).hostname
            if not hostname:
                return False
            ip = ipaddress.ip_address(socket.gethostbyname(hostname))
            return not any(ip in net for net in _PRIVATE_NETWORKS)
        except Exception:
            return False

    def sanitize_filename(self, title: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        return slug[:80]

    def scan_prompt_injection(self, text: str) -> bool:
        lower = text.lower()
        return any(re.search(p, lower) for p in INJECTION_PATTERNS)

    def enforce_content_type(self, content_type: str) -> bool:
        base = content_type.split(";")[0].strip().lower()
        return base in _ALLOWED_TYPES

    def enforce_size_limit(self, content_bytes: bytes, content_type: str) -> bool:
        base = content_type.split(";")[0].strip().lower()
        limit = self._pdf_limit if base == "application/pdf" else _HTML_LIMIT
        return len(content_bytes) <= limit

    def size_limit_for(self, content_type: str) -> int:
        base = content_type.split(";")[0].strip().lower()
        return self._pdf_limit if base == "application/pdf" else _HTML_LIMIT


from dataclasses import dataclass
import httpx


@dataclass
class ValidationResult:
    valid: bool
    content_type: str = ""
    last_modified: str = ""
    reason: str = ""


class SourceValidator:
    def __init__(self, security: SecurityValidator, max_redirect_depth: int = 3):
        self._security = security
        self._max_redirects = max_redirect_depth
        self._failures: dict[str, int] = {}

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def _is_tripped(self, url: str) -> bool:
        return self._failures.get(self._domain(url), 0) >= 3

    def _record_failure(self, url: str) -> None:
        d = self._domain(url)
        self._failures[d] = self._failures.get(d, 0) + 1

    async def validate_url(self, url: str) -> ValidationResult:
        if self._is_tripped(url):
            return ValidationResult(False, reason=f"circuit breaker: {self._domain(url)}")
        if not self._security.check_ssrf(url):
            return ValidationResult(False, reason="SSRF: private/internal IP")
        try:
            async with httpx.AsyncClient(
                timeout=10.0, follow_redirects=True,
                max_redirects=self._max_redirects,
            ) as client:
                headers = {"User-Agent": "Mozilla/5.0 (compatible; Hermes/1.0)"}
                resp = await client.head(url, headers=headers)
                if resp.status_code != 200:
                    resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    self._record_failure(url)
                    return ValidationResult(False, reason=f"HTTP {resp.status_code}")
                ct = resp.headers.get("content-type", "")
                if not self._security.enforce_content_type(ct):
                    return ValidationResult(False, reason=f"rejected content-type: {ct}")
                cl = int(resp.headers.get("content-length", 0) or 0)
                if cl > 0:
                    limit = self._security.size_limit_for(ct)
                    if cl > limit:
                        self._record_failure(url)
                        return ValidationResult(False, reason=f"too large: {cl} bytes")
                lm = resp.headers.get("last-modified", "")
                return ValidationResult(True, content_type=ct, last_modified=lm)
        except httpx.TooManyRedirects:
            self._record_failure(url)
            return ValidationResult(False, reason="too many redirects")
        except Exception as e:
            self._record_failure(url)
            return ValidationResult(False, reason=str(e))
