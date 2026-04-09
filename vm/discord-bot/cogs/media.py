"""MediaCog — sole responsibility: rich media commands (TTS, polls)."""
import base64
import datetime
import io
import tempfile

import discord
from discord.ext import commands

from config import BotConfig


class MediaCog(commands.Cog):
    def __init__(self, bot: commands.Bot, cfg: BotConfig) -> None:
        self.bot = bot
        self.cfg = cfg

    # ── Discord built-in TTS ───────────────────────────────────────────────────

    @commands.command(name="tts")
    async def send_tts(self, ctx: commands.Context, *, text: str) -> None:
        """Read text aloud via Discord's built-in TTS."""
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        await ctx.channel.send(text[:2000], tts=True)

    # ── AI voice via Ollama (gemma4:e4b supports audio modalities) ────────────

    @commands.command(name="speak")
    async def speak(self, ctx: commands.Context, *, text: str = None) -> None:
        """
        Synthesize speech via gemma4:e4b and play it in your voice channel.
        Usage: !speak [text]  — omit text to speak the last bot reply.
        Requires you to be in a voice channel.
        """
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

    @commands.command(name="poll")
    async def create_poll(self, ctx: commands.Context, *, args: str) -> None:
        """
        Create a native Discord poll (24h).
        Usage: !poll question | option 1 | option 2 [| option 3 ...]
        """
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 3:
            await ctx.send(
                "Usage: `!poll question | option 1 | option 2 [| ...]`\n"
                "Minimum 2 options required."
            )
            return
        question, *options = parts
        options = options[:10]
        try:
            poll = discord.Poll(
                question=question[:300],
                duration=datetime.timedelta(hours=24),
            )
            for opt in options:
                poll.add_answer(text=opt[:55])
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
