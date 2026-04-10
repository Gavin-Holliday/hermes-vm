"""ModerationCog — sole responsibility: message moderation commands."""
import discord
from discord import app_commands
from discord.ext import commands

from config import BotConfig
from protocols import IMessageTracker


class ModerationCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        cfg: BotConfig,
        tracker: IMessageTracker,
    ) -> None:
        self.bot = bot
        self.cfg = cfg
        self.tracker = tracker

    @commands.hybrid_command(name="pin")
    async def pin_message(self, ctx: commands.Context) -> None:
        """Pin the last bot reply, or the message you're replying to."""
        if ctx.message.reference:
            target = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        else:
            target = self.tracker.last(ctx.channel.id)
        if not target:
            await ctx.send("No message to pin.")
            return
        try:
            await target.pin()
            await ctx.message.add_reaction("✅")
        except discord.Forbidden:
            await ctx.send("Missing Manage Messages permission.")
        except discord.HTTPException as e:
            await ctx.send(f"Pin failed: {e}")

    @commands.hybrid_command(name="unpin")
    @app_commands.describe(message_id="ID of the message to unpin. Omit to unpin the most recent pin.")
    async def unpin_message(self, ctx: commands.Context, message_id: int = None) -> None:
        """Unpin by message ID, or the most recent pin."""
        try:
            if message_id:
                target = await ctx.channel.fetch_message(message_id)
            else:
                pins = await ctx.channel.pins()
                if not pins:
                    await ctx.send("No pinned messages.")
                    return
                target = pins[0]
            await target.unpin()
            await ctx.message.add_reaction("✅")
        except discord.Forbidden:
            await ctx.send("Missing Manage Messages permission.")
        except Exception as e:
            await ctx.send(f"Unpin failed: {e}")

    @commands.hybrid_command(name="delete")
    @app_commands.describe(n="Number of recent bot messages to delete (default: 1).")
    async def delete_messages(self, ctx: commands.Context, n: int = 1) -> None:
        """Delete the last N bot messages (default: 1)."""
        removed = self.tracker.pop_recent(ctx.channel.id, n)
        for msg in removed:
            try:
                await msg.delete()
            except discord.NotFound:
                pass
        await ctx.message.add_reaction("✅")
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
