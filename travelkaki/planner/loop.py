"""The planner agent loop (M2 spec, "Agent loop", issue #16).

The LLM decides its own steps: each round it may call tools (list_places,
build_days, validate, save_plan, ...). Code does the maths and the checks.

Limits: 8 rounds. Each LLM try counts toward the trip's daily cap.
Never silent: if the LLM is down, the cap is hit, or it never saves,
we fall back to the code-only plan (build_days with default priorities).
Every LLM call and tool call is logged as an AgentTrace row.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass

from travelkaki.db import plan_queries as plq
from travelkaki.llm.cap import CapReached, make_counter
from travelkaki.llm.client import LlmUnavailable, ToolCall
from travelkaki.planner.build import build_days
from travelkaki.planner.fit import day_label
from travelkaki.planner.prompt import ASK_TOOL, SYSTEM_PROMPT, TOOLS
from travelkaki.planner.tools import ToolState, run_tool
from travelkaki.planner.types import Issue, Plan, PlanInput
from travelkaki.planner.validate import validate

log = logging.getLogger(__name__)

MAX_ROUNDS = 8
AGENT_TIMEOUT = 240  # seconds of LLM time per run; then the code-only plan (PR2 review #2)
# Poll waits don't count: the clock pauses while the group votes (PR3 review #2).
NUDGE = "Use the tools. Finish with save_plan."


@dataclass
class PlanResult:
    plan: Plan
    issues: list[Issue]
    used_ai: bool  # False = the code-only fallback made this plan
    tradeoffs: str  # the agent's short summary ("" without AI)
    rounds: int  # LLM rounds used


def _text_call(content: str | None) -> ToolCall | None:
    """A tool call the model wrote as text: {"name": ..., "arguments": {...}}.

    Qwen sometimes does this instead of a real tool call (seen in a live run on
    its last round), so we read it rather than throw the plan away.
    """
    text = (content or "").strip()
    text = re.sub(r"</?tool_call>", "", text)  # qwen's own wrapper (PR2 review #11)
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        return None
    args = data.get("arguments", data.get("parameters", {}))
    return ToolCall("text-call", data["name"], args if isinstance(args, str) else json.dumps(args))


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
    rounds, started = 0, time.monotonic()
    while rounds < MAX_ROUNDS and not st.saved:
        # LLM time only: the clock pauses while the group answers a poll.
        llm_seconds = time.monotonic() - started - st.poll_seconds
        try:
            reply = await asyncio.wait_for(
                deps.llm.chat_tools(messages, tools, on_call), AGENT_TIMEOUT - llm_seconds
            )
        except (LlmUnavailable, CapReached, TimeoutError) as e:
            log.warning("planner LLM stopped: %s", type(e).__name__)
            break
        rounds += 1
        calls = [f"{c.name}({c.arguments})" for c in reply.tool_calls]
        trace("llm", None, f"round {rounds}", reply.content or "; ".join(calls), reply.tokens)
        messages.append(reply.message)
        text_call = None if reply.tool_calls else _text_call(reply.content)
        if text_call is not None:  # answer it as a normal message (there's no call id)
            out = await run_tool(text_call.name, text_call.arguments, st)
            trace("tool", text_call.name, text_call.arguments, out)
            messages.append({"role": "user", "content": f"Result of {text_call.name}: {out}"})
            continue
        if not reply.tool_calls:
            messages.append({"role": "user", "content": NUDGE})
            continue
        for call in reply.tool_calls:
            if st.saved:  # calls after save_plan would change the saved plan (review #6)
                out = "ignored: the plan is already saved"
            else:
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
