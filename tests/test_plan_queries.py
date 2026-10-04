"""Queries the planner uses: hotel pin, hours, traces, voter count (M2 Task 1)."""

from travelkaki.db import place_queries as pq
from travelkaki.db import plan_queries as plq
from travelkaki.db import queries
from travelkaki.db.models import AgentTrace, Place, Trip


def _trip(sessions):
    with sessions() as s:
        return queries.upsert_trip(s, 1, "Tokyo", None, None, "Gracery")


def test_hotel_pin_and_hours_saved(sessions):
    trip = _trip(sessions)
    with sessions() as s:
        place = pq.add_place(s, trip.id, name="Ichiran", category="ramen", video_note="")
        plq.set_hotel_pin(s, trip.id, 35.69, 139.70)
        plq.set_hours(s, place.id, "Mo-Su 10:00-22:00")
    with sessions() as s:
        assert s.get(Trip, trip.id).hotel_lat == 35.69
        assert s.get(Place, place.id).opening_hours == "Mo-Su 10:00-22:00"


def test_trace_is_cut(sessions):
    trip = _trip(sessions)
    with sessions() as s:
        plq.add_trace(s, trip.id, "run-1", 1, "tool", "validate", "{}", "x" * 5000, tokens=3)
        row = s.query(AgentTrace).one()
    assert len(row.output) == 2000
    assert row.tokens == 3 and row.kind == "tool"


def test_voter_count_distinct(sessions):
    trip = _trip(sessions)
    with sessions() as s:
        ids = [pq.add_place(s, trip.id, name=n, category="", video_note="").id for n in "abc"]
        for pid in ids:
            pq.vote(s, pid, 100, "must")
        pq.vote(s, ids[0], 200, "skip")
        assert plq.voter_count(s, trip.id) == 2
