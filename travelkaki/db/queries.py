"""Small, named database functions. Each one commits its own change.

Handlers and the pipeline call these instead of writing SQL themselves.
`s` is always an open Session (`with sessions() as s:`).
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from travelkaki.db.models import Source, SourceStatus, Trip

# ---------- trips ----------


def get_trip(s: Session, chat_id: int) -> Trip | None:
    """The chat's trip, or None if /newtrip was never run here."""
    return s.scalar(select(Trip).where(Trip.chat_id == chat_id))


def upsert_trip(
    s: Session,
    chat_id: int,
    city: str,
    start: date | None,
    end: date | None,
    hotel: str | None,
    city_lat: float | None = None,
    city_lng: float | None = None,
) -> Trip:
    """Create the chat's trip, or update it (places are kept)."""
    trip = get_trip(s, chat_id) or Trip(chat_id=chat_id)
    if trip.hotel != hotel:  # new hotel: forget the old hotel's pin (M2 planner)
        trip.hotel_lat = trip.hotel_lng = None
    trip.city, trip.start_date, trip.end_date, trip.hotel = city, start, end, hotel
    trip.city_lat, trip.city_lng = city_lat, city_lng
    s.add(trip)
    s.commit()
    return trip


def migrate_trip(s: Session, old_id: int, new_id: int) -> bool:
    """Move a trip to a new chat id (group upgraded to supergroup). True if moved.

    Safe to repeat: with no trip under old_id there is nothing to do. A trip that
    already exists under new_id is never overwritten.
    """
    trip = get_trip(s, old_id)
    if trip is None or get_trip(s, new_id) is not None:
        return False
    trip.chat_id = new_id
    s.commit()
    return True


# ---------- sources (posted links) ----------


def add_source(s: Session, trip_id: int, url: str, platform: str, added_by: int) -> Source | None:
    """Save a new link. Returns None if this trip already has it.

    We rely on the unique (trip_id, url) constraint, so even two people
    posting the same link at the same moment can't create two rows.
    """
    source = Source(trip_id=trip_id, url=url, platform=platform, added_by=added_by)
    s.add(source)
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        return None
    return source


def find_source(s: Session, trip_id: int, url: str) -> Source | None:
    """This trip's row for a (normalised) link, if it was posted before."""
    return s.scalar(select(Source).where(Source.trip_id == trip_id, Source.url == url))


def get_source(s: Session, source_id: int) -> Source | None:
    return s.get(Source, source_id)


def set_source(
    s: Session,
    source_id: int,
    *,
    status: str,
    error: str | None = None,
    caption: str | None = None,
) -> None:
    """Update a link's status (and error code / caption when given)."""
    source = s.get(Source, source_id)
    source.status, source.error = status, error
    if caption is not None:
        source.caption = caption
    s.commit()


def mark_interrupted(s: Session) -> list[tuple[int, int]]:
    """At startup: links still mid-pipeline were cut off by a restart.

    Mark them failed ("interrupted") and return (source_id, chat_id) pairs,
    so the bot can offer a Retry button in each chat.
    """
    rows = s.execute(
        select(Source, Trip.chat_id)
        .join(Trip, Trip.id == Source.trip_id)
        .where(Source.status.in_([SourceStatus.pending, SourceStatus.caption]))
    ).all()
    for source, _ in rows:
        source.status, source.error = SourceStatus.failed, "interrupted"
    s.commit()
    return [(source.id, chat_id) for source, chat_id in rows]


def reset_source(s: Session, source_id: int) -> None:
    """Retry button: put a failed link back to the start of the pipeline."""
    set_source(s, source_id, status=SourceStatus.pending)
