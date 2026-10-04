"""Tests for /newtrip (issue #7): parsing the text, and the handler saving the trip."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from travelkaki.bot.trip import NewTrip, TripParseError, newtrip, parse_newtrip
from travelkaki.db import queries
from travelkaki.deps import Deps

TODAY = date(2026, 10, 4)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Tokyo 12-15 Dec", NewTrip("Tokyo", date(2026, 12, 12), date(2026, 12, 15), None)),
        ("Tokyo 12 Dec - 3 Jan", NewTrip("Tokyo", date(2026, 12, 12), date(2027, 1, 3), None)),
        (
            "New York 3-7 Jan hotel The Plaza",
            NewTrip("New York", date(2027, 1, 3), date(2027, 1, 7), "The Plaza"),
        ),
        ("Seoul 5 Mar", NewTrip("Seoul", date(2027, 3, 5), date(2027, 3, 5), None)),
        ("Kyoto", NewTrip("Kyoto", None, None, None)),
        (
            "Bangkok 20 december to 2 january",
            NewTrip("Bangkok", date(2026, 12, 20), date(2027, 1, 2), None),
        ),
        ("Osaka hotel Cross Hotel", NewTrip("Osaka", None, None, "Cross Hotel")),
    ],
)
def test_parse_newtrip(text, expected):
    assert parse_newtrip(text, TODAY) == expected


def test_parse_end_before_start_is_error():
    with pytest.raises(TripParseError, match="before"):
        parse_newtrip("Osaka 15-12 Dec", TODAY)


def test_parse_empty_shows_usage():
    with pytest.raises(TripParseError, match="/newtrip Tokyo 12-15 Dec"):
        parse_newtrip("   ", TODAY)


def _fake(args, sessions):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_message=message)
    context = SimpleNamespace(args=args, bot_data={"deps": Deps(sessions=sessions)})
    return update, context, message


async def test_newtrip_saves_trip_and_replies(sessions):
    update, context, message = _fake(["Tokyo", "12-15", "Dec"], sessions)
    await newtrip(update, context)
    with sessions() as s:
        trip = queries.get_trip(s, 1)
    assert trip.city == "Tokyo"
    # The handler uses the real date, so only check day + month (the year depends on today).
    assert (trip.start_date.day, trip.start_date.month) == (12, 12)
    assert "Tokyo" in message.reply_text.await_args.args[0]


async def test_newtrip_bad_input_replies_error(sessions):
    update, context, message = _fake(["Osaka", "15-12", "Dec"], sessions)
    await newtrip(update, context)
    assert "before" in message.reply_text.await_args.args[0]
    with sessions() as s:
        assert queries.get_trip(s, 1) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A typed year is used. (PR1 review)
        ("Tokyo 12-15 Dec 2027", NewTrip("Tokyo", date(2027, 12, 12), date(2027, 12, 15), None)),
        # A trip already under way (ends today or later) stays in this year.
        ("Tokyo 3-7 Oct", NewTrip("Tokyo", date(2026, 10, 3), date(2026, 10, 7), None)),
    ],
)
def test_parse_year_rules(text, expected):
    assert parse_newtrip(text, TODAY) == expected


@pytest.mark.parametrize(
    "text", ["Tokyo Dec 12-15", "Tokyo 12/12-15/12", "Tokyo 31 Feb", "Tokyo 12 Foo"]
)
def test_parse_unreadable_dates_are_errors(text):
    # Never save a city like "Tokyo Dec 12-15" or a wrong date silently.
    with pytest.raises(TripParseError):
        parse_newtrip(text, TODAY)
