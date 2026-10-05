"""The trip's latest /plan as day routes for the map's day tabs (M3, #25).

Reads the newest Itinerary version and its ItineraryItems (saved by /plan).
Each day: a label, its stops in order, and Google Maps route links
(hotel -> stops -> hotel), the same links the /plan message has.
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelkaki.bot.plan_text import route_links
from travelkaki.db.models import Itinerary, ItineraryItem, Place, Trip
from travelkaki.planner.fit import day_label, hhmm


def _base(trip: Trip):
    """Where each day starts and ends: the hotel pin, else the city centre, else None."""
    if trip.hotel_lat is not None and trip.hotel_lng is not None:
        return (trip.hotel_lat, trip.hotel_lng)
    if trip.city_lat is not None and trip.city_lng is not None:
        return (trip.city_lat, trip.city_lng)
    return None


def days_json(s: Session, trip: Trip) -> list[dict]:
    """[] if the trip has no plan yet."""
    latest = s.scalar(
        select(Itinerary)
        .where(Itinerary.trip_id == trip.id)
        .order_by(Itinerary.version.desc())
        .limit(1)
    )
    if latest is None:
        return []

    rows = s.execute(
        select(ItineraryItem, Place)
        .join(Place, Place.id == ItineraryItem.place_id)
        .where(ItineraryItem.itinerary_id == latest.id)
        .order_by(ItineraryItem.day, ItineraryItem.order)
    )
    by_day = defaultdict(list)  # dicts keep insert order, so days stay sorted
    for item, place in rows:
        by_day[item.day].append(
            {
                "place_id": place.id,
                "name": place.name,
                "lat": place.lat,
                "lng": place.lng,
                "start": hhmm(item.start_min),
                "end": hhmm(item.end_min),
                "travel": item.travel_minutes,
            }
        )

    base = _base(trip)
    days = []
    for day, stops in by_day.items():
        points = [(x["lat"], x["lng"]) for x in stops if x["lat"] is not None]
        links = route_links(base, points) if base else []
        days.append({"label": day_label(day), "stops": stops, "links": links})
    return days
