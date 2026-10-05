"""/map and the "Open map" button (M3, #26).

Telegram doesn't allow mini app (web_app) buttons in groups. So we send a
normal URL button to the mini app's direct link: t.me/<bot>/<app>?startapp=<trip id>.
Telegram opens the mini app and passes the trip id as `start_param`.
The server still checks the person is in the group (web/members.py).
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from travelkaki.bot.cards import NO_TRIP
from travelkaki.db import queries

log = logging.getLogger(__name__)

NOT_SET_UP = "The map isn't set up yet (MINI_APP_URL is empty). See the README."
BUTTON = "🗺 Open map"


def map_markup(url: str | None, trip_id: int) -> InlineKeyboardMarkup | None:
    """The Open map button, or None when MINI_APP_URL isn't set."""
    if not url:
        return None
    url = url.rstrip("/")  # a trailing slash would break the link (PR #57 review)
    return InlineKeyboardMarkup([[InlineKeyboardButton(BUTTON, url=f"{url}?startapp={trip_id}")]])


async def map_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/map: a button that opens the trip's map."""
    deps, chat_id = context.bot_data["deps"], update.effective_chat.id
    log.info("map chat=%s", chat_id)
    message = update.effective_message
    with deps.sessions() as s:
        trip = queries.get_trip(s, chat_id)
        trip_id = trip.id if trip else None
    if trip_id is None:
        await message.reply_text(NO_TRIP)
        return
    markup = map_markup(deps.mini_app_url, trip_id)
    if markup is None:
        await message.reply_text(NOT_SET_UP)
        return
    await message.reply_text("Saved places and the plan, on a map:", reply_markup=markup)
