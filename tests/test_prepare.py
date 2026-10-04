"""prepare(): trip + votes + hotel + hours -> PlanInput (M2 Task 9, #17)."""

from datetime import date

import pytest

from tests.fakes import make_deps
from travelkaki.db import place_queries as pq
from travelkaki.db import queries
from travelkaki.db.models import Place, Trip
from travelkaki.geo.nominatim import GeoResult
from travelkaki.planner.prepare import PlanError, prepare
from travelkaki.planner.types import Window

CENTER = (35.68, 139.76)


class FakeGeo:
    """locate() finds the hotel; search() returns hours. Counts the calls."""

    def __init__(self, hotel=(35.69, 139.70), hours="Mo-Su 10:00-20:00"):
        self.hotel, self.hours = hotel, hours
        self.locates, self.searches = 0, 0

    async def locate(self, name, city, center):
        self.locates += 1
        if self.hotel is None:
            return None, "none"
        return GeoResult(*self.hotel, "Hotel address"), "high"

    async def search(self, query, box=None):
        self.searches += 1
        return GeoResult(35.6, 139.7, "x", opening_hours=self.hours)


def _trip(sessions, start=date(2026, 12, 15), end=date(2026, 12, 16), hotel="Gracery"):
    with sessions() as s:
        return queries.upsert_trip(s, 1, "Tokyo", start, end, hotel, *CENTER)


def _add(sessions, trip, name, votes=(), lat=35.69, hours=None):
    with sessions() as s:
        p = pq.add_place(s, trip.id, name=name, category="ramen", video_note="slurp", lat=lat,
                         lng=139.70 if lat else None, opening_hours=hours)  # fmt: skip
        for user, value in votes:
            pq.vote(s, p.id, user, value)
        return p


def _deps(sessions, geo=None):
    deps = make_deps(sessions)
    deps.geo = geo or FakeGeo()
    return deps


async def test_no_trip(sessions):
    with pytest.raises(PlanError) as e:
        await prepare(_deps(sessions), 1, Window())
    assert e.value.code == "no_trip"


async def test_no_dates(sessions):
    _trip(sessions, start=None, end=None)
    with pytest.raises(PlanError) as e:
        await prepare(_deps(sessions), 1, Window())
    assert e.value.code == "no_dates"


async def test_too_many_days(sessions):
    trip = _trip(sessions, end=date(2026, 12, 29))  # 15 days
    _add(sessions, trip, "A")
    with pytest.raises(PlanError) as e:
        await prepare(_deps(sessions), 1, Window())
    assert e.value.code == "too_many_days"


async def test_no_places(sessions):
    trip = _trip(sessions)
    _add(sessions, trip, "Unpinned", lat=None)
    with pytest.raises(PlanError) as e:
        await prepare(_deps(sessions), 1, Window())
    assert e.value.code == "no_places"


async def test_tiers_skips_and_unpinned(sessions):
    trip = _trip(sessions)
    must = _add(sessions, trip, "Must", votes=[(1, "must")], hours="24/7")
    maybe = _add(sessions, trip, "Nobody voted", hours="24/7")
    skip = _add(sessions, trip, "Skip", votes=[(1, "skip"), (2, "skip")], hours="24/7")
    unpinned = _add(sessions, trip, "No pin", lat=None)
    inp = await prepare(_deps(sessions), 1, Window())
    assert [(p.id, p.tier) for p in inp.places] == [(must.id, "must"), (maybe.id, "maybe")]
    assert inp.skipped == [skip.id]
    assert [(d.place_id, d.reason) for d in inp.dropped] == [(unpinned.id, "no map pin")]
    assert inp.dates == [date(2026, 12, 15), date(2026, 12, 16)]
    assert inp.places[0].visit == 60 and inp.places[0].note == "slurp"


async def test_hotel_pinned_once(sessions):
    trip = _trip(sessions)
    _add(sessions, trip, "A", hours="24/7")
    geo = FakeGeo()
    inp = await prepare(_deps(sessions, geo), 1, Window())
    assert inp.base == (35.69, 139.70) and inp.base_is_hotel
    await prepare(_deps(sessions, geo), 1, Window())
    assert geo.locates == 1  # stored after the first time
    with sessions() as s:
        assert s.get(Trip, trip.id).hotel_lat == 35.69


async def test_hotel_not_found_uses_city_centre(sessions):
    trip = _trip(sessions)
    _add(sessions, trip, "A", hours="24/7")
    inp = await prepare(_deps(sessions, FakeGeo(hotel=None)), 1, Window())
    assert inp.base == CENTER and not inp.base_is_hotel


async def test_hours_backfilled_and_saved(sessions):
    trip = _trip(sessions)
    a = _add(sessions, trip, "A", hours=None)
    _add(sessions, trip, "B", hours="")  # already checked: no new lookup
    geo, progress = FakeGeo(), []

    async def note(text):
        progress.append(text)

    inp = await prepare(_deps(sessions, geo), 1, Window(), progress=note)
    assert geo.searches == 1
    assert inp.place(a.id).hours == "Mo-Su 10:00-20:00"
    assert progress == ["Checking opening hours…"]
    with sessions() as s:
        assert s.get(Place, a.id).opening_hours == "Mo-Su 10:00-20:00"


async def test_new_hotel_is_looked_up_again(sessions):
    """/newtrip with a different hotel must not keep the old hotel's pin."""
    trip = _trip(sessions)
    _add(sessions, trip, "A", hours="24/7")
    geo = FakeGeo()
    await prepare(_deps(sessions, geo), 1, Window())
    _trip(sessions, hotel="Park Hyatt")
    await prepare(_deps(sessions, geo), 1, Window())
    assert geo.locates == 2
