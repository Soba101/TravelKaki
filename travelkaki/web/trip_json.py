"""Turn a trip from the database into the JSON the map page needs (M3, #24).

Pure database -> dict code, so it is easy to test without a web server.
"""

from sqlalchemy.orm import Session

from travelkaki.bot.cards import maps_url
from travelkaki.db.models import Trip
from travelkaki.db.place_queries import places_with_counts
from travelkaki.planner.rules import tier


def trip_json(s: Session, trip: Trip) -> dict:
    """City, hotel pin (or None) and every place with its votes and tier."""
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
    return {"city": trip.city, "hotel": hotel, "places": places}
