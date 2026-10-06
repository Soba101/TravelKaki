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
    """Pin every place that was never geocoded. Returns (pinned, not found).

    Each DB read and write uses its own short session. No session stays open while
    we wait on Nominatim (1 s sleeps), so a bot write in between can't be overwritten.
    """
    done = missed = 0
    with deps.sessions() as s:
        trips = [(t.id, t.city, t.city_lat, t.city_lng) for t in s.scalars(select(Trip))]
    for trip_id, city_name, lat, lng in trips:
        # "Never geocoded" = no pin AND hours never checked. A place whose pin was
        # removed with "Wrong place" has hours set, so we leave it alone.
        with deps.sessions() as s:
            todo = [
                (p.id, p.name)
                for p in s.scalars(
                    select(Place).where(
                        Place.trip_id == trip_id, Place.lat.is_(None), Place.opening_hours.is_(None)
                    )
                )
            ]
        if not todo:
            continue
        if lat is None:  # pin the city first: searches are kept near it
            city = await geo.search(city_name)
            if city:
                lat, lng = city.lat, city.lng
                with deps.sessions() as s:
                    trip = s.get(Trip, trip_id)
                    trip.city_lat, trip.city_lng = lat, lng
                    s.commit()  # keep the city pin
        centre = (lat, lng) if lat is not None else None
        for place_id, name in todo:
            try:
                hit, confidence = await geo.locate(name, city_name, centre)
                if hit is None:  # leave it unpinned; the next run tries again
                    missed += 1
                    continue
                with deps.sessions() as s:  # short session: re-read, write, commit
                    place = s.get(Place, place_id)
                    place.lat, place.lng, place.address = hit.lat, hit.lng, hit.address
                    place.confidence, place.opening_hours = confidence, hit.opening_hours or ""
                    s.commit()  # per place, so a crash keeps what was done
                done += 1
            except Exception:  # one odd response must not lose the whole run
                log.exception("backfill failed for place %s", place_id)
                missed += 1
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
