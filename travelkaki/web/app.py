"""FastAPI app. It only has /health so far, but it also owns the bot's lifecycle.

Why here? uvicorn runs this app. FastAPI's "lifespan" runs code on startup
and shutdown. We start the Telegram bot (polling) there, so one process
runs both the bot and the API, and Ctrl+C / `docker stop` stops both cleanly.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from telegram.error import TelegramError

from travelkaki.bot.app import build_application, register_commands
from travelkaki.bot.results import announce_interrupted
from travelkaki.config import get_settings
from travelkaki.deps import build_deps, close_deps
from travelkaki.planner.ask import release_all

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Start the bot before serving requests; stop it on shutdown."""
    settings = get_settings()  # fails fast with a clear error if the token is missing

    # Database + HTTP client, shared by the bot and (later) the API. (M1)
    deps = build_deps(settings)

    try:
        if not settings.run_bot:
            log.info("RUN_BOT=false: starting web API only, no Telegram bot.")
            yield
            return

        bot = build_application(settings.telegram_bot_token, deps)
        # These 3 steps are the manual version of bot.run_polling(),
        # which we can't use because uvicorn already owns the event loop.
        await bot.initialize()
        await bot.start()
        await bot.updater.start_polling()  # polling: we ask Telegram for updates, no open ports
        log.info("Telegram bot started (polling).")
        try:
            await register_commands(bot)  # the "/" command menu
        except TelegramError as e:
            # The menu is nice to have. A Telegram hiccup here must not stop the bot
            # from booting (PR1 review). It is set again on the next restart.
            log.warning("Could not set the command menu: %s", e)
        # Links cut off by the last restart: tell those chats and offer Retry (#15).
        await announce_interrupted(bot.bot, deps)
        try:
            yield  # the app serves requests while we're paused here
        finally:
            # Shut down in reverse order. First end any /plan poll waits, so their
            # polls get stopped instead of left open in the chat (M2, PR3 review #4).
            release_all(bot.bot_data.get("polls", {}))
            await bot.updater.stop()
            await bot.stop()
            await bot.shutdown()
            log.info("Telegram bot stopped.")
    finally:
        # Always close the DB/HTTP resources, even if startup failed halfway.
        await close_deps(deps)


app = FastAPI(title="TravelKaki", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, bool]:
    """Simple liveness check, used by the Docker healthcheck."""
    return {"ok": True}
