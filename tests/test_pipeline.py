"""Tests for the ingest pipeline (link -> caption -> LLM -> saved places). Fakes only."""

from sqlalchemy import func, select

from tests.fakes import FakeLlm, caption_fetcher, make_deps, make_source, places_answer
from travelkaki.db import queries
from travelkaki.db.models import Place, PlaceSource
from travelkaki.ingest import pipeline
from travelkaki.llm.client import LlmUnavailable


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
