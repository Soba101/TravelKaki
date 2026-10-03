"""Builds the Telegram bot application and registers its handlers.

Building does NOT connect to Telegram. Starting/stopping happens in
`travelkaki/web/app.py`, so the bot and the web API share one process.
"""

from telegram.ext import Application, CommandHandler

from travelkaki.bot.handlers import start


def build_application(token: str) -> Application:
    """Create the bot app for this token, with all command handlers added."""
    app = Application.builder().token(token).build()
    # One line per command. More commands (/newtrip, /plan, ...) come in later milestones.
    app.add_handler(CommandHandler("start", start))
    return app
