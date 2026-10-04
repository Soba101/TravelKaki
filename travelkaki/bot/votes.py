"""Button taps (votes, and from PR4 'Wrong place' + 'Retry') and /places (issue #14).

Anyone in the group can vote. Tapping the same button again removes your vote.
"""

import logging

from sqlalchemy import select
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from travelkaki.bot.cards import NO_TRIP, card_keyboard, parse_callback, places_text
from travelkaki.bot.results import send
from travelkaki.db import place_queries as pq
from travelkaki.db import queries
from travelkaki.db.models import Vote

log = logging.getLogger(__name__)

GONE = "This place no longer exists."
VALUES = {"m": "must", "y": "maybe", "s": "skip"}
TOASTS = {"must": "Voted Must-go", "maybe": "Voted Maybe", "skip": "Voted Skip"}


def _chat_place(s, place_id: int, chat_id: int):
    """The place, only if it belongs to this chat's trip (else None)."""
    place, trip = pq.get_place(s, place_id), queries.get_trip(s, chat_id)
    return place if place and trip and place.trip_id == trip.id else None


async def _vote(query, chat_id: int, place_id: int, code: str, deps) -> None:
    user_id = query.from_user.id
    with deps.sessions() as s:
        place = _chat_place(s, place_id, chat_id)
        if place is None:
            await query.answer(GONE)
            return
        counts = pq.vote(s, place_id, user_id, VALUES[code])
        mine = s.scalar(
            select(Vote.value).where(Vote.place_id == place_id, Vote.tg_user_id == user_id)
        )
    await query.answer(TOASTS[mine] if mine else "Vote removed")
    try:
        await query.edit_message_reply_markup(card_keyboard(place, counts))
    except TelegramError as e:  # e.g. "message is not modified" after fast double taps
        log.debug("vote edit skipped: %s", e)


async def _wrong_place(query, chat_id: int, place_id: int, deps) -> None:
    """'👎 Wrong place': forget the pin, keep the place and its votes (#12)."""
    with deps.sessions() as s:
        if _chat_place(s, place_id, chat_id) is None:
            await query.answer(GONE)
            return
        place = pq.clear_pin(s, place_id)
        counts = pq.vote_counts(s, place_id)
    await query.answer("Pin removed")
    try:
        await query.edit_message_text(
            query.message.text_html + "\n❌ Pin removed",
            parse_mode="HTML",
            reply_markup=card_keyboard(place, counts),  # pin gone -> only the vote row
        )
    except TelegramError as e:
        log.debug("wrong-place edit skipped: %s", e)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any inline button tap."""
    query, deps = update.callback_query, context.bot_data["deps"]
    parsed = parse_callback(query.data)
    if parsed is None:
        await query.answer(GONE)
        return
    kind, item_id, arg = parsed
    chat_id = query.message.chat.id
    if kind == "v":
        await _vote(query, chat_id, item_id, arg, deps)
    elif kind == "w":
        await _wrong_place(query, chat_id, item_id, deps)
    else:
        await query.answer()  # 'r' (retry) arrives in Task 15


async def places_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/places: every saved place with its vote counts."""
    deps, chat_id = context.bot_data["deps"], update.effective_chat.id
    log.info("places chat=%s", chat_id)
    with deps.sessions() as s:
        trip = queries.get_trip(s, chat_id)
        chunks = places_text(pq.places_with_counts(s, trip.id), trip.city) if trip else [NO_TRIP]
    for chunk in chunks:
        await send(context.bot, chat_id, chunk)
