import asyncio
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from history import ChannelHistory
from client import stream_response

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
PROXY_URL = os.environ.get("PROXY_URL", "http://hermes-proxy:8000")
MODEL = os.environ.get("MODEL", "hermes3")

# Edit the in-progress reply at most every EDIT_INTERVAL characters of new content.
# This prevents Discord API rate limits (5 edits / 5 seconds per message).
EDIT_EVERY_CHARS = 80

intents = discord.Intents.default()
intents.message_content = True  # required for reading message text (privileged intent)

bot = commands.Bot(command_prefix="!", intents=intents)
history = ChannelHistory()


def split_message(text: str, max_len: int = 1990) -> list[str]:
    """Split text into chunks of at most max_len characters."""
    if not text:
        return ["(no response)"]
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]


@bot.event
async def on_ready() -> None:
    print(f"Hermes connected as {bot.user} (id={bot.user.id})")


@bot.command(name="clear")
async def clear_history(ctx: commands.Context) -> None:
    """Reset conversation history for this channel."""
    if ctx.channel.id != CHANNEL_ID:
        return
    history.clear(ctx.channel.id)
    await ctx.send("Conversation history cleared.")


@bot.event
async def on_message(msg: discord.Message) -> None:
    # Ignore our own messages and other bots
    if msg.author.bot:
        return
    # Only respond in the configured channel
    if msg.channel.id != CHANNEL_ID:
        return

    # Process !commands first (e.g., !clear)
    await bot.process_commands(msg)
    if msg.content.startswith("!"):
        return

    history.add(msg.channel.id, "user", msg.content)

    # Send a placeholder that we'll edit progressively
    reply = await msg.channel.send("...")

    full_response = ""
    last_edit_len = 0

    try:
        async for chunk in stream_response(PROXY_URL, MODEL, history.get(msg.channel.id)):
            full_response += chunk
            # Edit every EDIT_EVERY_CHARS new characters to avoid rate limits
            if len(full_response) - last_edit_len >= EDIT_EVERY_CHARS:
                display = full_response[:1990] + ("…" if len(full_response) > 1990 else "")
                await reply.edit(content=display or "…")
                last_edit_len = len(full_response)
    except Exception as exc:
        await reply.edit(content=f"Error: {exc}")
        return

    if not full_response:
        await reply.edit(content="(no response)")
        return

    history.add(msg.channel.id, "assistant", full_response)

    # Final render — split into multiple messages if needed
    parts = split_message(full_response)
    await reply.edit(content=parts[0])
    for part in parts[1:]:
        await msg.channel.send(part)


if __name__ == "__main__":
    bot.run(TOKEN)
