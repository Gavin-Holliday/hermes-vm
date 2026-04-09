"""API request handlers — depend on bot and tracker via closure, not globals."""
import discord
import aiohttp.web as web

from config import BotConfig
from protocols import IMessageTracker


def make_handlers(
    bot: "discord.ext.commands.Bot",
    cfg: BotConfig,
    tracker: IMessageTracker,
):
    """
    Returns a dict of route → handler built with injected dependencies.
    Handlers are plain async functions — easy to unit-test in isolation.
    """

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def debug_info(request: web.Request) -> web.Response:
        return web.json_response({
            "watching_channel_id": cfg.channel_id,
            "guilds": [
                {
                    "name": g.name,
                    "channels": [
                        {"id": ch.id, "name": ch.name}
                        for ch in g.text_channels
                    ],
                }
                for g in bot.guilds
            ],
        })

    async def send_message(request: web.Request) -> web.Response:
        data = await request.json()
        channel = await _resolve_channel(bot, cfg, data)
        if channel is None:
            return web.json_response({"error": "channel not found"}, status=404)
        msg = await channel.send(str(data.get("content", ""))[:2000])
        tracker.track(msg)
        return web.json_response({"ok": True, "message_id": msg.id})

    async def list_channels(request: web.Request) -> web.Response:
        channels = [
            {"id": ch.id, "name": ch.name, "type": str(ch.type), "guild": g.name}
            for g in bot.guilds
            for ch in g.channels
        ]
        return web.json_response({"channels": channels})

    async def list_members(request: web.Request) -> web.Response:
        members = [
            {
                "id": m.id,
                "name": m.name,
                "display_name": m.display_name,
                "bot": m.bot,
            }
            for g in bot.guilds
            for m in g.members
        ]
        return web.json_response({"members": members})

    async def create_poll(request: web.Request) -> web.Response:
        import datetime
        data = await request.json()
        channel = await _resolve_channel(bot, cfg, data)
        if channel is None:
            return web.json_response({"error": "channel not found"}, status=404)
        question = str(data.get("question", "Poll"))[:300]
        options = data.get("options", [])[:10]
        hours = int(data.get("duration_hours", 24))
        try:
            poll = discord.Poll(
                question=question,
                duration=datetime.timedelta(hours=hours),
            )
            for opt in options:
                poll.add_answer(text=str(opt)[:55])
            msg = await channel.send(poll=poll)
            return web.json_response({"ok": True, "message_id": msg.id})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def add_reaction(request: web.Request) -> web.Response:
        data = await request.json()
        channel = await _resolve_channel(bot, cfg, data)
        if channel is None:
            return web.json_response({"error": "channel not found"}, status=404)
        try:
            msg = await channel.fetch_message(int(data["message_id"]))
            await msg.add_reaction(data.get("emoji", "✅"))
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    return {
        "GET  /health":   health,
        "GET  /debug":    debug_info,
        "POST /send":     send_message,
        "GET  /channels": list_channels,
        "GET  /members":  list_members,
        "POST /poll":     create_poll,
        "POST /react":    add_reaction,
    }


async def _resolve_channel(bot, cfg: BotConfig, data: dict):
    if "channel_id" in data:
        return bot.get_channel(int(data["channel_id"]))
    if "channel_name" in data:
        name = data["channel_name"].lower()
        for guild in bot.guilds:
            for ch in guild.channels:
                if ch.name.lower() == name:
                    return ch
    return bot.get_channel(cfg.channel_id)
