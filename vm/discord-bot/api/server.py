"""BotApiServer — sole responsibility: lifecycle of the internal HTTP API."""
import aiohttp.web as web

from config import BotConfig
from protocols import IMessageTracker
from api.handlers import make_handlers


class BotApiServer:
    """Wraps aiohttp lifecycle. Depends on injected bot + tracker."""

    def __init__(
        self,
        bot,
        cfg: BotConfig,
        tracker: IMessageTracker,
    ) -> None:
        self._port = cfg.api_port
        self._runner: web.AppRunner | None = None
        handlers = make_handlers(bot, cfg, tracker)
        self._app = _build_app(handlers)

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        await site.start()
        print(f"Bot API listening on :{self._port}")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()


def _build_app(handlers: dict) -> web.Application:
    app = web.Application()
    method_map = {"GET": app.router.add_get, "POST": app.router.add_post}
    for key, handler in handlers.items():
        method, path = key.split(None, 1)
        method_map[method](path.strip(), handler)
    return app
