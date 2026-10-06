"""Builds the Telegram bot application and registers its handlers.

Building does NOT connect to Telegram. Starting/stopping happens in
`travelkaki/web/app.py`, so the bot and the web API share one process.
"""

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PollHandler,
    filters,
)

from travelkaki.bot.handlers import on_error, start
from travelkaki.bot.links import add_command, on_message
from travelkaki.bot.map import map_command
from travelkaki.bot.pin import on_location, pin_command
from travelkaki.bot.plan import plan_command
from travelkaki.bot.trip import newtrip
from travelkaki.bot.votes import on_callback, places_command
from travelkaki.deps import Deps
from travelkaki.planner.ask import on_poll

# The command menu users see when they type "/". Set from code at startup,
# so we never have to edit it by hand in BotFather.
COMMANDS = [
    BotCommand("start", "What I do and what I store"),
    BotCommand("newtrip", "Start a trip: /newtrip Tokyo 12-15 Dec"),
    BotCommand("add", "Add a link or a place by name"),
    BotCommand("places", "Saved places and votes"),
    BotCommand("plan", "Plan the days: /plan or /plan 10-22"),  # M2
    BotCommand("map", "Open the trip map"),  # M3
    BotCommand("pin", "Set a place's map pin: /pin or /pin <name>"),
]


# New messages only (by default PTB also runs commands again when they're edited).
NEW_ONLY = filters.UpdateType.MESSAGE


def build_application(token: str, deps: Deps | None = None) -> Application:
    """Create the bot app for this token, with all handlers added.

    `deps` (database, HTTP client, LLM, ...) is stored in bot_data so every
    handler can reach it as context.bot_data["deps"].
    """
    # 20 s timeouts (default 5 s): sends timed out in the PR3 demo while the Mac was busy
    # running the local LLM, and a place card was lost.
    app = Application.builder().token(token).read_timeout(20).write_timeout(20).build()
    app.bot_data["deps"] = deps
    # One line per command. NEW_ONLY: editing a command must not run it again (PR3 review).
    app.add_handler(CommandHandler("start", start, filters=NEW_ONLY))
    app.add_handler(CommandHandler("newtrip", newtrip, filters=NEW_ONLY))
    app.add_handler(CommandHandler("add", add_command, filters=NEW_ONLY))
    app.add_handler(CommandHandler("places", places_command, filters=NEW_ONLY))
    app.add_handler(CommandHandler("plan", plan_command, filters=NEW_ONLY))  # M2 planner
    app.add_handler(CommandHandler("map", map_command, filters=NEW_ONLY))  # M3 mini app
    app.add_handler(CommandHandler("pin", pin_command, filters=NEW_ONLY))  # manual map pin
    app.add_handler(CallbackQueryHandler(on_callback))  # vote / wrong place / retry buttons
    # M2: poll counts arrive here, so ask_group can close a poll early.
    app.add_handler(PollHandler(on_poll))
    app.add_error_handler(on_error)  # never silent, even when a handler crashes
    # Every other new message with text or a caption (photos/videos with links too).
    # UpdateType.MESSAGE = new messages only: an edit must not read a link twice.
    app.add_handler(
        MessageHandler(
            filters.UpdateType.MESSAGE & (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            on_message,
        )
    )
    # A location/venue sent as a reply to a /pin prompt (on_location ignores other replies).
    app.add_handler(
        MessageHandler(
            filters.UpdateType.MESSAGE & filters.REPLY & (filters.LOCATION | filters.VENUE),
            on_location,
        )
    )
    return app


async def register_commands(app: Application) -> None:
    """Send the command menu to Telegram. Called once after the bot starts.

    (PTB's post_init hook only runs with run_polling(), which we don't use.)
    """
    await app.bot.set_my_commands(COMMANDS)
