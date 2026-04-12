import os
from dataclasses import dataclass
from functools import lru_cache


def _load_system_prompt() -> str:
    # Note: env var is SYSTEM_PROMPT_FILE (a file path), not SYSTEM_PROMPT_OVERRIDE.
    # The infrastructure plan and .env.example must use SYSTEM_PROMPT_FILE.
    path = os.getenv("SYSTEM_PROMPT_FILE", "/app/system_prompt.txt")
    try:
        with open(path) as f:
            text = f.read().strip()
    except FileNotFoundError:
        text = "You are Hermes, a helpful assistant."
    github_owner = os.getenv("GHCR_OWNER", "")
    if github_owner:
        text = text.replace("{{GITHUB_OWNER}}", github_owner)
    else:
        # Strip the line entirely if no owner is configured
        text = "\n".join(
            line for line in text.splitlines()
            if "{{GITHUB_OWNER}}" not in line
        )
    return text


@dataclass
class Config:
    ollama_host: str = None
    allowed_models: list[str] = None
    searxng_url: str = None
    rate_limit_burst: int = None
    rate_limit_per_min: int = None
    max_tool_rounds: int = None
    tool_timeout_secs: int = None
    system_prompt: str = None
    workspace_path: str = None
    data_path: str = None
    vision_model: str = None
    discord_bot_api_url: str = None
    tenor_api_key: str = None
    github_token: str = None
    research_agent_model: str = None
    research_orchestrator_model: str = None
    research_max_rounds: int = None
    research_timeout_mins: int = None
    research_novelty_threshold: float = None
    research_max_concurrent: int = None
    research_memory_threshold_pct: int = None
    research_memory_critical_pct: int = None
    research_max_pdf_size_mb: int = None
    research_min_sources: int = None
    research_max_redirect_depth: int = None
    research_data_path: str = None
    research_ollama_parallel: int = None
    research_report_channel: str = None

    def __post_init__(self):
        if self.ollama_host is None:
            self.ollama_host = os.getenv(
                "OLLAMA_HOST", "http://host.containers.internal:11434"
            )
        if self.allowed_models is None:
            raw = os.getenv("ALLOWED_MODELS", "hermes3")
            self.allowed_models = [m.strip() for m in raw.split(",")]
        if self.searxng_url is None:
            self.searxng_url = os.getenv("SEARXNG_URL", "http://hermes-searxng:8080")
        if self.rate_limit_burst is None:
            self.rate_limit_burst = int(os.getenv("RATE_LIMIT_BURST", "20"))
        if self.rate_limit_per_min is None:
            self.rate_limit_per_min = int(os.getenv("RATE_LIMIT_PER_MIN", "5"))
        if self.max_tool_rounds is None:
            self.max_tool_rounds = int(os.getenv("MAX_TOOL_ROUNDS", "15"))
        if self.tool_timeout_secs is None:
            self.tool_timeout_secs = int(os.getenv("TOOL_TIMEOUT_SECS", "300"))
        if self.system_prompt is None:
            self.system_prompt = _load_system_prompt()
        if self.workspace_path is None:
            self.workspace_path = os.getenv("WORKSPACE_PATH", "/app/workspace")
        if self.data_path is None:
            self.data_path = os.getenv("DATA_PATH", "/app/data")
        if self.vision_model is None:
            self.vision_model = os.getenv("VISION_MODEL", "gemma4:e4b")
        if self.discord_bot_api_url is None:
            self.discord_bot_api_url = os.getenv(
                "DISCORD_BOT_API_URL", "http://hermes-discord:8001"
            )
        if self.tenor_api_key is None:
            self.tenor_api_key = os.getenv("TENOR_API_KEY", "")
        if self.github_token is None:
            self.github_token = os.getenv("GITHUB_TOKEN", "")
        if self.research_agent_model is None:
            self.research_agent_model = os.getenv("RESEARCH_AGENT_MODEL", "gemma4:e4b")
        if self.research_orchestrator_model is None:
            self.research_orchestrator_model = os.getenv("RESEARCH_ORCHESTRATOR_MODEL", "gemma4:e4b")
        if self.research_max_rounds is None:
            self.research_max_rounds = int(os.getenv("RESEARCH_MAX_ROUNDS", "5"))
        if self.research_timeout_mins is None:
            self.research_timeout_mins = int(os.getenv("RESEARCH_TIMEOUT_MINS", "15"))
        if self.research_novelty_threshold is None:
            self.research_novelty_threshold = float(os.getenv("RESEARCH_NOVELTY_THRESHOLD", "0.20"))
        if self.research_max_concurrent is None:
            self.research_max_concurrent = int(os.getenv("RESEARCH_MAX_CONCURRENT", "2"))
        if self.research_memory_threshold_pct is None:
            self.research_memory_threshold_pct = int(os.getenv("RESEARCH_MEMORY_THRESHOLD_PCT", "20"))
        if self.research_memory_critical_pct is None:
            self.research_memory_critical_pct = int(os.getenv("RESEARCH_MEMORY_CRITICAL_PCT", "10"))
        if self.research_max_pdf_size_mb is None:
            self.research_max_pdf_size_mb = int(os.getenv("RESEARCH_MAX_PDF_SIZE_MB", "10"))
        if self.research_min_sources is None:
            self.research_min_sources = int(os.getenv("RESEARCH_MIN_SOURCES", "3"))
        if self.research_max_redirect_depth is None:
            self.research_max_redirect_depth = int(os.getenv("RESEARCH_MAX_REDIRECT_DEPTH", "3"))
        if self.research_data_path is None:
            self.research_data_path = os.getenv("RESEARCH_DATA_PATH", "/app/data/research")
        if self.research_ollama_parallel is None:
            self.research_ollama_parallel = int(os.getenv("RESEARCH_OLLAMA_PARALLEL", "3"))
        if self.research_report_channel is None:
            self.research_report_channel = os.getenv("RESEARCH_REPORT_CHANNEL", "")


@lru_cache
def get_config() -> Config:
    return Config()
