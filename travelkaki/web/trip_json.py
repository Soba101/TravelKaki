"""Turn a trip from the database into the JSON the map page needs (M3, #24).

Pure database -> dict code, so it is easy to test without a web server.
"""

from sqlalchemy.orm import Session

from travelkaki.bot.cards import maps_url
from travelkaki.db.models import Trip
from travelkaki.db.place_queries import places_with_counts
from travelkaki.planner.rules import tier
from travelkaki.web.days_json import days_json


def trip_json(s: Session, trip: Trip) -> dict:
    """City, hotel pin (or None), every place with its votes and tier, and plan days."""
    hotel = None
    if trip.hotel_lat is not None and trip.hotel_lng is not None:
        hotel = {"name": trip.hotel or "Hotel", "lat": trip.hotel_lat, "lng": trip.hotel_lng}

    places = []
    for p, c in places_with_counts(s, trip.id):
        places.append(
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "lat": p.lat,  # None = no pin; the page lists these under the map
                "lng": p.lng,
                "address": p.address,
                "must": c.must,
                "maybe": c.maybe,
                "skip": c.skip,
                # Same rule the planner uses, so map colours match /plan.
                "tier": tier(c.must, c.maybe, c.skip),
                "maps_url": maps_url(p, trip.city),
            }
        )
    # days = the latest /plan, for the day tabs (M3, #25). [] before the first /plan.
    # center = where to look when nothing has a pin yet (live check 2026-10-06 showed
    # the whole world map). The city centre from /newtrip, or None.
    center = None
    if trip.city_lat is not None and trip.city_lng is not None:
        center = [trip.city_lat, trip.city_lng]
    return {
        "city": trip.city,
        "center": center,
        "hotel": hotel,
        "places": places,
        "days": days_json(s, trip),
    }
