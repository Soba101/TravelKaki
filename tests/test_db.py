"""Tests for the database layer (issue #6). Uses the in-memory `sessions` fixture."""

from travelkaki.db import queries
from travelkaki.db.base import make_engine
from travelkaki.db.models import Source, SourceStatus


def test_upsert_trip_updates_and_keeps_id(sessions):
    with sessions() as s:
        first = queries.upsert_trip(s, chat_id=1, city="Tokyo", start=None, end=None, hotel=None)
        second = queries.upsert_trip(s, chat_id=1, city="Osaka", start=None, end=None, hotel=None)
        # Same chat -> same trip row, just updated.
        assert first.id == second.id
        assert queries.get_trip(s, 1).city == "Osaka"


def test_add_source_duplicate_returns_none(sessions):
    with sessions() as s:
        trip = queries.upsert_trip(s, chat_id=1, city="Tokyo", start=None, end=None, hotel=None)
        other = queries.upsert_trip(s, chat_id=2, city="Seoul", start=None, end=None, hotel=None)
        url = "https://www.tiktok.com/@a/video/1"
        assert queries.add_source(s, trip.id, url, "tiktok", added_by=7) is not None
        # Same link in the same trip -> None (duplicate). Must not raise.
        assert queries.add_source(s, trip.id, url, "tiktok", added_by=8) is None
        # Same link in another trip is fine.
        assert queries.add_source(s, other.id, url, "tiktok", added_by=7) is not None


def test_mark_interrupted(sessions):
    with sessions() as s:
        trip = queries.upsert_trip(s, chat_id=42, city="Tokyo", start=None, end=None, hotel=None)
        a = queries.add_source(s, trip.id, "u1", "tiktok", added_by=1)
        b = queries.add_source(s, trip.id, "u2", "tiktok", added_by=1)
        c = queries.add_source(s, trip.id, "u3", "tiktok", added_by=1)
        queries.set_source(s, b.id, status=SourceStatus.caption)
        queries.set_source(s, c.id, status=SourceStatus.done)

        marked = queries.mark_interrupted(s)

        # Only the unfinished ones (pending + caption) are marked, with their chat id.
        assert sorted(marked) == [(a.id, 42), (b.id, 42)]
        assert s.get(Source, a.id).status == SourceStatus.failed
        assert s.get(Source, a.id).error == "interrupted"
        assert s.get(Source, c.id).status == SourceStatus.done


def test_make_engine_creates_sqlite_folder(tmp_path):
    make_engine(f"sqlite:///{tmp_path}/x/y.db")
    assert (tmp_path / "x").is_dir()


def test_vote_toggle(sessions):
    from travelkaki.db import place_queries as pq

    with sessions() as s:
        trip = queries.upsert_trip(s, chat_id=1, city="Tokyo", start=None, end=None, hotel=None)
        place = pq.add_place(s, trip.id, name="Ichiran", category="ramen", video_note="")
        assert pq.vote(s, place.id, 7, "must") == pq.VoteCounts(1, 0, 0)
        assert pq.vote(s, place.id, 7, "must") == pq.VoteCounts(0, 0, 0)  # same tap removes
        assert pq.vote(s, place.id, 7, "skip") == pq.VoteCounts(0, 0, 1)
        assert pq.vote(s, place.id, 8, "must") == pq.VoteCounts(1, 0, 1)  # another person
        assert pq.places_with_counts(s, trip.id) == [(place, pq.VoteCounts(1, 0, 1))]
