"""build_days: group by area, order by distance, fit opening hours (M2 Task 5, #18)."""

from tests.planner_helpers import make_input, place, planned_ids
from travelkaki.planner.build import build_days
from travelkaki.planner.travel import estimate
from travelkaki.planner.types import Priorities, Window

AREA_A = (35.6600, 139.7000)  # Shibuya-ish
AREA_B = (35.7300, 139.8000)  # ~12 km away
BASE_MID = (35.6950, 139.7500)


def _all_ids(plan):
    """Every place id in the plan's days or dropped list."""
    return sorted(
        [s.place_id for d in plan.days for s in d.stops] + [x.place_id for x in plan.dropped]
    )


def test_clusters_by_area():
    places = [
        place(1, *AREA_A), place(2, AREA_A[0] + 0.002, AREA_A[1]),
        place(3, *AREA_B), place(4, AREA_B[0] + 0.002, AREA_B[1]),
    ]  # fmt: skip
    plan = build_days(make_input(places, days=2, base=BASE_MID))
    groups = sorted(sorted(ids) for ids in planned_ids(plan).values())
    assert groups == [[1, 2], [3, 4]]


def test_same_input_same_plan():
    places = [place(i, 35.68 + i * 0.003, 139.70 + i * 0.002) for i in range(1, 8)]
    inp = make_input(places, days=2)
    assert build_days(inp) == build_days(inp)


def test_every_place_ends_up_somewhere():
    places = [place(i, 35.68 + i * 0.003, 139.70) for i in range(1, 15)]
    assert _all_ids(build_days(make_input(places, days=1))) == list(range(1, 15))


def test_closed_day_moves_must():
    closed_tuesday = "Mo-Su 10:00-18:00; Tu off"
    plan = build_days(make_input([place(1, hours=closed_tuesday)], days=2))  # Tue, Wed
    assert planned_ids(plan) == {1: [], 2: [1]}


def test_closed_whole_trip_dropped():
    plan = build_days(make_input([place(1, hours="Mo 10:00-18:00")], days=2))  # Tue, Wed
    assert planned_ids(plan) == {1: [], 2: []}
    assert "closed" in plan.dropped[0].reason


def test_waits_for_opening():
    plan = build_days(make_input([place(1, hours="Mo-Su 10:00-18:00")], days=1))
    assert plan.days[0].stops[0].start == 600


def test_no_time_left():
    places = [place(i, 35.69 + i * 0.001, 139.70) for i in range(1, 13)]  # 12 x 2 h
    plan = build_days(make_input(places, days=1))
    assert plan.dropped and all("no time left" in d.reason for d in plan.dropped)
    assert max(s.end for s in plan.days[0].stops) <= 1320


def test_evening_place_extends_day():
    bar = place(1, category="bar", hours="Mo-Su 21:00-02:00")
    stop = build_days(make_input([bar], days=1)).days[0].stops[0]
    assert stop.start == 1260 and 1320 < stop.end <= 1500


def test_fixed_window():
    places = [place(i, 35.69 + i * 0.002, 139.70) for i in range(1, 8)]
    plan = build_days(make_input(places, days=1, window=Window(600, 1200, fixed=True)))
    stops = plan.days[0].stops
    last = places[[p.id for p in places].index(stops[-1].place_id)]
    assert stops[0].start >= 600
    assert stops[-1].end + estimate(last.point, (35.69, 139.70))[0] <= 1200


def test_exclude_pins_include():
    places = [place(1), place(2, 35.692, 139.70), place(3, 35.694, 139.70, tier="maybe")]
    plan = build_days(make_input(places, days=2), Priorities(exclude=[1], pins={2: 2}, include=[3]))
    ids = planned_ids(plan)
    assert 2 in ids[2]  # pinned to day 2
    assert 3 in ids[1] + ids[2]  # included maybe is planned
    assert 1 not in ids[1] + ids[2]  # excluded: the agent's choice (listed in dropped)


