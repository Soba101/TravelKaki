"""The planner agent's instructions and tool list (M2 spec, "Agent loop").

Kept short and plain: a small local model (qwen3 4B) reads this every round.
Tool arguments are tiny on purpose (ids and day numbers), so the model can't
get lost in big JSON.
"""

from travelkaki.planner.fit import day_label, hhmm
from travelkaki.planner.types import Plan, PlanInput

SYSTEM_PROMPT = """You plan a group trip, day by day, using tools.

Goal: a plan with every Must-go place in it, if that is possible.
Code does the maths. You decide what to include and explain the trade-offs.

Steps:
1. Call list_places. (Don't call get_place_details for every place: only if you
   really need one detail. Rounds are limited.)
2. Call build_days (no arguments first). It returns a draft plan.
3. Call validate. If it lists errors, try again with build_days, for example:
   pin a place to a day where it is open, or exclude a Maybe to make room.
4. When validate says "savable: yes", call save_plan with 1-3 short, plain
   sentences about the trade-offs (what was left out and why).

Rules:
- Never include places voted Skip (they are not in the list).
- Must-go places matter most. Maybe places only if there is time.
- If two Must-go places compete and no plan fits both, you may ask the group
  with ask_group (if you have it). Ask at most twice. Then call build_days again
  with the group's choice (exclude the place that lost), validate and save.
- You have at most 8 rounds. Always finish with save_plan, as a real tool call."""


def _fn(name: str, description: str, properties: dict | None = None, required=()) -> dict:
    """One OpenAI-style tool schema."""
    params = {"type": "object", "properties": properties or {}, "required": list(required)}
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": params},
    }


_ID = {"type": "integer"}
_IDS = {"type": "array", "items": {"type": "integer"}}

TOOLS = [
    _fn("list_places", "Saved places: id, name, category, Must-go/Maybe, votes, hours known."),
    _fn("get_place_details", "Address, opening hours and notes for one place.",
        {"place_id": _ID}, ["place_id"]),
    _fn("estimate_travel", "Travel minutes between two places.",
        {"from_id": _ID, "to_id": _ID}, ["from_id", "to_id"]),
    _fn("check_open", "Is a place open on a day (1 = first day) at a time like '14:00'?",
        {"place_id": _ID, "day": _ID, "time": {"type": "string"}}, ["place_id", "day", "time"]),
    _fn("build_days", "Make a draft plan. Optional: include (Maybe ids to add), exclude "
        "(ids to leave out), pins (list of {place_id, day}).",
        {"include": _IDS, "exclude": _IDS, "pins": {"type": "array", "items": {
            "type": "object", "properties": {"place_id": _ID, "day": _ID}}}}),
    _fn("validate", "Check the last draft. Lists errors and warnings, and if it can be saved."),
    _fn("save_plan", "Save the last draft. Give 1-3 short sentences about trade-offs.",
        {"tradeoffs": {"type": "string"}}, ["tradeoffs"]),
]  # fmt: skip

ASK_TOOL = _fn(
    "ask_group",
    "Post a poll in the group chat and wait for votes (up to 5 min). 2-4 short options.",
    {"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}}},
    ["question", "options"],
)


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
