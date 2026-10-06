"""Text and buttons the bot sends: the place list per link, /places, error messages.

All messages use Telegram's HTML mode. Every user-supplied string (place
names, notes, addresses, names of people) goes through html.escape, because
captions are untrusted text.
"""

from html import escape
from urllib.parse import quote_plus

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from travelkaki.db.models import Confidence, Place
from travelkaki.db.place_queries import VoteCounts
from travelkaki.geo.nominatim import clean_name

TELEGRAM_LIMIT = 4096  # max characters in one message
PLATFORM_NAMES = {"tiktok": "TikTok", "instagram": "Instagram"}
NO_TRIP = "Start a trip first: /newtrip Tokyo 12-15 Dec"

# Error code -> message. "{bot}" becomes the bot's @username. (Spec: "Errors" table.)
ERRORS = {
    "no_caption": "Couldn't read that post. Add by name: @{bot} add &lt;place&gt;",
    "llm_unavailable": "AI model unreachable. Is Ollama running?",
    "cap_reached": "Daily AI limit reached for this trip. Add by name or try tomorrow.",
    "no_places": "No places found in that post. Add by name: @{bot} add &lt;place&gt;",
    "interrupted": "I restarted while reading a link. Tap Retry to try again.",
    "link_error": "Couldn't open that link. Try again in a minute.",
    "unknown": "Something went wrong reading that link.",
}


def error_text(code: str, bot_username: str) -> str:
    return ERRORS.get(code, ERRORS["unknown"]).format(bot=bot_username)


def maps_url(place: Place, city: str) -> str:
    """Google Maps link for a place. The one helper for bot cards and the mini app.

    The link the user pinned with wins. Otherwise a NAME search, never lat/lng only:
    raw coordinates open Maps at a bare point instead of the shop.
    """
    if place.maps_link:
        return place.maps_link
    query = quote_plus(f"{clean_name(place.name)}, {city}")
    return f"https://www.google.com/maps/search/?api=1&query={query}"


def _unsure(place: Place) -> bool:
    return place.confidence in (Confidence.low, Confidence.far)


def list_text(
    places: list[Place],
    city: str,
    poster: str | None,
    platform: str | None,
    merged: list[str] | tuple = (),
    extra: int = 0,
) -> str:
    """ONE compact message for everything found in a link (#49).

    Was one card per place, which flooded the group chat (M1 demo feedback).
    Each place is a numbered line; ⚠️ marks a pin we're unsure about.
    """
    count = f"{len(places)} place{'s' if len(places) != 1 else ''}"
    if platform:
        who = f"{escape(poster)}'s" if poster else ("an" if platform == "instagram" else "a")
        lines = [f"📍 {count} from {who} {PLATFORM_NAMES.get(platform, platform)}"]
    else:
        lines = [f"📍 Added: {count}"]  # text add ("@bot add ...")
    for i, place in enumerate(places, start=1):
        link = f'<a href="{escape(maps_url(place, city))}">Map</a>'
        line = f"{i}. <b>{escape(place.name)}</b> · {escape(place.category)} · {link}"
        lines.append(line + (" ⚠️" if _unsure(place) else ""))
    if merged or extra:
        lines.append("")
    if merged:
        lines.append("Already saved: " + ", ".join(escape(n) for n in merged))
    if extra:
        lines.append(f"+{extra} more, see /places")
    return "\n".join(lines)


def list_keyboard(places: list[Place], counts: dict[int, VoteCounts]) -> InlineKeyboardMarkup:
    """One button row per place, numbered like the list. Unsure pins get a 👎📍 button."""
    rows = []
    for i, place in enumerate(places, start=1):
        c = counts.get(place.id, VoteCounts())
        row = [
            InlineKeyboardButton(f"{i} ✅{c.must}", callback_data=f"v:{place.id}:m"),
            InlineKeyboardButton(f"🤔{c.maybe}", callback_data=f"v:{place.id}:y"),
            InlineKeyboardButton(f"❌{c.skip}", callback_data=f"v:{place.id}:s"),
        ]
        if _unsure(place):
            row.append(InlineKeyboardButton("👎📍", callback_data=f"w:{place.id}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def retry_keyboard(source_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔁 Retry", callback_data=f"r:{source_id}")]]
    )


def _line(place: Place, c: VoteCounts) -> str:
    return f"• {escape(place.name)} · {escape(place.category)} — ✅{c.must} 🤔{c.maybe} ❌{c.skip}"


def _chunks(lines: list[str]) -> list[str]:
    """Join lines into messages that each fit Telegram's limit."""
    chunks, current = [], ""
    for line in lines:
        if current and len(current) + 1 + len(line) > TELEGRAM_LIMIT:
            chunks.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    return chunks + [current] if current else chunks


def places_text(rows: list[tuple[Place, VoteCounts]], city: str) -> list[str]:
    """/places: most Must votes first, then Maybe. More Skips than Musts -> 'Skipped'."""
    if not rows:
        return ["No places yet. Post a TikTok or IG link!"]
    rows = sorted(rows, key=lambda r: (r[1].must, r[1].maybe), reverse=True)
    keep = [r for r in rows if r[1].skip <= r[1].must]
    skipped = [r for r in rows if r[1].skip > r[1].must]
    lines = [f"<b>📍 Places for {escape(city)}</b> ({len(rows)})"]
    lines += [_line(p, c) for p, c in keep]
    if skipped:
        lines += ["", "<b>Skipped</b>"] + [_line(p, c) for p, c in skipped]
    return _chunks(lines)


def parse_callback(data: str) -> tuple[str, int, str | None] | None:
    """'v:12:m' -> ('v', 12, 'm'); 'w:3' / 'r:4' / 'p:5' -> (kind, id, None). Bad data -> None."""
    parts = (data or "").split(":")
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    kind, item_id = parts[0], int(parts[1])
    if kind == "v" and len(parts) == 3 and parts[2] in ("m", "y", "s"):
        return kind, item_id, parts[2]
    if kind in ("w", "r", "p", "y", "n") and len(parts) == 2:  # p = /pin choice, y/n = pin confirm
        return kind, item_id, None
    return None
