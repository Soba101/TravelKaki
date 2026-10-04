"""Planner tools: what the LLM can call, and how bad calls are handled (M2 Task 10)."""

import json

from tests.planner_helpers import make_input, place
from travelkaki.planner.prompt import ASK_TOOL, SYSTEM_PROMPT, TOOLS, plan_summary
from travelkaki.planner.tools import ToolState, run_tool


def _state():
    places = [
        place(1, hours="Mo-Su 10:00-18:00; Tu off"),
        place(2, 35.692, 139.70, tier="maybe", category="ramen", hours=None),
    ]
    return ToolState(make_input(places, days=2))  # Tue 15 + Wed 16 Dec


def test_schemas_name_every_tool():
    names = [t["function"]["name"] for t in TOOLS]
    assert names == ["list_places", "get_place_details", "estimate_travel", "check_open",
                     "build_days", "validate", "save_plan"]  # fmt: skip
    assert ASK_TOOL["function"]["name"] == "ask_group"
    assert "save_plan" in SYSTEM_PROMPT


async def test_list_places_shows_tiers_and_votes():
    out = await run_tool("list_places", "{}", _state())
    assert "id 1" in out and "must" in out and "maybe" in out
    assert "hours unknown" in out  # place 2


async def test_check_open():
    st = _state()
    assert (
        await run_tool("check_open", '{"place_id": 1, "day": 1, "time": "12:00"}', st) == "closed"
    )
    assert await run_tool("check_open", '{"place_id": 1, "day": 2, "time": "12:00"}', st) == "open"
    assert (
        await run_tool("check_open", '{"place_id": 2, "day": 1, "time": "12:00"}', st) == "unknown"
    )


async def test_estimate_travel_and_details():
    st = _state()
    assert "min" in await run_tool("estimate_travel", '{"from_id": 1, "to_id": 2}', st)
    assert "Mo-Su 10:00-18:00" in await run_tool("get_place_details", '{"place_id": "1"}', st)


async def test_build_validate_save_flow():
    st = _state()
    summary = await run_tool("build_days", "{}", st)
    assert st.draft is not None and "Day 1 (Tue 15 Dec)" in summary
    assert "Place 1" in summary  # planned on Wed
    report = await run_tool("validate", "{}", st)
    assert "savable: yes" in report
    out = await run_tool("save_plan", json.dumps({"tradeoffs": "All good. Ramen on day 2."}), st)
    assert out == "saved" and st.saved and st.tradeoffs == "All good. Ramen on day 2."


async def test_build_days_args_with_string_ids_and_pin_list():
    st = _state()
    await run_tool("build_days", '{"exclude": ["2"], "pins": {"1": 2}}', st)
    assert [x.place_id for x in st.draft.dropped] == [2]
    await run_tool("build_days", '{"pins": [{"place_id": 1, "day": 2}]}', st)
    assert st.draft.days[1].stops[0].place_id == 1


async def test_save_before_build_is_an_error():
    st = _state()
    assert (await run_tool("save_plan", '{"tradeoffs": "x"}', st)).startswith("error")
    assert not st.saved


async def test_save_refuses_errors():
    st = _state()
    await run_tool("build_days", "{}", st)
    stop = next(s for d in st.draft.days for s in d.stops if s.place_id == 1)
    stop.start, stop.end = 0, 60  # break it: place 1 is closed at 00:00
    out = await run_tool("save_plan", '{"tradeoffs": "x"}', st)
    assert out.startswith("error: fix or exclude first")


async def test_tradeoffs_are_cut():
    st = _state()
    await run_tool("build_days", "{}", st)
    long = "One. Two. Three. Four. Five." + " x" * 400
    await run_tool("save_plan", json.dumps({"tradeoffs": long}), st)
    assert st.tradeoffs == "One. Two. Three."


async def test_bad_calls_never_raise():
    """Review Focus 3: a small model sends odd arguments."""
    st = _state()
    assert (await run_tool("estimate_travel", '{"from_id":"1","to_id":999}', st)).startswith(
        "error"
    )
    assert (await run_tool("nope", "{}", st)).startswith("error")
    assert (await run_tool("build_days", "[1,2]", st)).startswith("error")
    assert (await run_tool("check_open", "not json", st)).startswith("error")
    assert (await run_tool("check_open", '{"place_id": 1, "day": 9, "time": "x"}', st)).startswith(
        "error"
    )
    assert (await run_tool("get_place_details", '{"place_id": "abc"}', st)).startswith("error")
    assert (await run_tool("ask_group", '{"question": "?", "options": ["a","b"]}', st)).startswith(
        "error"
    )


def test_plan_summary_lists_dropped():
    from travelkaki.planner.build import build_days

    st = _state()
    plan = build_days(st.inp)
    assert "Day 2 (Wed 16 Dec)" in plan_summary(plan, st.inp)


async def test_validate_wording_for_left_out_must_go():
    """Live run: 'error missing_must' + 'savable: yes' confused the 4B model into
    looping. A dropped Must-go is shown as 'left out', with a hint, and a savable
    draft says to call save_plan now."""
    st = ToolState(make_input([place(1, hours="Mo 10:00-18:00")], days=2))  # closed Tue + Wed
    await run_tool("build_days", "{}", st)
    report = await run_tool("validate", "{}", st)
    assert "error missing_must" not in report
    assert "left out: Place 1 (closed on Tue 15 Dec)" in report
    assert "pin it to another day" in report
    assert report.endswith("savable: yes. Call save_plan now.")
