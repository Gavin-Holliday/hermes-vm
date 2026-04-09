import os
from dataclasses import dataclass
from functools import lru_cache


def _load_system_prompt() -> str:
    # Note: env var is SYSTEM_PROMPT_FILE (a file path), not SYSTEM_PROMPT_OVERRIDE.
    # The infrastructure plan and .env.example must use SYSTEM_PROMPT_FILE.
    path = os.getenv("SYSTEM_PROMPT_FILE", "/app/system_prompt.txt")
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return "You are Hermes, a helpful assistant."


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
            self.max_tool_rounds = int(os.getenv("MAX_TOOL_ROUNDS", "10"))
        if self.tool_timeout_secs is None:
            self.tool_timeout_secs = int(os.getenv("TOOL_TIMEOUT_SECS", "120"))
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


@lru_cache
def get_config() -> Config:
    return Config()
