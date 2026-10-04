"""Database functions for the planner (M2). Each one commits its own change.

save_itinerary is added with the agent loop (plan Task 11).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from travelkaki.db.models import AgentTrace, Place, Trip, Vote

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
