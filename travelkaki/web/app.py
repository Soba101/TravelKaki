"""FastAPI app. It only has /health so far, but it also owns the bot's lifecycle.

Why here? uvicorn runs this app. FastAPI's "lifespan" runs code on startup
and shutdown. We start the Telegram bot (polling) there, so one process
runs both the bot and the API, and Ctrl+C / `docker stop` stops both cleanly.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from travelkaki.bot.app import build_application, register_commands
from travelkaki.config import get_settings
from travelkaki.deps import build_deps, close_deps

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Start the bot before serving requests; stop it on shutdown."""
    settings = get_settings()  # fails fast with a clear error if the token is missing

    # Database + HTTP client, shared by the bot and (later) the API. (M1)
    deps = build_deps(settings)

    if not settings.run_bot:
        log.info("RUN_BOT=false: starting web API only, no Telegram bot.")
        try:
            yield
        finally:
            await close_deps(deps)
        return

    bot = build_application(settings.telegram_bot_token, deps)
    # These 3 steps are the manual version of bot.run_polling(),
    # which we can't use because uvicorn already owns the event loop.
    await bot.initialize()
    await bot.start()
    await bot.updater.start_polling()  # polling: we ask Telegram for updates, no open ports
    log.info("Telegram bot started (polling).")
    await register_commands(bot)  # the "/" command menu
    try:
        yield  # the app serves requests while we're paused here
    finally:
        # Shut down in reverse order.
        await bot.updater.stop()
        await bot.stop()
        await bot.shutdown()
        await close_deps(deps)
        log.info("Telegram bot stopped.")


app = FastAPI(title="TravelKaki", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, bool]:
    """Simple liveness check, used by the Docker healthcheck."""
    return {"ok": True}
