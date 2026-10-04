"""The planner agent loop (M2 spec, "Agent loop", issue #16).

The LLM decides its own steps: each round it may call tools (list_places,
build_days, validate, save_plan, ...). Code does the maths and the checks.

Limits: 8 rounds. Each LLM try counts toward the trip's daily cap.
Never silent: if the LLM is down, the cap is hit, or it never saves,
we fall back to the code-only plan (build_days with default priorities).
Every LLM call and tool call is logged as an AgentTrace row.
"""

import json
import logging
from dataclasses import dataclass

from travelkaki.db import plan_queries as plq
from travelkaki.llm.cap import CapReached, make_counter
from travelkaki.llm.client import LlmUnavailable
from travelkaki.planner.build import build_days
from travelkaki.planner.fit import day_label
from travelkaki.planner.prompt import ASK_TOOL, SYSTEM_PROMPT, TOOLS
from travelkaki.planner.tools import ToolState, run_tool
from travelkaki.planner.types import Issue, Plan, PlanInput
from travelkaki.planner.validate import validate

log = logging.getLogger(__name__)

MAX_ROUNDS = 8
NUDGE = "Use the tools. Finish with save_plan."


@dataclass
class PlanResult:
    plan: Plan
    issues: list[Issue]
    used_ai: bool  # False = the code-only fallback made this plan
    tradeoffs: str  # the agent's short summary ("" without AI)
    rounds: int  # LLM rounds used


class _Tracer:
    """Writes numbered AgentTrace rows for one run."""

    def __init__(self, deps, trip_id: int, run_id: str):
        self.deps, self.trip_id, self.run_id, self.step = deps, trip_id, run_id, 0

    def __call__(self, kind: str, tool: str | None, input: str, output: str, tokens: int = 0):
        self.step += 1
        with self.deps.sessions() as s:
            plq.add_trace(
                s, self.trip_id, self.run_id, self.step, kind, tool, input, output, tokens
            )


def _first_message(inp: PlanInput) -> str:
    first, last = day_label(inp.dates[0]), day_label(inp.dates[-1])
    return f"Plan this trip: {inp.city}, {len(inp.dates)} days ({first} to {last})."


async def _agent(deps, inp: PlanInput, st: ToolState, trace: _Tracer, tools: list) -> int:
    """Run LLM rounds until save_plan or a limit. Returns rounds used."""
    on_call = make_counter(deps.sessions, inp.trip_id, deps.daily_cap)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _first_message(inp)},
    ]
    rounds = 0
    while rounds < MAX_ROUNDS and not st.saved:
        try:
            reply = await deps.llm.chat_tools(messages, tools, on_call)
        except (LlmUnavailable, CapReached) as e:
            log.warning("planner LLM stopped: %s", type(e).__name__)
            break
        rounds += 1
        calls = [f"{c.name}({c.arguments})" for c in reply.tool_calls]
        trace("llm", None, f"round {rounds}", reply.content or "; ".join(calls), reply.tokens)
        messages.append(reply.message)
        if not reply.tool_calls:
            messages.append({"role": "user", "content": NUDGE})
            continue
        for call in reply.tool_calls:
            out = await run_tool(call.name, call.arguments, st)
            trace("tool", call.name, call.arguments, out)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": out}
            )
    return rounds


async def run_planner(deps, inp: PlanInput, run_id: str, ask=None) -> PlanResult:
    """Plan the trip with the agent, or with code only if the agent can't finish."""
    st = ToolState(inp, ask=ask)
    tools = TOOLS + ([ASK_TOOL] if ask is not None else [])
    trace = _Tracer(deps, inp.trip_id, run_id)
    rounds = await _agent(deps, inp, st, trace, tools) if deps.llm is not None else 0
    if st.saved:
        plan, used_ai, tradeoffs = st.draft, True, st.tradeoffs
    else:
        plan, used_ai, tradeoffs = build_days(inp), False, ""
        trace("tool", "fallback", "{}", json.dumps({"reason": "agent did not save"}))
    return PlanResult(plan, validate(plan, inp), used_ai, tradeoffs, rounds)
