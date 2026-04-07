import re
from dataclasses import dataclass


@dataclass
class FilterResult:
    blocked: bool
    refusal: str | None = None


_JAILBREAK_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"forget\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"you\s+are\s+now\s+(?:a|an)\s+\w+",
    r"act\s+as\s+(?:a|an)\s+(?:unrestricted|uncensored|jailbroken)",
    r"\bdan\s+mode\b",
    r"\bdeveloper\s+mode\b",
    r"\bjailbreak\b",
    r"\bprompt\s+injection\b",
]

_ARCHITECTURE_PATTERNS = [
    r"what\s+(\w+\s+)*(os|operating\s+system|machine|server|host|hardware)",
    r"(tell|show|reveal|expose|leak)\s+(me\s+)?(about\s+)?(your\s+)?"
    r"(host|server|machine|vm|docker|container|architecture|infrastructure|setup|config)",
    r"what\s+(\w+\s+)*(port|ip|address|subnet|network|interface)",
    r"(host|server|machine|vm|container)\s+(ip|address|port|name|hostname)",
    r"are\s+you\s+(running\s+)?(in\s+a?\s+)?(vm|container|docker|virtual\s+machine)",
    r"what\s+version\s+of\s+(linux|ubuntu|fedora|debian|macos)",
]

_JAILBREAK_REFUSAL = "I'm not able to process that request."
_ARCH_REFUSAL = "I'm not able to share information about the infrastructure I run on."


def check_jailbreak(prompt: str) -> FilterResult:
    text = prompt.lower()
    for pattern in _JAILBREAK_PATTERNS:
        if re.search(pattern, text):
            return FilterResult(blocked=True, refusal=_JAILBREAK_REFUSAL)
    return FilterResult(blocked=False)


def check_architecture(prompt: str) -> FilterResult:
    text = prompt.lower()
    for pattern in _ARCHITECTURE_PATTERNS:
        if re.search(pattern, text):
            return FilterResult(blocked=True, refusal=_ARCH_REFUSAL)
    return FilterResult(blocked=False)
