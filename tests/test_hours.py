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


def test_spaces_after_commas():
    """Real OSM data (Tokyo National Museum) puts spaces after commas."""
    hours = parse("Mo, We-Th 09:30-17:00; Fr-Su 09:30-20:00")
    assert hours[0] == [(570, 1020)] and hours[1] == [] and hours[4] == [(570, 1200)]
    assert parse("Mo-Fr 11:00-14:00, 17:00-22:00")[0] == [(660, 840), (1020, 1320)]


def test_open_past_midnight_for_24_7_and_24_00():
    """Review #5: a 24/7 place is open at 00:10 the next morning (minute 1450)."""
    assert is_open("24/7", 0, 1450) is True
    assert is_open("Mo-Su 00:00-24:00", 0, 1450) is True


def test_open_through_respects_breaks():
    """Review #12: a visit across a lunch break is not 'open'."""
    from travelkaki.planner.hours import open_through

    raw = "Mo-Su 10:00-14:00,14:30-20:00"
    assert open_through(raw, 0, 780, 900) is False  # 13:00-15:00 crosses the break
    assert open_through(raw, 0, 900, 1000) is True
    assert open_through("24/7", 0, 1380, 1500) is True  # 23:00-01:00
    assert open_through("Mo-Su 18:00-02:00", 0, 1400, 1500) is True
    assert open_through(None, 0, 600, 700) is None
