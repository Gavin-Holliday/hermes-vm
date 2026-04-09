"""
Entry point — wires config, state, cogs, and API server together.
No business logic lives here.
"""
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import BotConfig
from history import ChannelHistory
from state import MessageTracker, ModelState
from api.server import BotApiServer
from cogs.chat import ChatCog
from cogs.media import MediaCog
from cogs.model import ModelCog
from cogs.moderation import ModerationCog
from cogs.server import ServerCog

load_dotenv()


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


async def main() -> None:
    cfg = BotConfig.from_env()

    history = ChannelHistory()
    model_state = ModelState(cfg.default_model, cfg.allowed_models, cfg.model_aliases)
    tracker = MessageTracker()

    bot = commands.Bot(command_prefix="!", intents=_build_intents(cfg))

    await bot.add_cog(ChatCog(bot, cfg, history, model_state, tracker))
    await bot.add_cog(ModelCog(bot, cfg, model_state, history))
    await bot.add_cog(ModerationCog(bot, cfg, tracker))
    await bot.add_cog(ServerCog(bot, cfg, model_state, history, tracker))
    await bot.add_cog(MediaCog(bot, cfg))

    @bot.event
    async def on_ready() -> None:
        print(f"Hermes connected as {bot.user} (id={bot.user.id})")
        for guild in bot.guilds:
            print(f"  Guild: {guild.name} — {len(guild.channels)} channels")

    api_server = BotApiServer(bot, cfg, tracker)
    await api_server.start()

    async with bot:
        await bot.start(cfg.token)


if __name__ == "__main__":
    asyncio.run(main())
