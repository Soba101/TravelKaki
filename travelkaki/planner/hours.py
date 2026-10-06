"""Read OpenStreetMap opening hours, e.g. "Mo-Fr 10:00-22:00; Sa,Su 09:00-23:00".

The full OSM format is huge (holidays, months, sunrise...). We only read the
common forms. Anything else counts as "unknown" (None), which the planner
treats as a warning, never as a failure. (M2 spec, "Opening hours".)

Supported:
- "24/7"
- rules split by ";" -- each rule is "[days] times"
- days: Mo Tu We Th Fr Sa Su, ranges "Mo-Fr", lists "Sa,Su" (no days = every day)
- times: "10:00-22:00", several with commas, or "off" / "closed"
- later rules win for the days they name ("Mo-Su 10:00-20:00; Tu off")

Minutes count from midnight. An end past midnight is > 1440 (18:00-02:00 -> 1080, 1560).
Weekday 0 = Monday, like Python's date.weekday().
"""

import re

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_DAY = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
_DAY_PART = rf"{_DAY}(?:-{_DAY})?"
_TIME = r"\d\d:\d\d-\d\d:\d\d"
# One rule: optional day list, then a time list or off/closed. Nothing else allowed.
_RULE = re.compile(rf"^(?:({_DAY_PART}(?:,{_DAY_PART})*)\s+)?({_TIME}(?:,{_TIME})*|off|closed)$")
# A public (PH) or school (SH) holiday rule, e.g. "PH off". We skip these.
_HOLIDAY = re.compile(r"^(?:PH|SH)\b")


def _minutes(hhmm: str) -> int:
    h, m = (int(x) for x in hhmm.split(":"))
    # Hours 0-23 and minutes 0-59; "24:00" (end of day) is the one allowed exception.
    if m > 59 or h > 24 or (h == 24 and m != 0):
        raise ValueError(f"bad time {hhmm}")
    return h * 60 + m


def _days(text: str | None) -> list[int]:
    """'Mo-We,Fr' -> [0, 1, 2, 4]. None -> every day."""
    if text is None:
        return list(range(7))
    out = []
    for part in text.split(","):
        first, _, last = part.partition("-")
        a, b = DAYS.index(first), DAYS.index(last or first)
        out += list(range(a, b + 1)) if a <= b else list(range(a, 7)) + list(range(b + 1))
    return out


def _intervals(text: str) -> list[tuple[int, int]]:
    """'11:00-14:00,17:00-02:00' -> [(660, 840), (1020, 1560)]. 'off' -> []."""
    if text in ("off", "closed"):
        return []
    out = []
    for span in text.split(","):
        start, end = (_minutes(t) for t in span.split("-"))
        if end == start:
            raise ValueError("start equals end")  # would mean 24 h open; don't guess
        if end < start:
            end += 1440  # closes after midnight
        out.append((start, end))
    return out


def parse(raw: str | None) -> dict[int, list[tuple[int, int]]] | None:
    """Opening intervals per weekday, or None when we can't read the string."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    raw = re.sub(r",\s+", ",", raw)  # real OSM data often writes "Mo, We" -> "Mo,We"
    if raw == "24/7":
        return {d: [(0, 1440)] for d in range(7)}
    week: dict[int, list[tuple[int, int]]] = {d: [] for d in range(7)}  # unlisted = closed
    seen_rule = False
    for rule in raw.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        if _HOLIDAY.match(rule):
            continue  # public/school holiday rules: ignored, the rest still parses
        match = _RULE.match(rule)
        if match is None:
            return None  # a form we don't support -> unknown
        try:
            times = _intervals(match.group(2))
        except ValueError:
            return None  # impossible clock time or start == end -> unknown
        seen_rule = True
        for d in _days(match.group(1)):
            week[d] = times  # later rules override earlier ones
    return week if seen_rule else None  # empty / holiday-only string -> unknown


def _around(week: dict, weekday: int) -> list[tuple[int, int]]:
    """Yesterday's, today's and tomorrow's intervals on today's clock, merged.

    Yesterday's 18:00-02:00 becomes (-360, 120). Tomorrow's 00:00-24:00 becomes
    (1440, 2880). Touching intervals join, so 24/7 is one long open stretch.
    (Review #5: minutes after midnight must see tomorrow's hours too.)
    """
    spans = [(s - 1440, e - 1440) for s, e in week[(weekday - 1) % 7]]
    spans += week[weekday] + [(s + 1440, e + 1440) for s, e in week[(weekday + 1) % 7]]
    merged: list[list[int]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def open_through(raw: str | None, weekday: int, start: int, end: int) -> bool | None:
    """Open for the whole visit from `start` to `end`? None = unknown.

    Checks one unbroken open stretch, so a visit across a lunch break
    (closed 14:00-14:30) is not open. (Review #12.)
    """
    week = parse(raw)
    if week is None:
        return None
    return any(s <= start and end <= e for s, e in _around(week, weekday))


def is_open(raw: str | None, weekday: int, minute: int) -> bool | None:
    """Open at this minute? None = unknown. Sees last night's late hours too."""
    return open_through(raw, weekday, minute, minute + 1)


def next_open(raw: str | None, weekday: int, minute: int) -> int | None:
    """The first minute at or after `minute` when it's open that day, or None."""
    week = parse(raw)
    if week is None:
        return None
    if is_open(raw, weekday, minute):
        return minute
    later = [s for s, _ in week[weekday] if s >= minute]
    return min(later) if later else None
