"""Tests for the ingest pipeline (link -> caption -> LLM -> saved places). Fakes only."""

from sqlalchemy import func, select

from tests.fakes import FakeLlm, caption_fetcher, make_deps, make_source, places_answer
from travelkaki.db import queries
from travelkaki.db.models import Place, PlaceSource
from travelkaki.geo.nominatim import GeoResult
from travelkaki.ingest import pipeline
from travelkaki.llm.client import LlmUnavailable


class FakeGeo:
    """locate() always returns the same pin + confidence."""

    def __init__(self, lat=35.66, lng=139.70, confidence="high"):
        self.answer = (GeoResult(lat, lng, "1-2 Shibuya"), confidence) if lat else (None, "none")

    async def locate(self, name, city, center):
        return self.answer


def _count(sessions, model):
    with sessions() as s:
        return s.scalar(select(func.count()).select_from(model))


async def test_happy_path_saves_places_and_caption(sessions):
    _, source = make_source(sessions)
    deps = make_deps(sessions, FakeLlm(places_answer("Ichiran", "Shibuya Sky")))

    result = await pipeline.run(source.id, deps)

    assert result.error is None
    assert [p.name for p in result.places] == ["Ichiran", "Shibuya Sky"]
    assert result.author == "foodie"
    with sessions() as s:
        saved = queries.get_source(s, source.id)
        assert (saved.status, saved.caption) == ("done", "caption")
    assert _count(sessions, PlaceSource) == 2


async def test_no_caption(sessions):
    _, source = make_source(sessions)
    deps = make_deps(sessions, FakeLlm(), fetch=caption_fetcher(text=None))
    assert (await pipeline.run(source.id, deps)).error == "no_caption"
    with sessions() as s:
        assert (
            queries.get_source(s, source.id).status,
            queries.get_source(s, source.id).error,
        ) == (
            "failed",
            "no_caption",
        )


async def test_llm_unavailable(sessions):
    _, source = make_source(sessions)
    deps = make_deps(sessions, FakeLlm(error=LlmUnavailable()))
    assert (await pipeline.run(source.id, deps)).error == "llm_unavailable"


async def test_cap_reached(sessions):
    _, source = make_source(sessions)
    deps = make_deps(sessions, FakeLlm(places_answer("A")), daily_cap=0)
    assert (await pipeline.run(source.id, deps)).error == "cap_reached"


async def test_no_places(sessions):
    _, source = make_source(sessions)
    deps = make_deps(sessions, FakeLlm(places_answer()))
    assert (await pipeline.run(source.id, deps)).error == "no_places"


async def test_more_than_ten_places(sessions):
    _, source = make_source(sessions)
    names = [f"Place {i}" for i in range(12)]
    result = await pipeline.run(source.id, make_deps(sessions, FakeLlm(places_answer(*names))))
    assert len(result.places) == 10 and result.extra == 2
    assert _count(sessions, Place) == 12  # all saved, only 10 cards


async def test_unexpected_error_is_unknown(sessions):
    _, source = make_source(sessions)

    async def boom(url, platform, http):
        raise RuntimeError("bug")

    result = await pipeline.run(source.id, make_deps(sessions, FakeLlm(), fetch=boom))
    assert result.error == "unknown"
    with sessions() as s:
        assert queries.get_source(s, source.id).status == "failed"


async def test_add_by_name(sessions):
    trip, _ = make_source(sessions)
    result = await pipeline.add_by_name(trip.id, "Ichiran Shibuya", make_deps(sessions))
    assert [p.name for p in result.places] == ["Ichiran Shibuya"]
    assert result.places[0].category == "place"


async def test_geocoded_place_is_saved_with_pin(sessions):
    _, source = make_source(sessions)
    deps = make_deps(sessions, FakeLlm(places_answer("Ichiran")))
    deps.geo = FakeGeo(confidence="low")
    place = (await pipeline.run(source.id, deps)).places[0]
    assert (place.lat, place.lng, place.address, place.confidence) == (
        35.66,
        139.70,
        "1-2 Shibuya",
        "low",
    )


async def test_same_place_from_another_link_is_merged(sessions):
    trip, first = make_source(sessions)
    with sessions() as s:
        second = queries.add_source(s, trip.id, "https://www.tiktok.com/@b/video/2", "tiktok", 8)
    deps = make_deps(sessions, FakeLlm(places_answer("Ichiran Shibuya")))
    deps.geo = FakeGeo()
    await pipeline.run(first.id, deps)
    deps.llm = FakeLlm(places_answer("ichiran, shibuya"))

    result = await pipeline.run(second.id, deps)

    assert result.places == [] and result.merged == ["Ichiran Shibuya"]
    assert _count(sessions, Place) == 1
    assert _count(sessions, PlaceSource) == 2  # one place, linked to both posts


async def test_retry_after_partial_save_makes_no_duplicates(sessions):
    # PR3 review: a crash after some places were saved, then Retry, must not double them.
    _, source = make_source(sessions)
    deps = make_deps(sessions, FakeLlm(places_answer("A", "B")))
    deps.geo = FakeGeo(lat=None)  # unpinned: dedupe by name
    await pipeline.run(source.id, deps)
    await pipeline.run(source.id, deps)
    assert _count(sessions, Place) == 2


async def test_fail_then_retry_succeeds(sessions):
    _, source = make_source(sessions)
    deps = make_deps(sessions, FakeLlm(error=LlmUnavailable()))
    assert (await pipeline.run(source.id, deps)).error == "llm_unavailable"
    with sessions() as s:
        queries.reset_source(s, source.id)  # what the Retry button does
    deps.llm = FakeLlm(places_answer("Ichiran"))
    result = await pipeline.run(source.id, deps)
    assert result.error is None and [p.name for p in result.places] == ["Ichiran"]


async def test_retry_reuses_the_saved_caption(sessions):
    # PR3 review: don't fetch again (Instagram may block a second fetch).
    _, source = make_source(sessions)
    with sessions() as s:
        queries.set_source(
            s, source.id, status="failed", error="llm_unavailable", caption="Ichiran!"
        )
    deps = make_deps(sessions, FakeLlm(places_answer("Ichiran")), fetch=caption_fetcher(text=None))
    assert (await pipeline.run(source.id, deps)).error is None


async def test_only_card_places_are_geocoded(sessions):
    # PR4 review: geocoding is ~1 s per place for everyone. Pin the 10 places that get
    # cards; save the rest unpinned so a 30-place post doesn't take over a minute.
    _, source = make_source(sessions)
    geo = FakeGeo()
    calls = []
    real = geo.locate

    async def counting(name, city, center):
        calls.append(name)
        return await real(name, city, center)

    geo.locate = counting
    deps = make_deps(sessions, FakeLlm(places_answer(*[f"P{i}" for i in range(12)])))
    deps.geo = geo
    result = await pipeline.run(source.id, deps)
    assert len(calls) == 10 and len(result.places) == 10 and result.extra == 2
    with sessions() as s:
        unpinned = [p for p in s.query(Place).all() if p.lat is None]
    assert len(unpinned) == 2
