"""/pin: set a place's map pin by replying with a Telegram location.

Some small shops aren't in Nominatim/OSM, so they get no pin. Flow:
/pin -> buttons for unpinned places -> tap one -> we send a ForceReply prompt ->
someone replies with a location (or venue) -> we save lat/lng on the place.
Why a reply: in groups with privacy mode on, bots still receive replies to their own messages.
"""

import logging

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from travelkaki.bot.cards import NO_TRIP
from travelkaki.db import place_queries as pq
from travelkaki.db import queries
from travelkaki.geo import gmaps_link

log = logging.getLogger(__name__)

MAX_BUTTONS = 10  # keep the list short; /pin <name> reaches the rest
GONE = "This place no longer exists."


def _chat_place(s, place_id: int, chat_id: int):
    """The place, only if it belongs to this chat's trip (else None)."""
    place, trip = pq.get_place(s, place_id), queries.get_trip(s, chat_id)
    return place if place and trip and place.trip_id == trip.id else None


async def _ask(bot, chat_id: int, place_id: int, name: str, chat_data: dict) -> None:
    """Send the ForceReply prompt and remember which place it is for."""
    text = f"Reply to this with a Google Maps link or a Telegram location for {name}."
    sent = await bot.send_message(chat_id, text, reply_markup=ForceReply(selective=True))
    chat_data.setdefault("pin_prompts", {})[sent.message_id] = place_id


async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/pin lists unpinned places. /pin <name> picks a place by name part."""
    deps, chat_id = context.bot_data["deps"], update.effective_chat.id
    log.info("pin chat=%s", chat_id)
    message = update.effective_message
    with deps.sessions() as s:
        trip = queries.get_trip(s, chat_id)
        places = pq.trip_places(s, trip.id) if trip else []
        # Detach plain values: the session closes before we send anything.
        rows = [(p.id, p.name, p.lat is None) for p in places]
    if trip is None:
        await message.reply_text(NO_TRIP)
        return
    wanted = " ".join(context.args or []).strip().lower()
    if wanted:
        found = [(i, n) for i, n, _ in rows if wanted in n.lower()]
        if len(found) == 1:  # one match: skip the list
            await _ask(context.bot, chat_id, found[0][0], found[0][1], context.chat_data)
            return
        if not found:
            await message.reply_text(f"No place matching “{wanted}”. Try /places.")
            return
    else:
        found = [(i, n) for i, n, unpinned in rows if unpinned]
        if not found:
            await message.reply_text("Every place already has a pin. 📍")
            return
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(n, callback_data=f"p:{i}")] for i, n in found[:MAX_BUTTONS]]
    )
    await message.reply_text("Which place needs a pin?", reply_markup=markup)


async def pick(query, chat_id: int, place_id: int, context, deps) -> None:
    """A 'p:<id>' button tap: ask for the location."""
    with deps.sessions() as s:
        place = _chat_place(s, place_id, chat_id)
        name = place.name if place else None
    if name is None:
        await query.answer(GONE)
        return
    await query.answer()
    await _ask(context.bot, chat_id, place_id, name, context.chat_data)


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A location/venue message. Only acts when it replies to one of our pin prompts."""
    message, chat_id = update.effective_message, update.effective_chat.id
    replied = message.reply_to_message
    prompts = context.chat_data.get("pin_prompts", {})
    place_id = prompts.get(replied.message_id) if replied else None
    if place_id is None:
        return  # an ordinary location: not ours
    point = message.venue.location if message.venue else message.location
    deps = context.bot_data["deps"]
    with deps.sessions() as s:
        place = _chat_place(s, place_id, chat_id)  # same trip scoping as the buttons
        if place is None:
            return
        name = place.name
        pq.set_pin(s, place_id, point.latitude, point.longitude)
    prompts.pop(replied.message_id, None)  # one reply per prompt
    log.info("pin set chat=%s place=%s", chat_id, place_id)
    await message.reply_text(f"📍 Pinned {name}. Open the map to see it.")


async def on_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A text reply to a pin prompt with a Google Maps link: save its coordinates.

    Runs before on_message (handler group -1). When it handles the message it raises
    ApplicationHandlerStop so the link is not also read as a place to add.
    """
    message, chat_id = update.effective_message, update.effective_chat.id
    replied = message.reply_to_message
    prompts = context.chat_data.get("pin_prompts", {})
    place_id = prompts.get(replied.message_id) if replied else None
    url = gmaps_link.find_url(message.text) if place_id is not None else None
    if url is None:
        return  # not a pin reply with a Maps link: let other handlers have it
    deps = context.bot_data["deps"]
    with deps.sessions() as s:
        place = _chat_place(s, place_id, chat_id)  # same trip scoping as the buttons
        name = place.name if place else None
    if name is None:
        return
    if gmaps_link.is_short(url):
        url = await gmaps_link.resolve(url)  # follow the redirect to the full link
    coords = gmaps_link.parse_coords(url)
    if coords is None:  # keep the prompt in chat_data so they can try again
        await message.reply_text(
            "Couldn't read a location from that link. Try a Telegram location, "
            "or a Google Maps link to the exact place."
        )
        raise ApplicationHandlerStop
    with deps.sessions() as s:
        pq.set_pin(s, place_id, *coords)
    prompts.pop(replied.message_id, None)  # one reply per prompt
    log.info("pin set from link chat=%s place=%s", chat_id, place_id)
    await message.reply_text(f"📍 Pinned {name}. Open the map to see it.")
    raise ApplicationHandlerStop
