"""build_days: turn the trip's places into days (M2 spec, "build_days", issue #18).

Pure code: the same input always gives the same plan. The agent only picks
Priorities (include / exclude / pins); this file does the maths.

1. Pinned places go to their day first.
2. Must-gos (and agent "include"s) are grouped by area: k-means on the pins,
   k = number of days, far-apart seeds, 10 rounds. Over-full days give away
   their farthest place to the nearest day with room.
4-5. Each day is ordered and fitted to times (fit.py).
Repair: a dropped must-go is tried on every other day; the first day where
everything still fits keeps it.
3. Only then do Maybes (most votes first) join the closest day that still has
   time: a Maybe stays only if nothing else on that day gets pushed out.
   So Must-gos always come first. (Review #2)
Places the agent excluded are listed as "left out by the planner". (Review #3)
"""

from travelkaki.geo.distance import distance_m
from travelkaki.planner.fit import fit_day, limits, order
from travelkaki.planner.types import Day, Dropped, Plan, PlanInput, PlanPlace, Priorities

ROUNDS = 10  # k-means rounds
SLACK = 15  # rough travel minutes per stop, for the "is this day full?" estimate


def _centre(places: list[PlanPlace], fallback: tuple[float, float]) -> tuple[float, float]:
    if not places:
        return fallback
    return (sum(p.lat for p in places) / len(places), sum(p.lng for p in places) / len(places))


def _cluster(places: list[PlanPlace], k: int, base) -> list[list[PlanPlace]]:
    """Split places into k area groups. Seeds: the farthest place from the base,
    then each next seed is the place farthest from all chosen seeds."""
    if k == 0:
        return []
    seeds = [max(places, key=lambda p: (distance_m(base, p.point), -p.id))]
    while len(seeds) < k:
        far = max(
            (p for p in places if p not in seeds),
            key=lambda p: (min(distance_m(s.point, p.point) for s in seeds), -p.id),
        )
        seeds.append(far)
    centres = [s.point for s in seeds]
    for _ in range(ROUNDS):
        groups = [[] for _ in range(k)]
        for p in places:
            i = min(range(k), key=lambda i: (distance_m(centres[i], p.point), i))
            groups[i].append(p)
        centres = [_centre(g, c) for g, c in zip(groups, centres, strict=True)]
    return groups


def _load(group: list[PlanPlace]) -> int:
    return sum(p.visit + SLACK for p in group)


def _fits(group: list[PlanPlace], p: PlanPlace, budget: int) -> bool:
    """Rough check: would this day still have time with `p` added?"""
    return _load(group) + p.visit + SLACK <= budget


def _assign(inp: PlanInput, pr: Priorities, budget: int) -> list[list[PlanPlace]]:
    """Pinned places and Must-gos (plus includes) per day. Maybes come later."""
    n = len(inp.dates)
    cands = [p for p in inp.places if p.id not in pr.exclude]
    pins = {pid: day for pid, day in pr.pins.items() if 1 <= day <= n}
    groups: list[list[PlanPlace]] = [[] for _ in range(n)]
    for p in cands:  # 1. pinned places first
        if p.id in pins:
            groups[pins[p.id] - 1].append(p)
    free = [p for p in cands if p.id not in pins]
    musts = [p for p in free if p.tier == "must" or p.id in pr.include]
    for i, g in enumerate(_cluster(musts, min(n, len(musts)), inp.base)):  # 2. by area
        groups[i] += g
    for i, g in enumerate(groups):  # an over-full day gives away its farthest place
        while _load(g) > budget:
            movable = [p for p in g if p.id not in pins]  # pins stay put (review #4)
            if not movable:
                break
            c = _centre(g, inp.base)
            far = max(movable, key=lambda p: (distance_m(c, p.point), p.id))
            room = [j for j in range(n) if j != i and _fits(groups[j], far, budget)]
            if not room:
                break
            j = min(room, key=lambda j: (_near(groups[j], far, inp.base), j))
            g.remove(far)
            groups[j].append(far)
    return groups


def _near(group: list[PlanPlace], p: PlanPlace, base) -> float:
    """How far `p` is from the middle of a day's places (the hotel if empty)."""
    return distance_m(_centre(group, base), p.point)


def _try(inp: PlanInput, days: list[Day], i: int, p: PlanPlace) -> tuple[Day, list[Dropped]]:
    """Refit day i with `p` added."""
    kept = [inp.place(s.place_id) for s in days[i].stops]
    return fit_day(days[i].date, i + 1, order(kept + [p], inp.base), inp.base, inp.window)


def build_days(inp: PlanInput, pr: Priorities | None = None) -> Plan:
    """Make a day-by-day plan. Every candidate ends up in a day or in `dropped`."""
    pr = pr or Priorities()
    budget = limits(inp.window, [])[2]
    groups = _assign(inp, pr, budget)
    fitted = [
        fit_day(d, i + 1, order(g, inp.base), inp.base, inp.window)
        for i, (d, g) in enumerate(zip(inp.dates, groups, strict=True))
    ]
    days = [day for day, _ in fitted]
    dropped: list[Dropped] = [x for _, lost in fitted for x in lost]
    for lost in list(dropped):  # repair: try a dropped must-go on another day
        if lost.place_id in pr.pins:
            continue  # the agent pinned it to that day: don't move it (review #4)
        p = inp.place(lost.place_id)
        for i in range(len(days)):
            new_day, new_lost = _try(inp, days, i, p)
            if not new_lost:  # everything on that day still fits, plus this one
                days[i] = new_day
                dropped.remove(lost)
                break
    placed = {pid for g in groups for pid in (p.id for p in g)}
    maybes = [p for p in inp.places if p.id not in placed and p.id not in pr.exclude]
    for p in sorted(maybes, key=lambda p: (-p.maybe, -p.must, p.id)):  # 3. Maybes last
        tries = sorted(range(len(days)), key=lambda i: (_near(_on(inp, days[i]), p, inp.base), i))
        reason = f"no time left on Day {tries[0] + 1}" if tries else "no days to plan"
        for i in tries:
            new_day, new_lost = _try(inp, days, i, p)
            if not new_lost:
                days[i] = new_day
                break
        else:
            dropped.append(Dropped(p.id, p.name, reason))
    for p in inp.places:  # the agent's exclusions are listed, so the plan stays honest
        if p.id in pr.exclude:
            dropped.append(Dropped(p.id, p.name, "left out by the planner"))
    return Plan(days, dropped)


def _on(inp: PlanInput, day: Day) -> list[PlanPlace]:
    return [inp.place(s.place_id) for s in day.stops]
