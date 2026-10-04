"""prepare(): read one trip from the DB into a PlanInput (M2 spec, "Planner input").

Steps:
1. No trip / no dates / over 14 days -> PlanError with a code the bot turns into a reply.
2. Tier each place from its votes. Skip-tier places are never planned.
   Places with no map pin can't be routed: listed as "no map pin".
3. The hotel is geocoded once (stored). Not found -> the city centre.
4. Places never checked for opening hours get one lookup (~1 s each, cached in the DB).
5. Visit length comes from the category.
"""

from datetime import timedelta

from travelkaki.db import place_queries as pq
from travelkaki.db import plan_queries as plq
from travelkaki.db import queries
from travelkaki.geo.distance import viewbox
from travelkaki.planner.rules import tier, visit_minutes
from travelkaki.planner.types import Dropped, PlanInput, PlanPlace, Window

MAX_DAYS = 14
MAX_HOURS_LOOKUPS = 25  # per /plan run, so a big trip doesn't wait too long


class PlanError(Exception):
    """Can't plan this trip. `code`: no_trip, no_dates, too_many_days, no_places."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


async def _base(deps, trip, places) -> tuple[tuple[float, float], bool]:
    """(base point, is it the hotel?). Hotel pin, else city centre, else the places' middle."""
    centre = (trip.city_lat, trip.city_lng) if trip.city_lat is not None else None
    if trip.hotel and trip.hotel_lat is None and deps.geo is not None:
        hit, _ = await deps.geo.locate(trip.hotel, trip.city, centre)
        if hit is not None:
            with deps.sessions() as s:
                plq.set_hotel_pin(s, trip.id, hit.lat, hit.lng)
            trip.hotel_lat, trip.hotel_lng = hit.lat, hit.lng
    if trip.hotel and trip.hotel_lat is not None:
        return (trip.hotel_lat, trip.hotel_lng), True
    if centre is not None:
        return centre, False
    lat = sum(p.lat for p in places) / len(places)
    return (lat, sum(p.lng for p in places) / len(places)), False


async def _backfill_hours(deps, city: str, places: list[PlanPlace], progress) -> None:
    """Look up OSM hours for places never checked. A miss stays None (try next time)."""
    todo = [p for p in places if p.hours is None][:MAX_HOURS_LOOKUPS]
    if not todo or deps.geo is None:
        return
    if progress is not None:
        await progress("Checking opening hours…")
    for p in todo:
        # A tiny box (~1 km) around the saved pin, so we find the same place.
        hit = await deps.geo.search(f"{p.name}, {city}", viewbox(p.point, 1))
        if hit is not None:
            p.hours = hit.opening_hours or ""
            with deps.sessions() as s:
                plq.set_hours(s, p.id, p.hours)


async def prepare(deps, chat_id: int, window: Window, progress=None) -> PlanInput:
    """Everything the planner needs for this chat's trip. Raises PlanError."""
    with deps.sessions() as s:
        trip = queries.get_trip(s, chat_id)
        if trip is None:
            raise PlanError("no_trip")
        if trip.start_date is None or trip.end_date is None:
            raise PlanError("no_dates")
        n_days = (trip.end_date - trip.start_date).days + 1
        if n_days > MAX_DAYS:
            raise PlanError("too_many_days")
        rows = pq.places_with_counts(s, trip.id)
    places, skipped, dropped = [], [], []
    for p, votes in rows:
        t = tier(votes.must, votes.maybe, votes.skip)
        if t == "skip":
            skipped.append(p.id)
        elif p.lat is None:
            dropped.append(Dropped(p.id, p.name, "no map pin"))
        else:
            places.append(
                PlanPlace(p.id, p.name, p.category, p.lat, p.lng, t, votes.must, votes.maybe,
                          p.opening_hours, visit_minutes(p.category), p.video_note, p.address)
            )  # fmt: skip
    if not places:
        raise PlanError("no_places")
    base, is_hotel = await _base(deps, trip, places)
    await _backfill_hours(deps, trip.city, places, progress)
    dates = [trip.start_date + timedelta(days=i) for i in range(n_days)]
    return PlanInput(trip.id, trip.city, dates, base, is_hotel, places, skipped, dropped, window)
