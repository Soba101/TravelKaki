"""Database functions for places and votes. Each one commits its own change.

(Split from queries.py to keep files under 200 lines.)
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelkaki.db.models import Confidence, Place, PlaceSource, Vote, VoteValue


@dataclass
class VoteCounts:
    must: int = 0
    maybe: int = 0
    skip: int = 0


def add_place(
    s: Session,
    trip_id: int,
    *,
    name: str,
    category: str,
    video_note: str,
    lat: float | None = None,
    lng: float | None = None,
    address: str | None = None,
    confidence: str = Confidence.none,
    opening_hours: str | None = None,  # M2: None = not checked, "" = checked, none
) -> Place:
    place = Place(
        trip_id=trip_id,
        name=name,
        category=category,
        video_note=video_note,
        lat=lat,
        lng=lng,
        address=address,
        confidence=confidence,
        opening_hours=opening_hours,
    )
    s.add(place)
    s.commit()
    return place


def link_source(s: Session, place_id: int, source_id: int) -> None:
    """Remember that this post mentions this place (skip if already linked)."""
    if s.get(PlaceSource, (place_id, source_id)) is None:
        s.add(PlaceSource(place_id=place_id, source_id=source_id))
        s.commit()


def get_place(s: Session, place_id: int) -> Place | None:
    return s.get(Place, place_id)


def trip_places(s: Session, trip_id: int) -> list[Place]:
    return list(s.scalars(select(Place).where(Place.trip_id == trip_id).order_by(Place.id)))


def vote_counts(s: Session, place_id: int) -> VoteCounts:
    counts = VoteCounts()
    for value in s.scalars(select(Vote.value).where(Vote.place_id == place_id)):
        setattr(counts, value, getattr(counts, value) + 1)
    return counts


def vote(s: Session, place_id: int, user_id: int, value: str) -> VoteCounts:
    """Set this person's vote. Tapping the same button again removes it."""
    value = VoteValue(value)  # raises ValueError for anything else
    existing = s.scalar(select(Vote).where(Vote.place_id == place_id, Vote.tg_user_id == user_id))
    if existing is None:
        s.add(Vote(place_id=place_id, tg_user_id=user_id, value=value))
    elif existing.value == value:
        s.delete(existing)  # same tap again = undo
    else:
        existing.value = value
    s.commit()
    return vote_counts(s, place_id)


def places_with_counts(s: Session, trip_id: int) -> list[tuple[Place, VoteCounts]]:
    return [(p, vote_counts(s, p.id)) for p in trip_places(s, trip_id)]


def clear_pin(s: Session, place_id: int) -> Place | None:
    """'Wrong place' button: forget the map pin."""
    place = s.get(Place, place_id)
    if place is not None:
        place.lat = place.lng = place.address = None
        # "" = checked. Pre-M2 places have NULL hours, which the pin backfill reads
        # as "never geocoded" and would re-pin the place the user just rejected (#54).
        place.opening_hours = ""
        place.confidence = Confidence.none
        s.commit()
    return place
