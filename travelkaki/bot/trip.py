"""/newtrip: start (or update) this chat's trip (issue #7).

Examples:
    /newtrip Tokyo 12-15 Dec
    /newtrip Tokyo 12 Dec - 3 Jan hotel Gracery Shinjuku
    /newtrip Kyoto                  (dates can be added later)
"""

import logging
import re
from dataclasses import dataclass
from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from travelkaki.db import queries

log = logging.getLogger(__name__)

USAGE = (
    "Tell me where and when, e.g.\n"
    "/newtrip Tokyo 12-15 Dec\n"
    "/newtrip Tokyo 12-15 Dec hotel Gracery Shinjuku"
)

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_DASH = r"\s*(?:-|–|to)\s*"
_YEAR = r"(?:\s+(\d{4}))?"  # optional year after the last month, e.g. "12-15 Dec 2027"
# Tried in this order. Groups: day, month (a second day + month for ranges), then the year.
_TWO_MONTHS = re.compile(
    rf"(\d{{1,2}})\s+([a-z]{{3,}}){_DASH}(\d{{1,2}})\s+([a-z]{{3,}}){_YEAR}", re.I
)  # 12 Dec - 3 Jan
_ONE_MONTH = re.compile(rf"(\d{{1,2}}){_DASH}(\d{{1,2}})\s+([a-z]{{3,}}){_YEAR}", re.I)  # 12-15 Dec
_SINGLE = re.compile(rf"(\d{{1,2}})\s+([a-z]{{3,}}){_YEAR}", re.I)  # 5 Mar


@dataclass
class NewTrip:
    city: str
    start: date | None
    end: date | None
    hotel: str | None


class TripParseError(ValueError):
    """Bad /newtrip text. The message is shown to the user as-is."""


def _month(word: str) -> int:
    try:
        return _MONTHS.index(word[:3].lower()) + 1
    except ValueError:
        raise TripParseError(f"I couldn't read the month “{word}”.\n{USAGE}") from None


def _build(d1: str, m1: str, d2: str, m2: str, year: int) -> tuple[date, date]:
    """Start/end dates when the trip starts in `year`. A range like 28 Dec - 3 Jan
    crosses New Year, so the end moves to the next year."""
    try:
        start = date(year, _month(m1), int(d1))
        end = date(year, _month(m2), int(d2))
    except TripParseError:
        raise
    except ValueError:  # e.g. 31 Feb
        raise TripParseError(f"That date doesn't exist.\n{USAGE}") from None
    if end < start and end.month < start.month:
        end = end.replace(year=year + 1)
    return start, end


def _dates(d1: str, m1: str, d2: str, m2: str, year: str | None, today: date) -> tuple[date, date]:
    """Build start/end dates. Year rules:
    - A typed year is the year of the last date ("28 Dec - 3 Jan 2027" ends in 2027).
    - No year: this year, unless the trip would already be over, then next year.
      (A trip that started yesterday but ends next week stays in this year.)
    """
    if year:
        start, end = _build(d1, m1, d2, m2, int(year))
        if end.year > int(year):  # the typed year belongs to the end date
            start, end = _build(d1, m1, d2, m2, int(year) - 1)
    else:
        start, end = _build(d1, m1, d2, m2, today.year)
        if end < today:
            start, end = _build(d1, m1, d2, m2, today.year + 1)
    if end < start:
        raise TripParseError("End date is before start date. Example: /newtrip Tokyo 12-15 Dec")
    return start, end


def parse_newtrip(text: str, today: date) -> NewTrip:
    """Turn '/newtrip' arguments into a NewTrip. Raises TripParseError."""
    # Everything after the word "hotel" is the hotel name.
    parts = re.split(r"\bhotel\b", text, maxsplit=1, flags=re.I)
    main = parts[0].strip()
    hotel = parts[1].strip() if len(parts) > 1 else ""
    hotel = hotel or None
    start = end = None
    if m := _TWO_MONTHS.search(main):
        start, end = _dates(m[1], m[2], m[3], m[4], m[5], today)
    elif m := _ONE_MONTH.search(main):
        start, end = _dates(m[1], m[3], m[2], m[3], m[4], today)
    elif m := _SINGLE.search(main):
        start, end = _dates(m[1], m[2], m[1], m[2], m[3], today)
    city = (main[: m.start()] if m else main).strip()
    leftover = main[m.end() :].strip() if m else ""
    # Digits left in the city, or text after the dates, means we misread the dates
    # (e.g. "Tokyo Dec 12-15"). Say so instead of saving a wrong trip. (PR1 review.)
    if not city or leftover or any(ch.isdigit() for ch in city):
        raise TripParseError(f"I couldn't read that.\n{USAGE}")
    return NewTrip(city, start, end, hotel)


def _describe(trip: NewTrip) -> str:
    """Short confirmation text, e.g. 'Tokyo, 12 Dec – 15 Dec 2026'."""
    text = trip.city
    if trip.start:
        text += f", {trip.start:%-d %b} – {trip.end:%-d %b %Y}"
    if trip.hotel:
        text += f"\nHotel: {trip.hotel}"
    return text


async def newtrip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /newtrip <city> [dates] [hotel <name>]."""
    chat_id = update.effective_chat.id
    log.info("newtrip chat=%s", chat_id)  # never log the message text
    try:
        trip = parse_newtrip(" ".join(context.args or []), date.today())
    except TripParseError as e:
        await update.effective_message.reply_text(str(e))
        return

    deps = context.bot_data["deps"]
    # Find the city on the map once; place searches are then kept near it (#12).
    city = await deps.geo.search(trip.city) if deps.geo else None
    lat, lng = (city.lat, city.lng) if city else (None, None)
    with deps.sessions() as s:
        queries.upsert_trip(s, chat_id, trip.city, trip.start, trip.end, trip.hotel, lat, lng)
    await update.effective_message.reply_text(
        f"✈️ Trip set: {_describe(trip)}\nNow drop TikTok or Instagram links here!"
    )


async def on_migrate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The group became a supergroup: its chat id changed, so move the trip.

    Telegram sends two service messages: migrate_to_chat_id (in the old chat) and
    migrate_from_chat_id (in the new one). Either one is enough; repeating is harmless.
    """
    message, chat_id = update.effective_message, update.effective_chat.id
    if message.migrate_to_chat_id:  # seen in the old chat
        old, new = chat_id, message.migrate_to_chat_id
    elif message.migrate_from_chat_id:  # seen in the new chat
        old, new = message.migrate_from_chat_id, chat_id
    else:
        return
    with context.bot_data["deps"].sessions() as s:
        moved = queries.migrate_trip(s, old, new)
    log.info("chat migrated old=%s new=%s trip_moved=%s", old, new, moved)
