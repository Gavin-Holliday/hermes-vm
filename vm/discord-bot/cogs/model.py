"""ModelCog — sole responsibility: model selection commands."""
from discord import app_commands
from discord.ext import commands

from config import BotConfig
from protocols import IHistory, IModelState


class ModelCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        cfg: BotConfig,
        model_state: IModelState,
        history: IHistory,
    ) -> None:
        self.bot = bot
        self.cfg = cfg
        self.model_state = model_state
        self.history = history

    def _channel_guard(self, ctx: commands.Context) -> bool:
        # Allow DMs (no guild) and the configured main channel
        return ctx.guild is None or ctx.channel.id == self.cfg.channel_id

    @commands.hybrid_command(name="model")
    @app_commands.describe(name="Model name or alias to switch to. Omit to list available models.")
    async def switch_model(self, ctx: commands.Context, name: str = None) -> None:
        """Show or change the active model."""
        if not self._channel_guard(ctx):
            return

        if name is None:
            model_list = "\n".join(
                f"{'→' if m == self.model_state.current else '  '} `{m}`"
                for m in self.model_state.allowed
            )
            alias_list = "\n".join(
                f"  `{k}` → `{v}`"
                for k, v in self.model_state.aliases.items()
            )
            await ctx.send(
                f"**Current model:** `{self.model_state.current}`\n\n"
                f"**Available:**\n{model_list}\n\n"
                f"**Aliases:**\n{alias_list}"
            )
            return

        old = self.model_state.current
        try:
            resolved = self.model_state.switch(name)
        except ValueError:
            await ctx.send(
                f"❌ `{name}` is not recognised. Use `!model` to see options."
            )
            return

        self.history.clear(ctx.channel.id)
        note = f" (alias `{name}`)" if resolved != name else ""
        await ctx.send(f"Switched `{old}` → `{resolved}`. History cleared.{note}")

    @commands.hybrid_command(name="clear")
    async def clear_history(self, ctx: commands.Context) -> None:
        """Reset conversation history for this channel."""
        if not self._channel_guard(ctx):
            return
        self.history.clear(ctx.channel.id)
        await ctx.message.add_reaction("✅")
