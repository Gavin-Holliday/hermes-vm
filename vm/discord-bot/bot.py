"""
Entry point — wires config, state, cogs, and API server together.
on_message lives here (not in a Cog) to ensure reliable dispatch.
Commands live in Cogs.
"""
import asyncio
import logging
import sys

import discord
from discord.ext import commands
from dotenv import load_dotenv

from client import stream_response
from config import BotConfig
from history import ChannelHistory
from state import MessageTracker, ModelState
from api.server import BotApiServer
from cogs.media import MediaCog
from cogs.model import ModelCog
from cogs.moderation import ModerationCog
from cogs.research import ResearchCog
from cogs.server import ServerCog

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("hermes.bot")

EDIT_EVERY_CHARS = 80


def _build_intents(cfg: BotConfig) -> discord.Intents:
    intents = discord.Intents.default()
    intents.message_content = True        # privileged — enable in Dev Portal
    intents.reactions = True
    intents.voice_states = True
    intents.guild_scheduled_events = True
    if cfg.enable_members_intent:
        intents.members = True            # privileged — enable in Dev Portal
        intents.presences = True          # privileged — enable in Dev Portal
    return intents


def _split(text: str, max_len: int = 1990) -> list[str]:
    if not text:
        return ["(no response)"]
    return [text[i: i + max_len] for i in range(0, len(text), max_len)]


async def main() -> None:
    cfg = BotConfig.from_env()

    history = ChannelHistory()
    model_state = ModelState(cfg.default_model, cfg.allowed_models, cfg.model_aliases)
    tracker = MessageTracker()

    bot = commands.Bot(command_prefix="!", intents=_build_intents(cfg))

    await bot.add_cog(ModelCog(bot, cfg, model_state, history))
    await bot.add_cog(ModerationCog(bot, cfg, tracker))
    await bot.add_cog(ServerCog(bot, cfg, model_state, history, tracker))
    await bot.add_cog(MediaCog(bot, cfg))
    await bot.add_cog(ResearchCog(bot, cfg))

    @bot.event
    async def on_ready() -> None:
        log.info("Hermes connected as %s (id=%s)", bot.user, bot.user.id)
        for guild in bot.guilds:
            log.info("  Guild: %s — %d channels", guild.name, len(guild.channels))
        log.info("Watching channel_id=%d", cfg.channel_id)
        await bot.tree.sync()
        log.info("Slash commands synced")

    async def _seed_dm_context(dm_key: int) -> None:
        """Fetch last 10 main channel messages and seed DM history as context."""
        main_channel = bot.get_channel(cfg.channel_id)
        if main_channel is None:
            return
        try:
            lines = []
            async for m in main_channel.history(limit=10):
                if m.content:
                    lines.append(f"{m.author.display_name}: {m.content[:300]}")
            if not lines:
                return
            lines.reverse()  # oldest first
            context = "[Recent main channel context — last messages before this DM]\n" + "\n".join(lines)
            history.add(dm_key, "user", context)
            history.add(dm_key, "assistant", "Got it — I have that channel context and I'm ready to chat privately.")
            log.info("Seeded DM context for dm_key=%d (%d messages)", dm_key, len(lines))
        except Exception as exc:
            log.warning("Failed to seed DM context: %s", exc)

    async def _handle_dm(msg: discord.Message) -> None:
        """Handle a private DM conversation, seeding main channel context on first message."""
        log.info("DM from %s (id=%d): %r", msg.author, msg.author.id, msg.content[:80])

        # Let command Cogs handle ! prefixed messages in DMs
        await bot.process_commands(msg)
        if msg.content.startswith("!"):
            return

        # Use channel.id as the history key (consistent with guild handler and !clear)
        dm_key = msg.channel.id

        # Seed context from main channel on first message in this DM session
        if not history.get(dm_key):
            await _seed_dm_context(dm_key)

        history.add(dm_key, "user", msg.content)

        reply = await msg.channel.send("…")
        tracker.track(reply)
        full_response = ""
        last_edit_len = 0

        try:
            async with msg.channel.typing():
                async for chunk in stream_response(
                    cfg.proxy_url,
                    model_state.current,
                    history.get(dm_key),
                ):
                    full_response += chunk
                    if len(full_response) - last_edit_len >= EDIT_EVERY_CHARS:
                        display = full_response[:1990] + (
                            "…" if len(full_response) > 1990 else ""
                        )
                        await reply.edit(content=display or "…")
                        last_edit_len = len(full_response)
        except Exception as exc:
            await reply.edit(content=f"Error: {exc}")
            return

        if not full_response:
            await reply.edit(content="(no response)")
            return

        history.add(dm_key, "assistant", full_response)

        parts = _split(full_response)
        await reply.edit(content=parts[0])
        for part in parts[1:]:
            await msg.channel.send(part)

    @bot.event
    async def on_message(msg: discord.Message) -> None:
        log.info(
            "on_message: author=%s bot=%s guild=%s channel=%s content=%r",
            msg.author,
            msg.author.bot,
            msg.guild,
            msg.channel.id if hasattr(msg.channel, "id") else "DM",
            msg.content[:80] if msg.content else "",
        )
        if msg.author.bot:
            return

        # Handle private DMs as their own sessions
        if msg.guild is None:
            await _handle_dm(msg)
            return

        # Accept messages in the main channel OR in threads that belong to it
        parent_id = getattr(msg.channel, "parent_id", None)
        in_main = msg.channel.id == cfg.channel_id
        in_thread = parent_id == cfg.channel_id
        if not in_main and not in_thread:
            log.info(
                "Ignoring message: channel %d (parent %s) != expected %d",
                msg.channel.id,
                parent_id,
                cfg.channel_id,
            )
            return

        # Let command Cogs handle ! prefixed messages
        await bot.process_commands(msg)
        if msg.content.startswith("!"):
            return

        # If the user replied to a specific message, include it as context
        user_content = msg.content
        if msg.reference and msg.reference.message_id:
            try:
                ref = await msg.channel.fetch_message(msg.reference.message_id)
                user_content = (
                    f"[Replying to {ref.author.display_name}: {ref.content[:500]}]\n"
                    f"{msg.content}"
                )
            except Exception:
                pass

        history.add(msg.channel.id, "user", user_content)

        reply = await msg.channel.send("…")
        tracker.track(reply)

        full_response = ""
        last_edit_len = 0

        try:
            async with msg.channel.typing():
                async for chunk in stream_response(
                    cfg.proxy_url,
                    model_state.current,
                    history.get(msg.channel.id),
                ):
                    full_response += chunk
                    if len(full_response) - last_edit_len >= EDIT_EVERY_CHARS:
                        display = full_response[:1990] + (
                            "…" if len(full_response) > 1990 else ""
                        )
                        await reply.edit(content=display or "…")
                        last_edit_len = len(full_response)
        except Exception as exc:
            await reply.edit(content=f"Error: {exc}")
            return

        if not full_response:
            await reply.edit(content="(no response)")
            return

        history.add(msg.channel.id, "assistant", full_response)

        parts = _split(full_response)
        await reply.edit(content=parts[0])
        for part in parts[1:]:
            extra = await msg.channel.send(part)
            tracker.track(extra)

        await msg.add_reaction("✅")

    api_server = BotApiServer(bot, cfg, tracker)
    await api_server.start()

    async with bot:
        await bot.start(cfg.token)


if __name__ == "__main__":
    asyncio.run(main())
