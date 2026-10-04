"""The planner agent loop: rounds, traces, limits, code-only fallback (M2 Task 11)."""

from sqlalchemy import func, select

from tests.fakes import GOOD_RUN, FakeToolLlm, make_deps, tool_reply
from tests.planner_helpers import make_input, place
from travelkaki.db import place_queries as pq
from travelkaki.db import plan_queries as plq
from travelkaki.db import queries
from travelkaki.db.models import AgentTrace, ItineraryItem
from travelkaki.llm.client import LlmUnavailable
from travelkaki.planner.build import build_days
from travelkaki.planner.loop import MAX_ROUNDS, run_planner


def _setup(sessions, llm, cap=100):
    with sessions() as s:
        trip = queries.upsert_trip(s, 1, "Tokyo", None, None, None)
        ids = [pq.add_place(s, trip.id, name=n, category="museum", video_note="").id for n in "ab"]
    inp = make_input([place(ids[0], hours="24/7"), place(ids[1], 35.692, 139.70, hours="24/7")])
    inp.trip_id = trip.id
    return make_deps(sessions, llm=llm, daily_cap=cap), inp


def _traces(sessions):
    with sessions() as s:
        return s.scalar(select(func.count()).select_from(AgentTrace))


async def test_scripted_run_saves(sessions):
    llm = FakeToolLlm(GOOD_RUN)
    deps, inp = _setup(sessions, llm)
    result = await run_planner(deps, inp, "run-1")
    assert result.used_ai and result.rounds == 4
    assert result.tradeoffs == "Everything fits."
    assert not [i for i in result.issues if i.level == "error"]
    assert _traces(sessions) == 8  # 4 LLM calls + 4 tool calls
    messages, tools = llm.seen[-1]
    assert messages[0]["role"] == "system" and "ask_group" not in tools
    assert messages[-1]["role"] == "tool" and messages[-1]["tool_call_id"] == "c0"


async def test_ask_tool_offered_only_with_ask(sessions):
    llm = FakeToolLlm(GOOD_RUN)
    deps, inp = _setup(sessions, llm)

    async def ask(question, options):
        return {}

    await run_planner(deps, inp, "run-1", ask=ask)
    assert "ask_group" in llm.seen[0][1]


async def test_bad_tool_does_not_crash(sessions):
    llm = FakeToolLlm([tool_reply(("teleport", {}))] + GOOD_RUN)
    deps, inp = _setup(sessions, llm)
    result = await run_planner(deps, inp, "run-1")
    assert result.used_ai and result.rounds == 5
    first_tool_answer = llm.seen[1][0][-1]
    assert first_tool_answer["content"].startswith("error: unknown tool")


async def test_eight_rounds_then_fallback(sessions):
    llm = FakeToolLlm([tool_reply(("list_places", {}))] * 20)
    deps, inp = _setup(sessions, llm)
    result = await run_planner(deps, inp, "run-1")
    assert llm.calls == MAX_ROUNDS == 8
    assert not result.used_ai and result.tradeoffs == ""
    assert result.plan == build_days(inp)


async def test_llm_down_fallback(sessions):
    deps, inp = _setup(sessions, FakeToolLlm([LlmUnavailable()]))
    result = await run_planner(deps, inp, "run-1")
    assert not result.used_ai and result.plan == build_days(inp)


async def test_cap_reached_fallback(sessions):
    llm = FakeToolLlm(GOOD_RUN)
    deps, inp = _setup(sessions, llm, cap=0)
    result = await run_planner(deps, inp, "run-1")
    assert not result.used_ai and llm.calls == 0


async def test_text_only_reply_nudges(sessions):
    llm = FakeToolLlm([tool_reply(text="Here is your plan!")] + GOOD_RUN)
    deps, inp = _setup(sessions, llm)
    result = await run_planner(deps, inp, "run-1")
    assert result.used_ai
    assert "save_plan" in llm.seen[1][0][-1]["content"]  # the nudge


async def test_no_llm_configured_uses_code(sessions):
    deps, inp = _setup(sessions, None)
    assert not (await run_planner(deps, inp, "run-1")).used_ai


def test_versions_increase(sessions):
    deps, inp = _setup(sessions, None)
    plan = build_days(inp)
    with sessions() as s:
        first = plq.save_itinerary(s, inp.trip_id, "r1", plan, used_ai=True, tradeoffs="x",
                                   window="flex")  # fmt: skip
        second = plq.save_itinerary(s, inp.trip_id, "r2", plan, used_ai=False, tradeoffs="",
                                    window="10-22")  # fmt: skip
        items = s.scalar(select(func.count()).select_from(ItineraryItem))
    assert (first.version, second.version) == (1, 2)
    assert items == 2 * sum(len(d.stops) for d in plan.days)


async def test_tool_call_written_as_text_is_used(sessions):
    """Live run: qwen wrote save_plan as JSON text instead of a tool call on its last
    round. We read it as a real call, so the agent's plan isn't thrown away."""
    text_call = '{"name": "save_plan", "arguments": {"tradeoffs": "Fits well."}}'
    llm = FakeToolLlm(GOOD_RUN[:3] + [tool_reply(text=text_call)])
    deps, inp = _setup(sessions, llm)
    result = await run_planner(deps, inp, "run-1")
    assert result.used_ai and result.tradeoffs == "Fits well."
