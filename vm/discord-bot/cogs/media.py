"""MediaCog — sole responsibility: rich media commands (TTS, polls)."""
import base64
import datetime
import io
import tempfile

import discord
from discord import app_commands
from discord.ext import commands

from config import BotConfig
from services.poll import PollService


class MediaCog(commands.Cog):
    def __init__(self, bot: commands.Bot, cfg: BotConfig) -> None:
        self.bot = bot
        self.cfg = cfg

    # ── Discord built-in TTS ───────────────────────────────────────────────────

    @commands.hybrid_command(name="tts")
    @app_commands.describe(text="Text to read aloud via Discord's built-in TTS.")
    async def send_tts(self, ctx: commands.Context, *, text: str) -> None:
        """Read text aloud via Discord's built-in TTS."""
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        await ctx.channel.send(text[:2000], tts=True)

    # ── AI voice via Ollama (gemma4:e4b supports audio modalities) ────────────

    @commands.hybrid_command(name="speak")
    @app_commands.describe(text="Text to speak aloud in voice channel")
    async def speak(self, ctx: commands.Context, *, text: str = None) -> None:
        """Synthesize speech via AI and play it in your voice channel."""
        if ctx.author.voice is None:
            await ctx.send("You need to be in a voice channel.")
            return

        if text is None:
            await ctx.send("Provide text: `!speak hello world`")
            return

        await ctx.message.add_reaction("⏳")

        audio_bytes = await _synthesize_speech(text, self.cfg.ollama_host)
        if audio_bytes is None:
            await ctx.message.remove_reaction("⏳", self.bot.user)
            await ctx.send(
                "Speech synthesis failed. "
                "Make sure `gemma4:e4b` is running and supports audio output."
            )
            return

        vc = ctx.author.voice.channel
        voice_client = await vc.connect()
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name
            source = discord.FFmpegPCMAudio(tmp_path)
            voice_client.play(source)
            while voice_client.is_playing():
                await discord.utils.asyncio.sleep(0.5)
        finally:
            await voice_client.disconnect()
            await ctx.message.remove_reaction("⏳", self.bot.user)
            await ctx.message.add_reaction("✅")

    # ── Polls ──────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="poll")
    @app_commands.describe(args="question | option1 | option2 | ...")
    async def create_poll(self, ctx: commands.Context, *, args: str) -> None:
        """Create a native Discord poll lasting 24 hours."""
        poll_data, error = PollService.parse_and_validate(args)
        if error:
            await ctx.send(error)
            return

        try:
            poll = PollService.create_discord_poll(poll_data)
            await ctx.channel.send(poll=poll)
            try:
                await ctx.message.delete()
            except discord.Forbidden:
                pass
        except Exception as e:
            await ctx.send(f"Poll creation failed: {e}")


async def _synthesize_speech(text: str, ollama_host: str) -> bytes | None:
    """
    Call Ollama with gemma4:e4b audio modality to synthesize speech.
    Returns raw audio bytes (WAV/MP3) or None on failure.

    Ollama audio output API (>= 0.7): POST /api/generate with
    {"model": "gemma4:e4b", "prompt": text, "modality": "audio"}
    Response: {"audio": "<base64>"}
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{ollama_host}/api/generate",
                json={
                    "model": "gemma4:e4b",
                    "prompt": text,
                    "modality": "audio",
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            audio_b64 = data.get("audio")
            if not audio_b64:
                return None
            return base64.b64decode(audio_b64)
    except Exception:
        return None
