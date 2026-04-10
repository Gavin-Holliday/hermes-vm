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
