"""ServerCog — sole responsibility: server management commands."""
import datetime

import discord
from discord import app_commands
from discord.ext import commands

from config import BotConfig
from protocols import IHistory, IMessageTracker, IModelState
from services.event import EventService


class ServerCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        cfg: BotConfig,
        model_state: IModelState,
        history: IHistory,
        tracker: IMessageTracker,
    ) -> None:
        self.bot = bot
        self.cfg = cfg
        self.model_state = model_state
        self.history = history
        self.tracker = tracker

    @commands.hybrid_command(name="status")
    async def show_status(self, ctx: commands.Context) -> None:
        """Show bot status: model, history size, server info, latency."""
        hist_len = len(self.history.get(ctx.channel.id))
        guild = ctx.guild
        await ctx.send(
            f"**Model:** `{self.model_state.current}`\n"
            f"**History:** {hist_len} messages\n"
            f"**Server:** {len(guild.channels)} channels, "
            f"{guild.member_count} members\n"
            f"**Latency:** {round(self.bot.latency * 1000)}ms"
        )

    @commands.hybrid_command(name="nick")
    @app_commands.describe(name="New nickname for the bot. Omit to reset to default.")
    async def change_nick(self, ctx: commands.Context, *, name: str = None) -> None:
        """Set the bot's nickname. Omit to reset."""
        try:
            await ctx.guild.me.edit(nick=name)
            await ctx.message.add_reaction("✅")
        except discord.Forbidden:
            await ctx.send("Missing Manage Nicknames permission.")

    @commands.hybrid_command(name="thread")
    @app_commands.describe(name="Thread name. Defaults to current time if omitted.")
    async def create_thread(self, ctx: commands.Context, *, name: str = None) -> None:
        """Create a thread from the last bot reply."""
        target = self.tracker.last(ctx.channel.id)
        if not target:
            await ctx.send("No recent bot message to thread from.")
            return
        name = name or f"Thread {datetime.datetime.now().strftime('%H:%M')}"
        try:
            thread = await target.create_thread(name=name[:100])
            await ctx.send(f"Created thread: {thread.mention}")
        except discord.Forbidden:
            await ctx.send("Missing Create Public Threads permission.")
        except Exception as e:
            await ctx.send(f"Thread creation failed: {e}")

    @commands.hybrid_command(name="event")
    @app_commands.describe(args="name | description | YYYY-MM-DD HH:MM")
    async def create_event(self, ctx: commands.Context, *, args: str) -> None:
        """Create a scheduled server event."""
        event_data, error = EventService.parse_and_validate(args)
        if error:
            await ctx.send(error)
            return

        try:
            event = await ctx.guild.create_scheduled_event(
                name=event_data.name,
                description=event_data.description,
                start_time=event_data.start_time,
                end_time=event_data.start_time + datetime.timedelta(hours=1),
                entity_type=discord.EntityType.external,
                location="Discord",
                privacy_level=discord.PrivacyLevel.guild_only,
            )
            ts = int(event.start_time.timestamp())
            await ctx.send(f"Event created: **{event.name}** — starts <t:{ts}:R>")
        except discord.Forbidden:
            await ctx.send("Missing Manage Events permission.")
        except Exception as e:
            await ctx.send(f"Event creation failed: {e}")

    @commands.hybrid_command(name="invite")
    async def create_invite(self, ctx: commands.Context) -> None:
        """Create a 24-hour, 10-use invite link."""
        try:
            invite = await ctx.channel.create_invite(
                max_age=86400, max_uses=10, unique=True
            )
            await ctx.send(f"Invite (24h / 10 uses): {invite.url}")
        except discord.Forbidden:
            await ctx.send("Missing Create Invite permission.")
