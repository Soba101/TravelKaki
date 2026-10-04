"""The /plan message text and Google Maps route links (M2 spec, issue #22).

One compact message (split by day only if it's over Telegram's 4096 chars):
header, a block per day, then trade-offs, places not planned and warnings.
HTML parse mode: every name goes through html.escape.
"""

from html import escape
from urllib.parse import urlencode

from travelkaki.planner.fit import day_label, hhmm
from travelkaki.planner.hours import parse

MAX_CHARS = 4096  # Telegram's limit per message
MAX_WAYPOINTS = 9  # Google Maps directions links allow 9 stops in between
ICONS = {"walk": "🚶", "transit": "🚇", "express": "🚆"}
MAX_LISTED = 10  # "Not planned" names shown; the rest are counted (PR2 review #4)
EXPRESS_NOTE = "🚆 = express train, express bus or taxi. Check routes in Google Maps."


def duration(minutes: int) -> str:
    """45 -> '45 min', 60 -> '1 h', 90 -> '1 h 30'."""
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h} h" + (f" {m}" if m else "")


def _pt(point) -> str:
    return f"{point[0]},{point[1]}"


def route_links(base, points: list) -> list[str]:
    """Directions links for hotel -> stops -> hotel, at most 9 waypoints each.

    A long day is cut into legs that overlap by one point, so they join up.
    """
    if not points:
        return []
    route = [base, *points, base]
    links, i = [], 0
    while i < len(route) - 1:
        leg = route[i : i + MAX_WAYPOINTS + 2]  # origin + 9 waypoints + destination
        params = {"api": 1, "origin": _pt(leg[0]), "destination": _pt(leg[-1])}
        if len(leg) > 2:
            params["waypoints"] = "|".join(_pt(p) for p in leg[1:-1])
        links.append("https://www.google.com/maps/dir/?" + urlencode(params, safe=",|"))
        i += len(leg) - 1
    return links


def _day_block(n: int, day, inp) -> str:
    lines = [f"<b>Day {n} · {day_label(day.date)}</b>"]
    if not day.stops:
        return "\n".join(lines + ["Free day"])
    for s in day.stops:
        p = inp.place(s.place_id)
        name = escape(p.name if p else f"Place {s.place_id}")
        trip = f"{ICONS.get(s.mode, '')} {duration(s.travel)} → " if s.travel else ""
        lines.append(f"{hhmm(s.start)} {trip}{name} · {duration(s.end - s.start)}")
    points = [inp.place(s.place_id).point for s in day.stops if inp.place(s.place_id)]
    for k, link in enumerate(route_links(inp.base, points)):
        label = f"🗺 Day {n} route" + (f" {k + 1}" if k else "")
        lines.append(f'<a href="{escape(link)}">{label}</a>')
    return "\n".join(lines)


def _footer(inp, result) -> str:
    lines = []
    if result.tradeoffs:
        lines.append(f"Trade-offs: {escape(result.tradeoffs)}")
    dropped = inp.dropped + result.plan.dropped
    if dropped:
        shown = ", ".join(f"{escape(d.name)} ({d.reason})" for d in dropped[:MAX_LISTED])
        more = len(dropped) - MAX_LISTED
        lines.append("Not planned: " + shown + (f" … and {more} more" if more > 0 else ""))
    planned = [inp.place(s.place_id) for d in result.plan.days for s in d.stops]
    unknown = sum(1 for p in planned if p and parse(p.hours) is None)
    if unknown:
        lines.append(f"⚠️ Hours unknown for {unknown} place{'s' if unknown > 1 else ''}.")
    if not inp.base_is_hotel:
        lines.append("⚠️ No hotel pin: days start from the city centre.")
    if any(s.mode == "express" for d in result.plan.days for s in d.stops):
        lines.append(EXPRESS_NOTE)
    if not result.used_ai:
        lines.append("Planned without AI (the model was unavailable).")
    return "\n".join(lines)


def format_plan(inp, result, version: int) -> list[str]:
    """The plan as one or more HTML messages, each at most 4096 chars."""
    header = f"🗓 <b>{escape(inp.city)} plan</b> · v{version} · {len(inp.dates)} days"
    blocks = [header] + [_day_block(n, d, inp) for n, d in enumerate(result.plan.days, 1)]
    footer = _footer(inp, result)
    if footer:
        blocks.append(footer)
    parts, current = [], ""
    for block in blocks:
        block = block[:MAX_CHARS]  # one giant block (can't really happen) is cut
        if current and len(current) + 2 + len(block) > MAX_CHARS:
            parts.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    return parts + [current]
