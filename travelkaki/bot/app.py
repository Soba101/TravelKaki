"""Builds the Telegram bot application and registers its handlers.

Building does NOT connect to Telegram. Starting/stopping happens in
`travelkaki/web/app.py`, so the bot and the web API share one process.
"""

from telegram import BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from travelkaki.bot.handlers import start
from travelkaki.bot.links import add_command, on_message
from travelkaki.bot.trip import newtrip
from travelkaki.deps import Deps

# The command menu users see when they type "/". Set from code at startup,
# so we never have to edit it by hand in BotFather.
COMMANDS = [
    BotCommand("start", "What I do and what I store"),
    BotCommand("newtrip", "Start a trip: /newtrip Tokyo 12-15 Dec"),
    BotCommand("add", "Add a link or a place by name"),
    BotCommand("places", "Saved places and votes"),
]


def build_application(token: str, deps: Deps | None = None) -> Application:
    """Create the bot app for this token, with all handlers added.

    `deps` (database, HTTP client, LLM, ...) is stored in bot_data so every
    handler can reach it as context.bot_data["deps"].
    """
    app = Application.builder().token(token).build()
    app.bot_data["deps"] = deps
    # One line per command.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newtrip", newtrip))
    app.add_handler(CommandHandler("add", add_command))
    # Every other new message with text or a caption (photos/videos with links too).
    # UpdateType.MESSAGE = new messages only: an edit must not read a link twice.
    app.add_handler(
        MessageHandler(
            filters.UpdateType.MESSAGE & (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            on_message,
        )
    )
    return app


async def register_commands(app: Application) -> None:
    """Send the command menu to Telegram. Called once after the bot starts.

    (PTB's post_init hook only runs with run_polling(), which we don't use.)
    """
    await app.bot.set_my_commands(COMMANDS)
