"""Backfill map pins for places saved without lat/lng (issue #54).

Why this exists: the live Test trip was created before geocoding shipped (#12/#13),
so its places and its city have no pin. Nothing ever goes back for them, so the map
and /plan have nothing to draw. This is a small one-off CLI instead of work inside
/plan: /plan stays fast, and a run is easy to repeat (it only touches unpinned places).

Run:  python -m travelkaki.geo.backfill
"""

import asyncio
import logging

import httpx
from sqlalchemy import select

from travelkaki.config import get_settings
from travelkaki.db.base import init_db, make_engine, make_sessions
from travelkaki.db.models import Place, Trip
from travelkaki.deps import Deps
from travelkaki.geo.nominatim import Nominatim

log = logging.getLogger(__name__)


async def backfill(deps: Deps, geo) -> tuple[int, int]:
    """Pin every place that was never geocoded. Returns (pinned, not found)."""
    done = missed = 0
    with deps.sessions() as s:
        trips = s.scalars(select(Trip)).all()
        for trip in trips:
            # "Never geocoded" = no pin AND hours never checked. A place whose pin was
            # removed with "Wrong place" has hours set, so we leave it alone.
            todo = s.scalars(
                select(Place).where(
                    Place.trip_id == trip.id, Place.lat.is_(None), Place.opening_hours.is_(None)
                )
            ).all()
            if not todo:
                continue
            if trip.city_lat is None:  # pin the city first: searches are kept near it
                city = await geo.search(trip.city)
                if city:
                    trip.city_lat, trip.city_lng = city.lat, city.lng
            centre = (trip.city_lat, trip.city_lng) if trip.city_lat is not None else None
            for place in todo:
                hit, confidence = await geo.locate(place.name, trip.city, centre)
                if hit is None:  # leave it unpinned; the next run tries again
                    missed += 1
                    continue
                place.lat, place.lng, place.address = hit.lat, hit.lng, hit.address
                place.confidence, place.opening_hours = confidence, hit.opening_hours or ""
                done += 1
            s.commit()  # one trip at a time, so a crash keeps what was done
    return done, missed


async def main() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    init_db(engine)
    async with httpx.AsyncClient() as http:
        geo = Nominatim(http, email=settings.nominatim_email)
        done, missed = await backfill(Deps(sessions=make_sessions(engine)), geo)
    print(f"Pinned {done} places, {missed} not found (run again to retry those).")


if __name__ == "__main__":
    asyncio.run(main())
