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
DEFAULT_MODEL = os.environ.get("MODEL", "hermes3")
ALLOWED_MODELS = [m.strip() for m in os.environ.get("ALLOWED_MODELS", DEFAULT_MODEL).split(",")]

# Short aliases → full model names. Add entries here as needed.
MODEL_ALIASES: dict[str, str] = {
    "heretic":  "igorls/gemma-4-E4B-it-heretic-GGUF:latest",
    "hermes":   "hermes3",
    "gemma26":  "gemma4:26b",
    "gemma4b":  "gemma4:e4b",
    "qwen9":    "qwen3.5:9b",
    "qwen1":    "qwen3.5:0.8b",
    "gpt20":    "gpt-oss:20b",
    "coder":    "qwen3-coder:30b",
}

# Edit the in-progress reply at most every EDIT_INTERVAL characters of new content.
# This prevents Discord API rate limits (5 edits / 5 seconds per message).
EDIT_EVERY_CHARS = 80

intents = discord.Intents.default()
intents.message_content = True  # required for reading message text (privileged intent)

bot = commands.Bot(command_prefix="!", intents=intents)
history = ChannelHistory()

# Active model — can be changed per-session with !model
current_model = DEFAULT_MODEL


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


@bot.command(name="model")
async def switch_model(ctx: commands.Context, model_name: str = None) -> None:
    """Show or change the active model. Usage: !model [name]"""
    global current_model
    if ctx.channel.id != CHANNEL_ID:
        return

    if model_name is None:
        model_list = "\n".join(
            f"{'→' if m == current_model else '  '} `{m}`" for m in ALLOWED_MODELS
        )
        alias_list = "\n".join(f"  `{k}` → `{v}`" for k, v in MODEL_ALIASES.items())
        await ctx.send(
            f"**Current model:** `{current_model}`\n\n"
            f"**Available:**\n{model_list}\n\n"
            f"**Aliases:**\n{alias_list}"
        )
        return

    # Resolve alias to full name if applicable
    resolved = MODEL_ALIASES.get(model_name, model_name)

    if resolved not in ALLOWED_MODELS:
        await ctx.send(
            f"❌ `{model_name}` is not recognised.\n"
            f"Use `!model` to see available models and aliases."
        )
        return

    old = current_model
    current_model = resolved
    history.clear(ctx.channel.id)
    msg = f"Switched from `{old}` → `{current_model}`. History cleared."
    if resolved != model_name:
        msg += f" (alias `{model_name}`)"
    await ctx.send(msg)


@bot.event
async def on_message(msg: discord.Message) -> None:
    # Ignore our own messages and other bots
    if msg.author.bot:
        return
    # Only respond in the configured channel
    if msg.channel.id != CHANNEL_ID:
        return

    # Process !commands first (e.g., !clear, !model)
    await bot.process_commands(msg)
    if msg.content.startswith("!"):
        return

    history.add(msg.channel.id, "user", msg.content)

    # Send a placeholder that we'll edit progressively
    reply = await msg.channel.send("...")

    full_response = ""
    last_edit_len = 0

    try:
        async for chunk in stream_response(PROXY_URL, current_model, history.get(msg.channel.id)):
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
