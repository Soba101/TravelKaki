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


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


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
        if end <= start:
            end += 1440  # closes after midnight
        out.append((start, end))
    return out


def parse(raw: str | None) -> dict[int, list[tuple[int, int]]] | None:
    """Opening intervals per weekday, or None when we can't read the string."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    if raw == "24/7":
        return {d: [(0, 1440)] for d in range(7)}
    week: dict[int, list[tuple[int, int]]] = {d: [] for d in range(7)}  # unlisted = closed
    for rule in raw.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        match = _RULE.match(rule)
        if match is None:
            return None  # a form we don't support -> unknown
        times = _intervals(match.group(2))
        for d in _days(match.group(1)):
            week[d] = times  # later rules override earlier ones
    return week


def is_open(raw: str | None, weekday: int, minute: int) -> bool | None:
    """Open at this minute? None = unknown. Also checks last night's late hours."""
    week = parse(raw)
    if week is None:
        return None
    if any(s <= minute < e for s, e in week[weekday]):
        return True
    yesterday = week[(weekday - 1) % 7]
    return any(s <= minute + 1440 < e for s, e in yesterday)


def next_open(raw: str | None, weekday: int, minute: int) -> int | None:
    """The first minute at or after `minute` when it's open that day, or None."""
    week = parse(raw)
    if week is None:
        return None
    if is_open(raw, weekday, minute):
        return minute
    later = [s for s, _ in week[weekday] if s >= minute]
    return min(later) if later else None
