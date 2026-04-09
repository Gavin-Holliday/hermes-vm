"""ChatCog — sole responsibility: handle incoming messages and stream responses."""
import discord
from discord.ext import commands

from client import stream_response
from config import BotConfig
from protocols import IHistory, IMessageTracker, IModelState

EDIT_EVERY_CHARS = 80


def _split(text: str, max_len: int = 1990) -> list[str]:
    if not text:
        return ["(no response)"]
    return [text[i: i + max_len] for i in range(0, len(text), max_len)]


class ChatCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        cfg: BotConfig,
        history: IHistory,
        model_state: IModelState,
        tracker: IMessageTracker,
    ) -> None:
        self.bot = bot
        self.cfg = cfg
        self.history = history
        self.model_state = model_state
        self.tracker = tracker

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message) -> None:
        if msg.author.bot or msg.channel.id != self.cfg.channel_id:
            return
        if msg.content.startswith("!"):
            return

        await msg.channel.trigger_typing()
        self.history.add(msg.channel.id, "user", msg.content)

        reply = await msg.channel.send("…")
        self.tracker.track(reply)

        full_response = ""
        last_edit_len = 0

        try:
            async for chunk in stream_response(
                self.cfg.proxy_url,
                self.model_state.current,
                self.history.get(msg.channel.id),
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

        self.history.add(msg.channel.id, "assistant", full_response)

        parts = _split(full_response)
        await reply.edit(content=parts[0])
        for part in parts[1:]:
            extra = await msg.channel.send(part)
            self.tracker.track(extra)

        await msg.add_reaction("✅")