def test_more_days_than_places():
    plan = build_days(make_input([place(1)], days=3))
    assert len(plan.days) == 3
    assert sum(1 for d in plan.days if not d.stops) == 2


def test_too_far_from_other_stops_is_dropped():
    """Between stops the 60-min rule still holds: a far place can't follow a city stop
    on a 1-day trip, so one of them is dropped with a reason."""
    far = place(2, 36.30, 139.70, tier="maybe")  # ~68 km away
    plan = build_days(make_input([place(1), far], days=1))
    assert all(s.travel <= 60 for s in plan.days[0].stops[1:])
    assert [d.place_id for d in plan.dropped] == [2]


def test_dropped_bar_does_not_stretch_the_day():
    """Review #1: a bar closed today must not give other stops a 01:00 limit."""
    from travelkaki.planner.validate import savable, validate

    museums = [place(i, 35.69 + i * 0.003, 139.70, hours="Mo-Su 12:00-24:00") for i in range(1, 6)]
    bar = place(9, 35.70, 139.70, category="bar", hours="Mo-Su 19:00-02:00; Tu off")
    inp = make_input(museums + [bar], days=1)
    plan = build_days(inp)
    assert savable(plan, validate(plan, inp))


def test_must_gos_beat_maybes():
    """Review #2: Must-gos are planned before Maybes take the time."""
    maybes = [place(10 + i, 35.6900 + i * 0.0005, 139.70, tier="maybe") for i in range(6)]
    musts = [place(1, 35.701, 139.70), place(2, 35.702, 139.70)]
    plan = build_days(make_input(maybes + musts, days=1))
    planned = planned_ids(plan)[1]
    assert 1 in planned and 2 in planned
    assert all("no time left" in d.reason for d in plan.dropped)


def test_excluded_must_is_dropped_with_reason():
    """Review #3: the agent may leave a Must-go out; it's listed, so the plan can be saved."""
    from travelkaki.planner.validate import savable, validate

    inp = make_input([place(1), place(2, 35.692, 139.70)], days=1)
    plan = build_days(inp, Priorities(exclude=[2]))
    assert [(d.place_id, d.reason) for d in plan.dropped] == [(2, "left out by the planner")]
    assert savable(plan, validate(plan, inp))


def test_pinned_places_stay_on_their_day():
    """Review #4: an over-full pinned day doesn't move pins elsewhere."""
    places = [place(i, 35.69 + i * 0.001, 139.70) for i in range(1, 8)]
    plan = build_days(make_input(places, days=2), Priorities(pins={i: 1 for i in range(1, 8)}))
    assert planned_ids(plan)[2] == []


def test_24_7_place_after_midnight_is_planned():
    """Review #5: a late 24/7 karaoke after a bar is not 'closed'."""
    bar = place(1, category="bar", hours="Mo-Su 22:00-23:30", visit=90)  # 22:00-23:30
    karaoke = place(2, 35.6905, 139.70, category="karaoke club", hours="24/7", visit=60)
    plan = build_days(make_input([bar, karaoke], days=1))
    assert planned_ids(plan)[1] == [1, 2]


def test_day_trip_gets_its_own_day():
    """Donovan: a far Must-go (e.g. ~70 km away) is a day trip, not dropped.
    The first stop of a day may be up to 3 h from the hotel."""
    from travelkaki.planner.validate import savable, validate

    far = place(9, 36.30, 139.70)  # ~68 km north
    city = [place(1), place(2, 35.692, 139.70)]
    inp = make_input(city + [far], days=2)
    plan = build_days(inp)
    ids = planned_ids(plan)
    assert [9] in ids.values()  # alone on its own day
    assert savable(plan, validate(plan, inp))


def test_far_place_goes_first_on_its_day():
    far = place(9, 36.30, 139.70)
    near_far = place(8, 36.302, 139.70)
    plan = build_days(make_input([far, near_far], days=1))
    assert planned_ids(plan)[1][0] in (8, 9) and len(planned_ids(plan)[1]) == 2
