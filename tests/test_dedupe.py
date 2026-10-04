"""Tests for spotting the same place twice (issue #13)."""

from travelkaki.db.models import Place
from travelkaki.ingest.dedupe import find_duplicate, normalise_name

SHIBUYA = (35.6595, 139.7005)


def _place(name, lat=None, lng=None):
    return Place(id=1, trip_id=1, name=name, category="x", lat=lat, lng=lng)


def test_normalise_name():
    assert (
        normalise_name("Ichiran, Shibuya!")
        == normalise_name("ichiran  shibuya")
        == "ichiran shibuya"
    )
    assert normalise_name("一蘭 渋谷") == "一蘭 渋谷"  # non-Latin names keep their letters


def test_find_duplicate():
    saved = [_place("Ichiran Shibuya", *SHIBUYA)]
    near = (SHIBUYA[0] + 0.0004, SHIBUYA[1])  # ~45 m north
    far = (SHIBUYA[0] + 0.0045, SHIBUYA[1])  # ~500 m north
    assert find_duplicate("ichiran, shibuya", *near, saved) is saved[0]
    assert find_duplicate("Ichiran Shibuya", *far, saved) is None
    assert find_duplicate("Butagumi", *SHIBUYA, saved) is None
    assert find_duplicate("Ichiran", None, None, [_place("ICHIRAN")]) is not None  # both unpinned
    assert find_duplicate("Ichiran Shibuya", None, None, saved) is None  # one pinned, one not
