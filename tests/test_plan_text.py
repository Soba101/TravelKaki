"""The /plan message: day blocks, route links, trade-offs, splitting (M2 Task 12)."""

from dataclasses import replace
from urllib.parse import parse_qs, urlparse

from tests.planner_helpers import TUE, make_input, place
from travelkaki.bot.plan_text import duration, format_plan, route_links
from travelkaki.planner.loop import PlanResult
from travelkaki.planner.types import Day, Dropped, Plan, Stop

BASE = (35.69, 139.70)


def _result(plan, used_ai=True, tradeoffs="Skipped the zoo."):
    return PlanResult(plan, [], used_ai, tradeoffs, 3)


def test_duration():
    assert [duration(m) for m in (45, 60, 90, 120)] == ["45 min", "1 h", "1 h 30", "2 h"]


def test_route_link_shape():
    [link] = route_links(BASE, [(35.7, 139.71), (35.71, 139.72)])
    q = parse_qs(urlparse(link).query)
    assert link.startswith("https://www.google.com/maps/dir/?api=1")
    assert q["origin"] == ["35.69,139.7"] and q["destination"] == ["35.69,139.7"]
    assert q["waypoints"] == ["35.7,139.71|35.71,139.72"]


def test_long_day_gets_two_links():
    """Review Focus 5: Google allows 9 waypoints per link."""
    points = [(35.0 + i / 100, 139.0) for i in range(12)]
    links = route_links(BASE, points)
    assert len(links) == 2
    for link in links:
        assert len(parse_qs(urlparse(link).query)["waypoints"][0].split("|")) <= 9


def test_message_layout_and_escaping():
    """Review Focus 1: names with <, & and emoji are escaped."""
    p = replace(place(1, hours="24/7"), name="A<b>&🍜")
    q = place(2, 35.70, 139.70, hours=None)
    inp = make_input([p, q], days=2)
    inp.dropped = [Dropped(9, "Ramen <Afro>", "no map pin")]
    plan = Plan(
        [Day(TUE, [Stop(1, 570, 690, 5, "walk"), Stop(2, 1440, 1500, 75, "express")]), Day(TUE)],
        [Dropped(3, "Zoo", "no time left on Day 2")],
    )
    [text] = format_plan(inp, _result(plan), version=2)
    assert "A&lt;b&gt;&amp;🍜" in text and "<b>&" not in text
    assert "v2" in text and "Day 1 · Tue 15 Dec" in text
    assert "09:30" in text and "00:00" in text  # 1440 wraps
    assert "🚆" in text and "express train" in text
    assert "Free day" in text
    assert "Day 1 route" in text
    assert "Ramen &lt;Afro&gt; (no map pin)" in text and "Zoo (no time left on Day 2)" in text
    assert "Trade-offs: Skipped the zoo." in text
    assert "Hours unknown for 1 place" in text
    assert "without AI" not in text


def test_without_ai_footer():
    inp = make_input([place(1, hours="24/7")], days=1)
    plan = Plan([Day(TUE, [Stop(1, 600, 720, 5, "walk")])])
    [text] = format_plan(inp, _result(plan, used_ai=False, tradeoffs=""), version=1)
    assert "Planned without AI" in text and "Trade-offs" not in text


def test_long_plan_is_split():
    places = [replace(place(i, hours="24/7"), name="X" * 90) for i in range(1, 40)]
    inp = make_input(places, days=14)
    days = [Day(TUE, [Stop(i, 600, 660, 5, "walk") for i in range(1, 40)]) for _ in range(14)]
    parts = format_plan(inp, _result(Plan(days)), version=1)
    assert len(parts) > 1 and all(len(p) <= 4096 for p in parts)


def test_long_not_planned_list_is_shortened():
    """PR2 review #4: hundreds of unpinned extras must not break the message."""
    inp = make_input([place(1, hours="24/7")], days=1)
    inp.dropped = [Dropped(100 + i, "Tom & Jerry's", "no map pin") for i in range(200)]
    plan = Plan([Day(TUE, [Stop(1, 600, 720, 5, "walk")])])
    parts = format_plan(inp, _result(plan), version=1)
    text = "\n".join(parts)
    assert "and 190 more" in text and all(len(p) <= 4096 for p in parts)
    assert "Trade-offs" in text
