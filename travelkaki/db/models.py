"""Database tables for M1 (issue #6). See the spec's "Data model" section.

Only trip data is stored: links, the post's public caption, places and votes.
Normal chat messages are never saved.
"""

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from travelkaki.db.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class SourceStatus(StrEnum):
    """Where a link is in the ingest pipeline. ("video" comes in M4.)"""

    pending = "pending"
    caption = "caption"
    done = "done"
    failed = "failed"


class Confidence(StrEnum):
    """How sure we are about a place's map pin (see geo/nominatim.py)."""

    high = "high"  # found inside the trip city area
    low = "low"  # found only by a wider search, but near the city
    far = "far"  # found, but more than 50 km from the city
    none = "none"  # not found / pin removed


class VoteValue(StrEnum):
    must = "must"
    maybe = "maybe"
    skip = "skip"


class Trip(Base):
    """One trip per group chat. /newtrip again updates it."""

    __tablename__ = "trip"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)  # Telegram ids can be large
    city: Mapped[str] = mapped_column(String(100))
    city_lat: Mapped[float | None]
    city_lng: Mapped[float | None]
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    hotel: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=_now)
    # M2: the hotel's map pin, found once when /plan runs. Days start and end here.
    hotel_lat: Mapped[float | None]
    hotel_lng: Mapped[float | None]


class Source(Base):
    """A TikTok/IG link posted in the chat, and its progress through ingest."""

    __tablename__ = "source"
    __table_args__ = (UniqueConstraint("trip_id", "url"),)  # same link twice = duplicate
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trip.id"))
    url: Mapped[str] = mapped_column(String(500))  # normalised URL
    platform: Mapped[str] = mapped_column(String(20))  # "tiktok" or "instagram"
    caption: Mapped[str | None]  # the post's public caption
    status: Mapped[str] = mapped_column(String(20), default=SourceStatus.pending)
    error: Mapped[str | None] = mapped_column(String(50))  # error code when failed
    added_by: Mapped[int] = mapped_column(BigInteger)  # Telegram user id
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Place(Base):
    """A place found in a post (or added by name)."""

    __tablename__ = "place"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trip.id"))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))
    lat: Mapped[float | None]
    lng: Mapped[float | None]
    address: Mapped[str | None]
    video_note: Mapped[str] = mapped_column(default="")  # what the post says about it
    confidence: Mapped[str] = mapped_column(String(10), default=Confidence.none)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    # M2: raw OSM opening hours, e.g. "Mo-Fr 10:00-22:00".
    # None = never checked. "" = checked, but OSM has no hours for it.
    opening_hours: Mapped[str | None]


class PlaceSource(Base):
    """Links a place to every post that mentions it (many-to-many)."""

    __tablename__ = "place_source"
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"), primary_key=True)


class Vote(Base):
    """One person's Must-go / Maybe / Skip on one place."""

    __tablename__ = "vote"
    __table_args__ = (UniqueConstraint("place_id", "tg_user_id"),)  # one vote per person
    id: Mapped[int] = mapped_column(primary_key=True)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"))
    tg_user_id: Mapped[int] = mapped_column(BigInteger)
    value: Mapped[str] = mapped_column(String(10))


class LlmUsage(Base):
    """How many LLM calls a trip made on a given day (for the daily cap)."""

    __tablename__ = "llm_usage"
    trip_id: Mapped[int] = mapped_column(ForeignKey("trip.id"), primary_key=True)
    day: Mapped[date] = mapped_column(primary_key=True)
    calls: Mapped[int] = mapped_column(default=0)


# ---- M2: the planner (spec: docs/superpowers/specs/2026-10-05-m2-planner-agent-design.md) ----


class Itinerary(Base):
    """One saved plan. Each /plan run makes a new version (old ones are kept)."""

    __tablename__ = "itinerary"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trip.id"))
    version: Mapped[int]
    run_id: Mapped[str] = mapped_column(String(36))  # links to the AgentTrace rows
    used_ai: Mapped[bool]  # False = the code-only fallback made it
    tradeoffs: Mapped[str] = mapped_column(default="")  # the agent's short summary
    window: Mapped[str] = mapped_column(String(20))  # "flex" or e.g. "10-22"
    created_at: Mapped[datetime] = mapped_column(default=_now)


class ItineraryItem(Base):
    """One stop in a plan. Times are minutes from midnight (00:30 next day = 1470)."""

    __tablename__ = "itinerary_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    itinerary_id: Mapped[int] = mapped_column(ForeignKey("itinerary.id"))
    day: Mapped[date]
    order: Mapped[int]
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id"))
    start_min: Mapped[int]
    end_min: Mapped[int]
    travel_minutes: Mapped[int]  # travel from the previous stop (or the hotel)


class AgentTrace(Base):
    """One step of a planner run: an LLM call or a tool call. Feeds the M5 eval."""

    __tablename__ = "agent_trace"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trip.id"))
    run_id: Mapped[str] = mapped_column(String(36))  # one uuid per /plan run
    step: Mapped[int]
    kind: Mapped[str] = mapped_column(String(10))  # "llm" or "tool"
    tool: Mapped[str | None] = mapped_column(String(50))
    input: Mapped[str] = mapped_column(default="")
    output: Mapped[str] = mapped_column(default="")
    tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=_now)
