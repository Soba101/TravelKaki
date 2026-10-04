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
    assert 1 not in ids[1] + ids[2] and not plan.dropped  # excluded: the agent's choice


def test_more_days_than_places():
    plan = build_days(make_input([place(1)], days=3))
    assert len(plan.days) == 3
    assert sum(1 for d in plan.days if not d.stops) == 2


def test_far_place_is_not_planned_with_long_transfer():
    far = place(2, 36.30, 139.70)  # ~70 km away
    plan = build_days(make_input([place(1), far], days=1))
    assert all(s.travel <= 60 for d in plan.days for s in d.stops)
    assert [d.place_id for d in plan.dropped] == [2]
