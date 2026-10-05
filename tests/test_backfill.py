"""Tests for the pin backfill (#54): places saved without lat/lng get geocoded later."""

from tests.fakes import make_deps
from travelkaki.db import place_queries as pq
from travelkaki.db import queries
from travelkaki.db.models import Place, Trip
from travelkaki.geo.backfill import backfill
from travelkaki.geo.nominatim import GeoResult


class FakeGeo:
    """search() finds the city; locate() finds every place except those in `missing`."""

    def __init__(self, missing=()):
        self.missing, self.centers = set(missing), []

    async def search(self, query, box=None):
        return GeoResult(35.68, 139.69, "Tokyo, Japan")

    async def locate(self, name, city, center):
        self.centers.append(center)
        if name in self.missing:
            return None, "none"
        return GeoResult(35.66, 139.70, f"{name} St", opening_hours="Mo-Su 09:00-18:00"), "high"


def _trip_with_unpinned(sessions, *names):
    with sessions() as s:
        trip = queries.upsert_trip(s, 1, "Tokyo", None, None, None)  # no city pin either
        for n in names:
            pq.add_place(s, trip.id, name=n, category="food", video_note="")
        return trip.id


async def test_backfill_pins_places_and_city(sessions):
    _trip_with_unpinned(sessions, "Ichiran", "Tsukiji Market")
    geo = FakeGeo()

    done, missed = await backfill(make_deps(sessions), geo)

    assert (done, missed) == (2, 0)
    with sessions() as s:
        places = s.query(Place).all()
        assert all((p.lat, p.lng) == (35.66, 139.70) for p in places)
        assert places[0].confidence == "high" and places[0].opening_hours == "Mo-Su 09:00-18:00"
        assert (s.query(Trip).one().city_lat) == 35.68  # the city got pinned too
    assert geo.centers[0] == (35.68, 139.69)  # places were searched near the city


async def test_backfill_counts_misses_and_skips_pinned_and_wrong_place(sessions):
    trip_id = _trip_with_unpinned(sessions, "Nowhere", "Pinned", "Wrong one")
    with sessions() as s:
        a, b = s.query(Place).filter(Place.name.in_(["Pinned", "Wrong one"])).all()
        pinned, wrong = (a, b) if a.name == "Pinned" else (b, a)
        pinned.lat, pinned.lng = 1.0, 2.0
        wrong.opening_hours = ""  # was pinned once, then "Wrong place" cleared it
        s.commit()

    done, missed = await backfill(make_deps(sessions), FakeGeo(missing={"Nowhere"}))

    assert (done, missed) == (0, 1)
    with sessions() as s:
        by_name = {p.name: p for p in pq.trip_places(s, trip_id)}
        assert by_name["Pinned"].lat == 1.0
        assert by_name["Wrong one"].lat is None  # the user rejected that pin; leave it
