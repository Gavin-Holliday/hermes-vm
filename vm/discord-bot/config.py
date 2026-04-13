import os
from dataclasses import dataclass


@dataclass
class BotConfig:
    token: str
    channel_id: int
    proxy_url: str
    default_model: str
    allowed_models: list[str]
    model_aliases: dict[str, str]
    api_port: int
    enable_members_intent: bool
    ollama_host: str
    tts_voice_channel_id: int | None

    @classmethod
    def from_env(cls) -> "BotConfig":
        default_model = os.environ.get("MODEL", "gemma4:e4b")
        raw_vc = os.environ.get("TTS_VOICE_CHANNEL_ID")
        return cls(
            token=os.environ["DISCORD_TOKEN"],
            channel_id=int(os.environ["DISCORD_CHANNEL_ID"]),
            proxy_url=os.environ.get("PROXY_URL", "http://hermes-proxy:8000"),
            default_model=default_model,
            allowed_models=[
                m.strip()
                for m in os.environ.get("ALLOWED_MODELS", default_model).split(",")
            ],
            model_aliases={
                "heretic": "igorls/gemma-4-E4B-it-heretic-GGUF:latest",
                "hermes":  "hermes3",
                "gemma26": "gemma4:26b",
                "gemma4b": "gemma4:e4b",
                "qwen9":   "qwen3.5:9b",
                "qwen1":   "qwen3.5:0.8b",
                "gpt20":   "gpt-oss:20b",
                "coder":   "qwen3-coder:30b",
                "josie":   "goekdenizguelmez/JOSIEFIED-Qwen3:latest",
            },
            api_port=int(os.environ.get("BOT_API_PORT", "8001")),
            enable_members_intent=(
                os.environ.get("ENABLE_MEMBERS_INTENT", "false").lower() == "true"
            ),
            ollama_host=os.environ.get(
                "OLLAMA_HOST", "http://host.containers.internal:11434"
            ),
            tts_voice_channel_id=int(raw_vc) if raw_vc else None,
        )
