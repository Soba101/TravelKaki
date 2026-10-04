"""OSM opening-hours parser: common forms work, odd forms are 'unknown' (M2 Task 2)."""

import pytest

from travelkaki.planner.hours import is_open, next_open, parse


def test_simple_week():
    hours = parse("Mo-Fr 10:00-22:00; Sa,Su 09:00-23:00")
    assert hours[0] == [(600, 1320)]  # Monday
    assert hours[6] == [(540, 1380)]  # Sunday


def test_24_7():
    hours = parse("24/7")
    assert all(hours[d] == [(0, 1440)] for d in range(7))


def test_no_days_means_every_day():
    assert parse("10:00-18:00")[3] == [(600, 1080)]


def test_mixed_day_list():
    hours = parse("Mo-We,Fr 11:00-20:00")
    assert hours[2] == [(660, 1200)]
    assert hours[3] == []  # Thursday not listed -> closed


def test_past_midnight():
    raw = "Mo-Su 18:00-02:00"
    assert parse(raw)[0] == [(1080, 1560)]
    assert is_open(raw, 1, 60) is True  # Tue 01:00 is still Monday night
    assert is_open(raw, 1, 900) is False  # Tue 15:00


def test_off_overrides():
    raw = "Mo-Su 10:00-20:00; Tu off"
    assert is_open(raw, 1, 720) is False
    assert is_open(raw, 2, 720) is True


def test_split_times():
    raw = "Mo-Fr 11:00-14:00,17:00-22:00"
    assert next_open(raw, 0, 900) == 1020
    assert next_open(raw, 0, 600) == 660
    assert next_open(raw, 0, 1350) is None  # nothing later that day
    assert next_open(raw, 0, 700) == 700  # already open


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "PH off",
        "sunrise-sunset",
        "Jan-Mar Mo-Fr 10:00-18:00",
        "Mo-Fr 10:00+",
        'Mo-Fr 10:00-18:00 "by appointment"',
        "Mo-Fr 10:00-18:00 || Sa 10:00-12:00",
        "garbage",
    ],
)
def test_unknown_forms(raw):
    assert parse(raw) is None
    assert is_open(raw, 0, 720) is None
    assert next_open(raw, 0, 720) is None
