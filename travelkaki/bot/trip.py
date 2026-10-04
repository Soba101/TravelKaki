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
# Tried in this order. Groups: day, month (and a second day, month for ranges).
_TWO_MONTHS = re.compile(
    rf"(\d{{1,2}})\s+([a-z]{{3,}}){_DASH}(\d{{1,2}})\s+([a-z]{{3,}})", re.I
)  # 12 Dec - 3 Jan
_ONE_MONTH = re.compile(rf"(\d{{1,2}}){_DASH}(\d{{1,2}})\s+([a-z]{{3,}})", re.I)  # 12-15 Dec
_SINGLE = re.compile(r"(\d{1,2})\s+([a-z]{3,})", re.I)  # 5 Mar


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


def _dates(d1: str, m1: str, d2: str, m2: str, today: date) -> tuple[date, date]:
    """Build start/end dates. No year given, so pick the next upcoming one."""
    try:
        start = date(today.year, _month(m1), int(d1))
        if start < today:
            start = start.replace(year=today.year + 1)
        end = date(start.year, _month(m2), int(d2))
        if end < start and end.month < start.month:  # e.g. 28 Dec - 3 Jan: crosses new year
            end = end.replace(year=start.year + 1)
    except ValueError as e:  # e.g. 31 Feb
        if isinstance(e, TripParseError):
            raise
        raise TripParseError(f"That date doesn't exist.\n{USAGE}") from None
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
        start, end = _dates(m[1], m[2], m[3], m[4], today)
    elif m := _ONE_MONTH.search(main):
        start, end = _dates(m[1], m[3], m[2], m[3], today)
    elif m := _SINGLE.search(main):
        start, end = _dates(m[1], m[2], m[1], m[2], today)
    city = (main[: m.start()] if m else main).strip()
    if not city:
        raise TripParseError(USAGE)
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
    with deps.sessions() as s:
        queries.upsert_trip(s, chat_id, trip.city, trip.start, trip.end, trip.hotel)
    await update.effective_message.reply_text(
        f"✈️ Trip set: {_describe(trip)}\nNow drop TikTok or Instagram links here!"
    )
