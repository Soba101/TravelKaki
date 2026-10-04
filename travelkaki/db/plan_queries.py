"""Database functions for the planner (M2). Each one commits its own change."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from travelkaki.db.models import AgentTrace, Itinerary, ItineraryItem, Place, Trip, Vote
from travelkaki.planner.types import Plan

MAX_TRACE_CHARS = 2000  # keep trace rows small; enough to debug a step


def set_hotel_pin(s: Session, trip_id: int, lat: float, lng: float) -> None:
    """Remember where the hotel is, so we only geocode it once."""
    trip = s.get(Trip, trip_id)
    trip.hotel_lat, trip.hotel_lng = lat, lng
    s.commit()


def set_hours(s: Session, place_id: int, raw: str) -> None:
    """Save OSM opening hours. Use "" for "checked, OSM has none"."""
    s.get(Place, place_id).opening_hours = raw
    s.commit()


def add_trace(
    s: Session,
    trip_id: int,
    run_id: str,
    step: int,
    kind: str,
    tool: str | None,
    input: str,
    output: str,
    tokens: int = 0,
) -> None:
    """Log one planner step (an LLM call or a tool call). Long text is cut."""
    s.add(
        AgentTrace(
            trip_id=trip_id,
            run_id=run_id,
            step=step,
            kind=kind,
            tool=tool,
            input=input[:MAX_TRACE_CHARS],
            output=output[:MAX_TRACE_CHARS],
            tokens=tokens,
        )
    )
    s.commit()


def voter_count(s: Session, trip_id: int) -> int:
    """How many different people voted on this trip's places (for ask_group)."""
    query = (
        select(func.count(func.distinct(Vote.tg_user_id)))
        .join(Place, Place.id == Vote.place_id)
        .where(Place.trip_id == trip_id)
    )
    return s.scalar(query) or 0


def save_itinerary(
    s: Session, trip_id: int, run_id: str, plan: Plan, *, used_ai: bool, tradeoffs: str, window: str
) -> Itinerary:
    """Save a plan as the trip's next version (1, 2, 3...). One item per stop."""
    last = s.scalar(select(func.max(Itinerary.version)).where(Itinerary.trip_id == trip_id))
    itinerary = Itinerary(
        trip_id=trip_id,
        version=(last or 0) + 1,
        run_id=run_id,
        used_ai=used_ai,
        tradeoffs=tradeoffs,
        window=window,
    )
    s.add(itinerary)
    s.flush()  # gives itinerary.id
    for day in plan.days:
        for order, stop in enumerate(day.stops):
            s.add(
                ItineraryItem(
                    itinerary_id=itinerary.id,
                    day=day.date,
                    order=order,
                    place_id=stop.place_id,
                    start_min=stop.start,
                    end_min=stop.end,
                    travel_minutes=stop.travel,
                )
            )
    s.commit()
    return itinerary
