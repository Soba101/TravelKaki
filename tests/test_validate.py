"""validate(plan): itinerary rules with errors and warnings (M2 Task 6, #19)."""

from dataclasses import replace

from tests.planner_helpers import TUE, make_input, place
from travelkaki.planner.build import build_days
from travelkaki.planner.types import Day, Dropped, Plan, Stop
from travelkaki.planner.validate import errors, savable, validate


def _codes(issues, level=None):
    return [i.code for i in issues if level is None or i.level == level]


def _one_stop(p, start=600, travel=5, end=None):
    return Plan([Day(TUE, [Stop(p.id, start, end or start + p.visit, travel, "walk")])])


def test_clean_plan_has_no_errors():
    p = place(1, hours="Mo-Su 09:00-20:00")
    assert errors(validate(_one_stop(p), make_input([p], days=1))) == []


def test_missing_must():
    p, q = place(1), place(2)
    issues = validate(_one_stop(p), make_input([p, q], days=1))
    assert _codes(issues, "error") == ["missing_must"]
    assert "Place 2" in issues[0].text


def test_missing_maybe_is_fine():
    p, q = place(1), place(2, tier="maybe")
    assert errors(validate(_one_stop(p), make_input([p, q], days=1))) == []


def test_skip_included():
    p = place(1)
    inp = make_input([p], days=1, skipped=[9])
    plan = Plan([Day(TUE, [Stop(1, 600, 720, 5, "walk"), Stop(9, 730, 790, 5, "walk")])])
    assert "skip_included" in _codes(validate(plan, inp), "error")


def test_closed():
    p = place(1, hours="Mo-Su 12:00-20:00")
    issues = validate(_one_stop(p, start=600), make_input([p], days=1))
    assert _codes(issues, "error") == ["closed"]
    assert "10:00" in issues[0].text and "Day 1" in issues[0].text


def test_closes_during_visit():
    p = place(1, hours="Mo-Su 09:00-11:00")  # 2 h museum from 10:00
    assert "closed" in _codes(validate(_one_stop(p, start=600), make_input([p], days=1)))


def test_day_too_long():
    p = place(1, visit=60)
    plan = _one_stop(p, start=1300)  # ends 22:40, after 22:00
    assert "day_too_long" in _codes(validate(plan, make_input([p], days=1)), "error")


def test_long_transfer():
    """A 75-min hop between two stops breaks the rule (the first trip may be longer)."""
    p, q = place(1), place(2)
    plan = Plan([Day(TUE, [Stop(1, 600, 720, 5, "walk"), Stop(2, 795, 915, 75, "transit")])])
    assert "long_transfer" in _codes(validate(plan, make_input([p, q], days=1)))


def test_hours_unknown_is_a_warning():
    p = place(1, hours=None)
    issues = validate(_one_stop(p), make_input([p], days=1))
    assert _codes(issues) == ["hours_unknown"] and issues[0].level == "warning"


def test_meal_time():
    p = place(1, category="ramen", hours="24/7")
    late = validate(_one_stop(p, start=930), make_input([p], days=1))  # 15:30
    assert _codes(late, "warning") == ["meal_time"]
    lunch = validate(_one_stop(p, start=720), make_input([p], days=1))
    assert _codes(lunch) == []


def test_no_hotel_pin():
    p = place(1, hours="24/7")
    inp = replace(make_input([p], days=1), base_is_hotel=False)
    assert _codes(validate(_one_stop(p), inp)) == ["no_hotel_pin"]


def test_savable_accepts_dropped_must_only():
    p, q = place(1, hours="24/7"), place(2)
    plan = _one_stop(p)
    plan.dropped = [Dropped(2, "Place 2", "closed on Tue 15 Dec")]
    inp = make_input([p, q], days=1)
    assert savable(plan, validate(plan, inp))
    plan.dropped = []
    assert not savable(plan, validate(plan, inp))


def test_savable_rejects_closed():
    p = place(1, hours="Mo-Su 12:00-20:00")
    plan = _one_stop(p, start=600)
    assert not savable(plan, validate(plan, make_input([p], days=1)))


def test_build_days_output_is_savable():
    places = [place(i, 35.68 + i * 0.004, 139.70 + (i % 3) * 0.01, hours="Mo-Sa 10:00-20:00")
              for i in range(1, 12)]  # fmt: skip
    places.append(place(20, category="bar", hours="Mo-Su 19:00-02:00"))
    inp = make_input(places, days=2)
    plan = build_days(inp)
    assert savable(plan, validate(plan, inp))


def test_visit_across_a_break_is_closed():
    """Review #12: open at the start and end isn't enough if it closes in between."""
    p = place(1, hours="Mo-Su 10:00-14:00,14:30-20:00")  # 2 h museum from 13:00
    assert "closed" in _codes(validate(_one_stop(p, start=780), make_input([p], days=1)))


def test_first_stop_may_be_a_long_day_trip():
    """A day may start with a trip of up to 3 h; later hops are capped at 60 min."""
    p = place(1, hours="24/7")
    inp = make_input([p], days=1)
    assert "long_transfer" not in _codes(validate(_one_stop(p, travel=150), inp))
    assert "long_transfer" in _codes(validate(_one_stop(p, travel=200), inp))
