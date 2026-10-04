"""validate(plan): check a plan against the itinerary rules (M2 spec, issue #19).

Pure code. Returns a list of Issues. A plan is **valid** when it has no
"error" issues. "warning" issues are shown to the group but don't block.

| code          | level   | rule                                                  |
| missing_must  | error   | a Must-go place is not in the plan                    |
| skip_included | error   | a Skip place is in the plan                           |
| closed        | error   | known hours say it's closed at the planned time       |
| day_too_long  | error   | ends after the day's latest end, or busy > 12 h       |
| long_transfer | error   | a hop over 60 min (a day's first trip: over 3 h)      |
| hours_unknown | warning | no hours for a planned place                          |
| meal_time     | warning | food places on the day, but none at lunch/dinner time |
| no_hotel_pin  | warning | days start from the city centre                       |
"""

from travelkaki.planner.fit import MAX_DAY_TRIP, MAX_TRANSFER, hhmm, limits
from travelkaki.planner.hours import open_through, parse
from travelkaki.planner.rules import is_food
from travelkaki.planner.travel import estimate
from travelkaki.planner.types import Issue, Plan, PlanInput

LUNCH = (660, 870)  # 11:00-14:30
DINNER = (1050, 1290)  # 17:30-21:30


def _overlaps(start: int, end: int, span: tuple[int, int]) -> bool:
    return start < span[1] and end > span[0]


def _check_day(n: int, day, inp: PlanInput) -> list[Issue]:
    """All the per-stop and per-day rules for day number n (1-based)."""
    out = []
    places = [inp.place(s.place_id) for s in day.stops]
    for k, (stop, p) in enumerate(zip(day.stops, places, strict=True)):
        if p is None:  # not a planned place: it was voted Skip
            text = f"Place {stop.place_id} was voted Skip but is in the plan"
            out.append(Issue("error", "skip_included", text, stop.place_id, n))
            continue
        if stop.travel > (MAX_TRANSFER if k else MAX_DAY_TRIP):  # first trip may be a day trip
            text = f"{stop.travel} min trip to {p.name} on Day {n}"
            out.append(Issue("error", "long_transfer", text, p.id, n))
        wd = day.date.weekday()
        if parse(p.hours) is None:
            out.append(
                Issue("warning", "hours_unknown", f"Opening hours unknown for {p.name}", p.id)
            )
        elif not open_through(p.hours, wd, stop.start, stop.end):
            text = f"{p.name} is closed at {hhmm(stop.start)} on Day {n}"
            out.append(Issue("error", "closed", text, p.id, n))
    planned = [p for p in places if p is not None]
    if day.stops and planned:
        start, latest, span = limits(inp.window, planned)
        last = inp.place(day.stops[-1].place_id) or planned[-1]
        finish = day.stops[-1].end + estimate(last.point, inp.base)[0]
        begin = day.stops[0].start - day.stops[0].travel
        if finish > latest or finish - begin > span or (inp.window.fixed and begin < start):
            text = f"Day {n} runs too long (back at {hhmm(finish)})"
            out.append(Issue("error", "day_too_long", text, None, n))
    food = [s for s, p in zip(day.stops, places, strict=True) if p and is_food(p.category)]
    meal = any(_overlaps(s.start, s.end, LUNCH) or _overlaps(s.start, s.end, DINNER) for s in food)
    if food and not meal:
        text = f"No meal stop at lunch or dinner time on Day {n}"
        out.append(Issue("warning", "meal_time", text, None, n))
    return out


def validate(plan: Plan, inp: PlanInput) -> list[Issue]:
    """Every issue in the plan: errors first, then warnings."""
    issues = []
    for n, day in enumerate(plan.days, start=1):
        issues += _check_day(n, day, inp)
    planned = {s.place_id for d in plan.days for s in d.stops}
    for p in inp.places:
        if p.tier == "must" and p.id not in planned:
            text = f"{p.name} (Must-go) is not in the plan"
            issues.append(Issue("error", "missing_must", text, p.id))
    if not inp.base_is_hotel:
        text = "No hotel pin: days start from the city centre"
        issues.append(Issue("warning", "no_hotel_pin", text))
    return sorted(issues, key=lambda i: i.level != "error")  # stable: errors first


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]


def savable(plan: Plan, issues: list[Issue]) -> bool:
    """OK to save: no errors, except Must-gos that build_days dropped with a reason."""
    dropped = {d.place_id for d in plan.dropped}
    return all(i.code == "missing_must" and i.place_id in dropped for i in errors(issues))
