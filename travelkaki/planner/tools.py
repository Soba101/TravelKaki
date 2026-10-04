"""Run the planner's tools (M2 spec, "Agent loop", issue #17).

run_tool() never raises. Whatever the model sends, it gets back a short text
answer, or "error: ..." it can read and fix. (A 4B model sends odd things:
ids as strings, lists instead of objects, made-up tools.)
"""

import json
import re
from dataclasses import dataclass, field

from travelkaki.planner.build import build_days
from travelkaki.planner.fit import day_label, hhmm
from travelkaki.planner.hours import is_open, parse
from travelkaki.planner.travel import estimate
from travelkaki.planner.types import Issue, Plan, PlanInput, Priorities
from travelkaki.planner.validate import savable, validate

MAX_TRADEOFF_CHARS = 400


class ToolError(Exception):
    """A bad call. The message goes back to the model as 'error: ...'."""


@dataclass
class ToolState:
    """What the agent has done so far in one /plan run."""

    inp: PlanInput
    draft: Plan | None = None  # the last build_days result
    issues: list[Issue] = field(default_factory=list)
    saved: bool = False
    tradeoffs: str = ""
    polls: int = 0  # ask_group calls so far
    ask: object = None  # async (question, options) -> {option: votes}; set in PR3


def _int(value, what: str) -> int:
    """Accept 3 or "3". Anything else is a ToolError."""
    if isinstance(value, bool) or not (isinstance(value, int) or str(value).strip().isdigit()):
        raise ToolError(f"{what} must be a number")
    return int(value)


def _place(st: ToolState, value):
    p = st.inp.place(_int(value, "place_id"))
    if p is None:
        raise ToolError(f"no place with id {value}")
    return p


def _day(st: ToolState, value) -> int:
    day = _int(value, "day")
    if not 1 <= day <= len(st.inp.dates):
        raise ToolError(f"day must be 1 to {len(st.inp.dates)}")
    return day


def plan_summary(plan: Plan, inp: PlanInput) -> str:
    """Short text form of a plan for the model: one line per day + dropped places."""
    names = {p.id: p.name for p in inp.places}
    lines = []
    for n, day in enumerate(plan.days, start=1):
        stops = ", ".join(f"{names.get(s.place_id, s.place_id)} {hhmm(s.start)}" for s in day.stops)
        lines.append(f"Day {n} ({day_label(day.date)}): {stops or 'free day'}")
    if plan.dropped:
        lines.append("Dropped: " + "; ".join(f"{d.name} ({d.reason})" for d in plan.dropped))
    return "\n".join(lines)


def _list_places(st: ToolState, args: dict) -> str:
    lines = [f"Trip: {st.inp.city}, {len(st.inp.dates)} days from {day_label(st.inp.dates[0])}"]
    for p in st.inp.places:
        hours = "hours known" if parse(p.hours) else "hours unknown"
        lines.append(f"id {p.id} | {p.name} | {p.category} | {p.tier} "
                     f"({p.must} must, {p.maybe} maybe) | {hours}")  # fmt: skip
    for d in st.inp.dropped:
        lines.append(f"not plannable: {d.name} ({d.reason})")
    return "\n".join(lines)


def _details(st: ToolState, args: dict) -> str:
    p = _place(st, args.get("place_id"))
    return f"{p.name}: {p.address or 'no address'} | hours: {p.hours or 'unknown'} | {p.note}"


def _travel(st: ToolState, args: dict) -> str:
    a, b = _place(st, args.get("from_id")), _place(st, args.get("to_id"))
    minutes, mode = estimate(a.point, b.point)
    return f"{minutes} min by {mode}"


def _check_open(st: ToolState, args: dict) -> str:
    p, day = _place(st, args.get("place_id")), _day(st, args.get("day"))
    match = re.fullmatch(r"(\d{1,2}):(\d\d)", str(args.get("time", "")).strip())
    if not match:
        raise ToolError("time must look like 14:00")
    minute = int(match[1]) * 60 + int(match[2])
    answer = is_open(p.hours, st.inp.dates[day - 1].weekday(), minute)
    return {True: "open", False: "closed", None: "unknown"}[answer]


def _pins(raw) -> dict[int, int]:
    """{"3": 2} or [{"place_id": 3, "day": 2}] -> {3: 2}."""
    if isinstance(raw, dict):
        return {_int(k, "place_id"): _int(v, "day") for k, v in raw.items()}
    if isinstance(raw, list):
        return {_int(x.get("place_id"), "place_id"): _int(x.get("day"), "day") for x in raw
                if isinstance(x, dict)}  # fmt: skip
    raise ToolError("pins must be a list of {place_id, day}")


def _build(st: ToolState, args: dict) -> str:
    ids = lambda key: [_int(v, key) for v in (args.get(key) or [])]  # noqa: E731
    pr = Priorities(
        include=ids("include"), exclude=ids("exclude"), pins=_pins(args.get("pins") or {})
    )
    st.draft, st.issues = build_days(st.inp, pr), []
    return plan_summary(st.draft, st.inp)


def _validate(st: ToolState, args: dict) -> str:
    if st.draft is None:
        raise ToolError("call build_days first")
    st.issues = validate(st.draft, st.inp)
    # Must-gos that build_days left out (with a reason) are NOT errors you must fix.
    # Saying "error" + "savable: yes" made the small model loop in a live run,
    # so they're shown as "left out", with a hint for the one fix that can help.
    dropped = {d.place_id: d for d in st.draft.dropped}
    lines = []
    for i in st.issues:
        if i.code == "missing_must" and i.place_id in dropped:
            d = dropped[i.place_id]
            hint = " - pin it to another day, or accept it" if "closed" in d.reason else ""
            lines.append(f"left out: {d.name} ({d.reason}){hint}")
        else:
            lines.append(f"{i.level} {i.code}: {i.text}")
    if savable(st.draft, st.issues):
        lines.append("savable: yes. Call save_plan now.")
    else:
        lines.append("savable: no. Fix the errors with build_days.")
    return "\n".join(lines or ["no issues"])


def _save(st: ToolState, args: dict) -> str:
    if st.draft is None:
        raise ToolError("call build_days first")
    issues = validate(st.draft, st.inp)
    if not savable(st.draft, issues):
        codes = sorted({i.code for i in issues if i.level == "error"})
        return "error: fix or exclude first: " + ", ".join(codes)
    sentences = re.split(r"(?<=[.!?])\s+", str(args.get("tradeoffs", "")).strip())
    st.tradeoffs = " ".join(sentences[:3])[:MAX_TRADEOFF_CHARS]
    st.saved = True
    return "saved"


async def _ask(st: ToolState, args: dict) -> str:
    """Group polls arrive in PR3 (#20). Until then the tool isn't offered."""
    raise ToolError("ask_group is not available")


SYNC_TOOLS = {
    "list_places": _list_places,
    "get_place_details": _details,
    "estimate_travel": _travel,
    "check_open": _check_open,
    "build_days": _build,
    "validate": _validate,
    "save_plan": _save,
}


async def run_tool(name: str, raw_args: str, st: ToolState) -> str:
    """Run one tool call and return its text answer. Never raises."""
    try:
        args = json.loads(raw_args or "{}")
        if not isinstance(args, dict):
            raise ToolError("arguments must be a JSON object")
        if name == "ask_group":
            return await _ask(st, args)
        if name not in SYNC_TOOLS:
            raise ToolError(f"unknown tool {name}")
        return SYNC_TOOLS[name](st, args)
    except (ToolError, ValueError, TypeError, AttributeError) as e:
        return f"error: {e}"
