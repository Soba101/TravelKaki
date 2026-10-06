"""/pin safety checks: refuse far-away pins, and confirm when a link names another place."""

import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from travelkaki.db import place_queries as pq
from travelkaki.db import queries
from travelkaki.geo.distance import distance_m

log = logging.getLogger(__name__)

FAR_M = 100_000  # a pin further than this from the trip city is almost surely wrong
GONE = "This place no longer exists."


def trip_info(deps, chat_id: int) -> tuple[str, tuple | None]:
    """(city, (lat, lng) or None) of the chat's trip. Plain values: the session closes."""
    with deps.sessions() as s:
        trip = queries.get_trip(s, chat_id)
        if trip is None:
            return "", None
        has_centre = trip.city_lat is not None and trip.city_lng is not None
        return trip.city, (trip.city_lat, trip.city_lng) if has_centre else None


def far_text(city: str, center: tuple | None, coords: tuple) -> str | None:
    """The refusal message when the pin is far from the trip city, else None."""
    if center is None or distance_m(center, coords) <= FAR_M:
        return None
    return f"That spot is far from {city}. Check the link and try again."


def done_text(name: str, approximate: bool) -> str:
    """The 'Pinned' reply. Approximate pins (postcode centre) say so."""
    if approximate:
        return f"📍 Pinned {name} (approximate, from the postcode). Use 'Wrong place' if it's off."
    return f"📍 Pinned {name}. Open the map to see it."


async def ask_confirm(message, chat_data: dict, place_id: int, pending: dict) -> None:
    """The link names a different place: keep the pin aside and ask. Nothing is saved yet."""
    chat_data.setdefault("pin_pending", {})[place_id] = pending
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes, pin it", callback_data=f"y:{place_id}"),
                InlineKeyboardButton("No", callback_data=f"n:{place_id}"),
            ]
        ]
    )
    text = (
        f"That link looks like <b>{escape(pending['link_name'])}</b>, "
        f"not <b>{escape(pending['name'])}</b>. Pin it anyway?"
    )
    await message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def on_confirm(query, chat_id: int, place_id: int, yes: bool, context) -> None:
    """A 'y:<id>' / 'n:<id>' tap on the question above."""
    pending = context.chat_data.get("pin_pending", {}).pop(place_id, None)
    if pending is None:  # already answered, or the bot restarted
        await query.answer(GONE)
        return
    await query.answer()
    if not yes:  # the original prompt stays usable
        await query.edit_message_text("OK — reply to the prompt with the right link.")
        return
    with context.bot_data["deps"].sessions() as s:
        pq.set_pin(s, place_id, *pending["coords"], maps_link=pending["link"])
    context.chat_data.get("pin_prompts", {}).pop(pending["prompt_id"], None)  # one reply per prompt
    log.info("pin set after confirm chat=%s place=%s", chat_id, place_id)
    await query.edit_message_text(done_text(pending["name"], pending["approximate"]))
