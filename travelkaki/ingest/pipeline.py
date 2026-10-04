"""The ingest workflow: a posted link becomes saved places (issues #10, #15).

Fixed steps, not an agent:
    caption -> LLM extract -> save places
(Normalising the URL happens earlier, in the bot, because the duplicate check
needs the canonical URL. Geocoding and dedupe are added in PR4.)

Every outside call comes from `deps`, so tests run with fakes.
Every failure sets the link to "failed" with an error code; the bot turns the
code into a message telling the user what to do next.
"""

import logging
from dataclasses import dataclass, field

from travelkaki.db import place_queries as pq
from travelkaki.db import queries
from travelkaki.db.models import Place, SourceStatus, Trip
from travelkaki.deps import Deps
from travelkaki.ingest.extract import ExtractedPlace, extract_places
from travelkaki.llm.cap import CapReached, make_counter
from travelkaki.llm.client import LlmUnavailable

log = logging.getLogger(__name__)

# Error codes (the bot has a message for each one, see bot/cards.py ERRORS).
NO_CAPTION = "no_caption"
LLM_UNAVAILABLE = "llm_unavailable"
CAP_REACHED = "cap_reached"
NO_PLACES = "no_places"
UNKNOWN = "unknown"

MAX_CARDS = 10  # cards posted per link; the rest are saved and shown in /places


@dataclass
class PipelineResult:
    places: list[Place] = field(default_factory=list)  # new places to post cards for
    merged: list[str] = field(default_factory=list)  # names merged into saved places
    extra: int = 0  # saved but not shown as cards (over MAX_CARDS)
    error: str | None = None  # error code, None = success
    author: str | None = None  # the post's creator


def _fail(deps: Deps, source_id: int, code: str) -> PipelineResult:
    with deps.sessions() as s:
        queries.set_source(s, source_id, status=SourceStatus.failed, error=code)
    return PipelineResult(error=code)


async def _save(trip: Trip, ex: ExtractedPlace, source_id: int | None, deps: Deps) -> Place | str:
    """Save one place. Returns the new Place (or, from PR4, the name it merged into)."""
    with deps.sessions() as s:
        place = pq.add_place(
            s, trip.id, name=ex.name, category=ex.category or "place", video_note=ex.video_note
        )
        if source_id is not None:
            pq.link_source(s, place.id, source_id)
    return place


async def _save_all(trip, extracted, source_id, deps, result: PipelineResult) -> None:
    for ex in extracted:
        saved = await _save(trip, ex, source_id, deps)
        if isinstance(saved, str):
            result.merged.append(saved)
        elif len(result.places) < MAX_CARDS:
            result.places.append(saved)
        else:
            result.extra += 1


async def _run(source_id: int, deps: Deps) -> PipelineResult:
    with deps.sessions() as s:
        source = queries.get_source(s, source_id)
        trip = s.get(Trip, source.trip_id)
        queries.set_source(s, source_id, status=SourceStatus.caption)

    caption = await deps.fetch_caption(source.url, source.platform, deps.http)
    if caption is None:
        return _fail(deps, source_id, NO_CAPTION)
    with deps.sessions() as s:  # keep the caption (for Retry and the M5 evals)
        queries.set_source(s, source_id, status=SourceStatus.caption, caption=caption.text)

    on_call = make_counter(deps.sessions, trip.id, deps.daily_cap)
    try:
        extracted = await extract_places(deps.llm, trip.city, caption.text, on_call)
    except CapReached:
        return _fail(deps, source_id, CAP_REACHED)
    except LlmUnavailable:
        return _fail(deps, source_id, LLM_UNAVAILABLE)
    if not extracted:
        return _fail(deps, source_id, NO_PLACES)

    result = PipelineResult(author=caption.author)
    await _save_all(trip, extracted, source_id, deps, result)
    with deps.sessions() as s:
        queries.set_source(s, source_id, status=SourceStatus.done)
    return result


async def run(source_id: int, deps: Deps) -> PipelineResult:
    """Run every step for one saved link. Never raises: errors become a result code."""
    try:
        return await _run(source_id, deps)
    except Exception:
        log.exception("pipeline failed for source %s", source_id)  # traceback, no message text
        return _fail(deps, source_id, UNKNOWN)


async def add_by_name(trip_id: int, name: str, deps: Deps) -> PipelineResult:
    """Text add ("@bot add Ichiran"): skip caption + LLM, save the place directly."""
    with deps.sessions() as s:
        trip = s.get(Trip, trip_id)
    result = PipelineResult()
    ex = ExtractedPlace(name=name.strip()[:100], category="place")
    await _save_all(trip, [ex], None, deps, result)
    return result
