import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config import BotConfig


class ResearchCog(commands.Cog):
    def __init__(self, bot: commands.Bot, cfg: BotConfig):
        self._bot = bot
        self._cfg = cfg

    @commands.hybrid_command(name="research", description="Start deep multi-round research on a topic")
    @app_commands.describe(
        topic="Topic or question to research",
        researcher_model="Agent model override (default: gemma4:e4b)",
        orchestrator_model="Orchestrator model override (default: gemma4:26b)",
        max_rounds="Max research rounds override",
        timeout_mins="Timeout in minutes override",
        verbosity="Progress detail: normal (default), verbose (per-query detail), silent (report only)",
    )
    async def research(self, ctx: commands.Context, *, topic: str,
                       researcher_model: str = None,
                       orchestrator_model: str = None,
                       max_rounds: int = None,
                       timeout_mins: int = None,
                       verbosity: str = "normal"):
        if verbosity not in ("normal", "verbose", "silent"):
            await ctx.send("verbosity must be `normal`, `verbose`, or `silent`")
            return
        payload = {"topic": topic, "channel": str(ctx.channel.id), "verbosity": verbosity}
        if researcher_model:
            payload["researcher_model"] = researcher_model
        if orchestrator_model:
            payload["orchestrator_model"] = orchestrator_model
        if max_rounds:
            payload["max_rounds"] = max_rounds
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self._cfg.proxy_url}/research", json=payload) as resp:
                    data = await resp.json()
            await ctx.send(data.get("message", "Research started."))
        except Exception as exc:
            await ctx.send(f"Failed to start research: {exc}")

    @commands.hybrid_command(name="deepdive", description="Deep dive into a topic or specific URLs")
    @app_commands.describe(
        topic="Topic from saved research or focus description",
        url="Optional seed URL to dive into",
        researcher_model="Agent model override",
        orchestrator_model="Orchestrator model override",
    )
    async def deepdive(self, ctx: commands.Context, *, topic: str,
                       url: str = None,
                       researcher_model: str = None,
                       orchestrator_model: str = None):
        payload = {"topic": topic, "channel": str(ctx.channel.id)}
        if url:
            payload["urls"] = [url]
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self._cfg.proxy_url}/deepdive", json=payload) as resp:
                    data = await resp.json()
            await ctx.send(data.get("message", "Deep dive started."))
        except Exception as exc:
            await ctx.send(f"Failed to start deep dive: {exc}")
