"""Tests for the day routes the map shows (M3, #25)."""

from datetime import date

from travelkaki.db.place_queries import add_place
from travelkaki.db.plan_queries import save_itinerary
from travelkaki.db.queries import upsert_trip
from travelkaki.planner.types import Day, Plan, Stop
from travelkaki.web.days_json import days_json

D1, D2 = date(2026, 12, 12), date(2026, 12, 13)


def make_trip(s, hotel=True):
    trip = upsert_trip(s, -100, "Tokyo", D1, D2, "Hotel X", 35.0, 139.0)
    if hotel:
        trip.hotel_lat, trip.hotel_lng = 35.6, 139.7
    a = add_place(s, trip.id, name="A <b>", category="ramen", video_note="", lat=35.7, lng=139.8)
    b = add_place(s, trip.id, name="B", category="temple", video_note="", lat=35.8, lng=139.9)
    return trip, a, b


def save(s, trip, days):
    save_itinerary(s, trip.id, "run", Plan(days=days), used_ai=True, tradeoffs="", window="flex")


def test_no_plan_means_no_days(sessions):
    with sessions() as s:
        trip, _, _ = make_trip(s)
        assert days_json(s, trip) == []


def test_latest_plan_days_in_order(sessions):
    with sessions() as s:
        trip, a, b = make_trip(s)
        save(s, trip, [Day(D1, [Stop(a.id, 600, 660, 20, "transit")])])  # old version
        save(s, trip, [
            Day(D1, [Stop(b.id, 600, 660, 20, "transit"), Stop(a.id, 700, 760, 10, "walk")]),
            Day(D2, [Stop(a.id, 540, 600, 15, "walk")]),
        ])  # fmt: skip
        days = days_json(s, trip)

    assert [d["label"] for d in days] == ["Sat 12 Dec", "Sun 13 Dec"]
    first = days[0]["stops"]
    assert [x["name"] for x in first] == ["B", "A <b>"]  # escaping is the page's job
    assert first[0] == {
        "place_id": b.id, "name": "B", "lat": 35.8, "lng": 139.9,
        "start": "10:00", "end": "11:00", "travel": 20,
    }  # fmt: skip
    # Route link starts and ends at the hotel.
    assert days[0]["links"][0].startswith(
        "https://www.google.com/maps/dir/?api=1&origin=35.6,139.7"
    )


def test_no_hotel_pin_uses_city_centre(sessions):
    with sessions() as s:
        trip, a, _ = make_trip(s, hotel=False)
        save(s, trip, [Day(D1, [Stop(a.id, 600, 660, 20, "transit")])])
        days = days_json(s, trip)
    assert "origin=35.0,139.0" in days[0]["links"][0]
