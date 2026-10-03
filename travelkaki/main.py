"""Entry point. Run with:

    uv run uvicorn travelkaki.main:app

This starts the web API and (unless RUN_BOT=false) the Telegram bot.
"""

import logging

from travelkaki.web.app import app

# Basic log format so we can see bot start/stop messages in the console and Docker logs.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

__all__ = ["app"]
