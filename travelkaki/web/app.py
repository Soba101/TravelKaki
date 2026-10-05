"""FastAPI app. It only has /health so far, but it also owns the bot's lifecycle.

Why here? uvicorn runs this app. FastAPI's "lifespan" runs code on startup
and shutdown. We start the Telegram bot (polling) there, so one process
runs both the bot and the API, and Ctrl+C / `docker stop` stops both cleanly.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from telegram.error import TelegramError

from travelkaki.bot.app import build_application, register_commands
from travelkaki.bot.results import announce_interrupted
from travelkaki.config import get_settings
from travelkaki.deps import build_deps, close_deps
from travelkaki.planner.ask import release_all
from travelkaki.web.api import STATIC, router
from travelkaki.web.members import MemberCheck

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the bot before serving requests; stop it on shutdown."""
    settings = get_settings()  # fails fast with a clear error if the token is missing

    # Database + HTTP client, shared by the bot and (later) the API. (M1)
    deps = build_deps(settings)

    # What the mini app API needs (M3, #23). Routes read these from request.app.state.
    app.state.deps = deps
    app.state.token = settings.telegram_bot_token  # to check initData signatures
    # No bot = nobody can be checked as a group member, so the API says no to all.
    app.state.members = _NoMembers()

    try:
        if not settings.run_bot:
            log.info("RUN_BOT=false: starting web API only, no Telegram bot.")
            yield
            return

        bot = build_application(settings.telegram_bot_token, deps)
        app.state.members = MemberCheck(bot.bot)  # real getChatMember checks (M3)
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


class _NoMembers:
    """Member check used when RUN_BOT=false: refuses everyone (M3)."""

    async def ok(self, chat_id: int, user_id: int) -> bool:
        return False


app = FastAPI(title="TravelKaki", lifespan=lifespan)
app.include_router(router)  # mini app: /app page + /api/trip/{id} (M3)
app.mount("/static", StaticFiles(directory=STATIC), name="static")  # map.js (M3)


@app.get("/health")
async def health() -> dict[str, bool]:
    """Simple liveness check, used by the Docker healthcheck."""
    return {"ok": True}
