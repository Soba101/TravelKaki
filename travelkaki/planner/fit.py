"""Order one day's places and fit them to times (helpers for build.py, M2 #18).

Rules (M2 spec, "build_days" steps 4-5):
- Order by nearest neighbour from the hotel. Evening places go last.
- Walk the day from its start. Closed on arrival? Wait if it opens within
  60 min (the first stop may wait longer: the day just starts later).
  Otherwise try it later in the day. Still impossible -> dropped, with a reason.
- A transfer over 60 min, or a day running past its end, also drops the place.
"""

from datetime import date

from travelkaki.geo.distance import distance_m
from travelkaki.planner.hours import is_open, next_open, parse
from travelkaki.planner.rules import is_evening
from travelkaki.planner.travel import estimate
from travelkaki.planner.types import EVENING_END, MAX_SPAN, Day, Dropped, PlanPlace, Stop, Window

MAX_WAIT = 60  # minutes we'll wait for a place to open
MAX_TRANSFER = 60  # minutes; longer trips break the validator's rule


def day_label(d: date) -> str:
    """date(2026, 12, 15) -> 'Tue 15 Dec'."""
    return f"{d:%a} {d.day} {d:%b}"


def order(places: list[PlanPlace], base: tuple[float, float]) -> list[PlanPlace]:
    """Nearest neighbour from the base. Evening places are visited last."""
    out, cur = [], base
    for group in ([p for p in places if not is_evening(p)], [p for p in places if is_evening(p)]):
        left = list(group)
        while left:
            nxt = min(left, key=lambda p: (distance_m(cur, p.point), p.id))
            left.remove(nxt)
            out.append(nxt)
            cur = nxt.point
    return out


def limits(window: Window, places: list[PlanPlace]) -> tuple[int, int, int]:
    """(start, latest end, max busy span) for a day with these places."""
    if window.fixed:
        return window.start, window.latest_end, window.latest_end - window.start
    latest = EVENING_END if any(is_evening(p) for p in places) else window.latest_end
    return window.start, latest, MAX_SPAN


def _open_at(p: PlanPlace, weekday: int, arrive: int, first: bool) -> int | None:
    """When we can start the visit (maybe after waiting), or None if we can't."""
    if parse(p.hours) is None:
        return arrive  # unknown hours: assume open (the validator warns)
    start = next_open(p.hours, weekday, arrive)
    if start is None or (not first and start - arrive > MAX_WAIT):
        return None
    if not is_open(p.hours, weekday, start + p.visit - 1):
        return None  # it closes before we'd finish
    return start


def _closed_reason(p: PlanPlace, d: date, day_no: int) -> str:
    week = parse(p.hours)
    if week is not None and not week[d.weekday()]:
        return f"closed on {day_label(d)}"
    return f"closed whenever it would fit on Day {day_no}"


def fit_day(
    d: date, day_no: int, places: list[PlanPlace], base: tuple[float, float], window: Window
) -> tuple[Day, list[Dropped]]:
    """Give each place a time on day `d`. Returns the Day and what didn't fit."""
    start, latest, span = limits(window, places)
    queue, tried_later, stops, dropped = list(places), set(), [], []
    t, cur, leave = start, base, None  # leave = when we leave the hotel
    while queue:
        p = queue.pop(0)
        travel, mode = estimate(cur, p.point)
        if travel > MAX_TRANSFER:
            dropped.append(Dropped(p.id, p.name, f"over {MAX_TRANSFER} min from the other stops"))
            continue
        arrive = _open_at(p, d.weekday(), t + travel, first=not stops)
        if arrive is None:
            if p.id not in tried_later:  # try it once more at the end of the day
                tried_later.add(p.id)
                queue.append(p)
            else:
                dropped.append(Dropped(p.id, p.name, _closed_reason(p, d, day_no)))
            continue
        end = arrive + p.visit
        back, _ = estimate(p.point, base)
        begin = leave if leave is not None else arrive - travel
        if end + back > latest or end + back - begin > span:
            dropped.append(Dropped(p.id, p.name, f"no time left on Day {day_no}"))
            continue
        leave = begin
        stops.append(Stop(p.id, arrive, end, travel, mode))
        t, cur = end, p.point
    return Day(d, stops), dropped
