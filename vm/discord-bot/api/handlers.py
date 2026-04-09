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
            if "message_id" in data:
                msg = await channel.fetch_message(int(data["message_id"]))
            else:
                msg = tracker.last(cfg.channel_id)
            if msg is None:
                return web.json_response({"error": "no message found"}, status=404)
            await msg.add_reaction(data.get("emoji", "✅"))
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def create_thread(request: web.Request) -> web.Response:
        data = await request.json()
        name = str(data.get("name", "Thread"))[:100]
        try:
            if "message_id" in data:
                channel = await _resolve_channel(bot, cfg, data)
                if channel is None:
                    return web.json_response({"error": "channel not found"}, status=404)
                msg = await channel.fetch_message(int(data["message_id"]))
            else:
                msg = tracker.last(cfg.channel_id)
            if msg is None:
                return web.json_response({"error": "no message to thread from"}, status=404)
            thread = await msg.create_thread(name=name)
            return web.json_response({"ok": True, "thread_name": thread.name, "thread_id": thread.id})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def pin_message(request: web.Request) -> web.Response:
        data = await request.json()
        try:
            if "message_id" in data:
                channel = await _resolve_channel(bot, cfg, data)
                if channel is None:
                    return web.json_response({"error": "channel not found"}, status=404)
                msg = await channel.fetch_message(int(data["message_id"]))
            else:
                msg = tracker.last(cfg.channel_id)
            if msg is None:
                return web.json_response({"error": "no message to pin"}, status=404)
            await msg.pin()
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def channel_history(request: web.Request) -> web.Response:
        import datetime
        q = request.rel_url.query
        limit = int(q.get("limit", 25))
        channel = await _resolve_channel(bot, cfg, dict(q))
        if channel is None:
            channel = bot.get_channel(cfg.channel_id)
        if channel is None:
            return web.json_response({"error": "channel not found"}, status=404)
        kwargs: dict = {"limit": min(limit, 100)}
        if q.get("before"):
            kwargs["before"] = datetime.datetime.fromisoformat(q["before"])
        if q.get("after"):
            kwargs["after"] = datetime.datetime.fromisoformat(q["after"])
        try:
            messages = []
            async for msg in channel.history(**kwargs):
                messages.append({
                    "id": str(msg.id),
                    "author": msg.author.display_name,
                    "bot": msg.author.bot,
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat(),
                })
            return web.json_response({"messages": messages})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def fetch_message(request: web.Request) -> web.Response:
        message_id = request.rel_url.query.get("message_id")
        if not message_id:
            return web.json_response({"error": "message_id required"}, status=400)
        channel = await _resolve_channel(bot, cfg, dict(request.rel_url.query))
        if channel is None:
            channel = bot.get_channel(cfg.channel_id)
        if channel is None:
            return web.json_response({"error": "channel not found"}, status=404)
        try:
            msg = await channel.fetch_message(int(message_id))
            return web.json_response({
                "id": str(msg.id),
                "author": msg.author.display_name,
                "bot": msg.author.bot,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat(),
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def delete_messages(request: web.Request) -> web.Response:
        data = await request.json()
        deleted = 0
        try:
            if "message_id" in data:
                channel = await _resolve_channel(bot, cfg, data)
                if channel is None:
                    return web.json_response({"error": "channel not found"}, status=404)
                msg = await channel.fetch_message(int(data["message_id"]))
                await msg.delete()
                deleted = 1
            else:
                count = int(data.get("count", 1))
                msgs = tracker.pop_recent(cfg.channel_id, count)
                for m in msgs:
                    try:
                        await m.delete()
                        deleted += 1
                    except discord.NotFound:
                        pass
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"ok": True, "deleted": deleted})

    return {
        "GET  /health":   health,
        "GET  /debug":    debug_info,
        "POST /send":     send_message,
        "GET  /channels": list_channels,
        "GET  /members":  list_members,
        "POST /poll":     create_poll,
        "POST /react":    add_reaction,
        "POST /thread":    create_thread,
        "POST /pin":       pin_message,
        "POST /delete":    delete_messages,
        "GET  /history":   channel_history,
        "GET  /message":   fetch_message,
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
