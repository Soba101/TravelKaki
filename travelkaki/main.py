"""Entry point. Run with:

    uv run uvicorn travelkaki.main:app

This starts the web API and (unless RUN_BOT=false) the Telegram bot.
"""

import logging

from travelkaki.web.app import app

# Basic log format so we can see bot start/stop messages in the console and Docker logs.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Security: httpx logs every request URL at INFO. Telegram URLs contain the bot token
# (https://api.telegram.org/bot<TOKEN>/getUpdates), so it leaked into Docker logs.
# Only show httpx warnings and errors. (Found 2026-10-04, see issue #3.)
logging.getLogger("httpx").setLevel(logging.WARNING)

__all__ = ["app"]
