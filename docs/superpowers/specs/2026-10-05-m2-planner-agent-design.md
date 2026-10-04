# M2 Planner Agent — Design

**Date:** 2026-10-05 · **Milestone:** M2 (due 2026-11-01) · **Issues:** #16–#22
**Status:** decisions approved by Donovan in chat. Spec awaiting review.

## Goal

Anyone in the group types `/plan`. The bot replies with a day-by-day plan, a Google Maps route
link per day, and plain-language trade-offs. An LLM agent picks the steps. Code does the maths
and the checking.

**Done when:** `/plan` on a real trip in the Test group → a plan with no validator errors →
every day's Maps link opens the right route → `AgentTrace` rows are saved. Checked on the Docker
bot, with screenshots in the issues.

**Not in M2:** mini app / map (M3), OR-Tools, Langfuse, flights and hotels (M6), re-planning on
the go, editing a plan by hand, planner eval (#32, M5).

## Decisions

| Topic | Choice | Why |
|---|---|---|
| Model | `PLAN_MODEL` default `ollama_chat/qwen3:4b-instruct`, optional `PLAN_FALLBACK_MODEL` | Free by default. Spike: 3/3 full tool loops (list → build → validate → fix → save), ~10 s on the Mac. |
| Agent style | Hybrid: LLM picks priorities and reacts to issues; `build_days` and `validate` are code | A 4B model can't do route maths. It can choose and explain. |
| Never silent | LLM down, cap hit or 8 rounds used up → code-only plan (default priorities) | `/plan` always answers. The message says "planned without AI". |
| Which places | Must + Maybe + unvoted. Skip-majority left out. Unpinned left out and listed. | Votes drive the plan. Can't route a place with no pin. |
| Tier rule | `skip` if skips > musts + maybes. `must` if musts ≥ 1. Else `maybe`. | Simple, explainable. |
| Opening hours | OSM `opening_hours` via Nominatim `extratags=1`. Small parser for common forms. Unknown = warning. | Free. Enough for the "closed on Monday" demo. |
| Hotel | Geocoded at `/plan` (once, stored). Days start and end there. No hotel → city centre. | Realistic routes. |
| Travel | Straight line × 1.3. < 1.5 km walk at 4.5 km/h. < 15 km transit: 20 km/h + 10 min. ≥ 15 km express (train, express bus or taxi): 40 km/h + 15 min. | Matches the v1 design ("distance × speed factor"). Express added after PR1 (Donovan: far places work by express bus; not everyone uses public transport). |
| Day trips | A day's first stop may be up to 3 h from the hotel; far places go first on their day. Hops between stops stay ≤ 60 min. | Donovan, after PR1: Disneyland-style Must-gos shouldn't be dropped. |
| Day window | Flexible by default (see below). `/plan 10-22` sets fixed hours. | Donovan: "let the user choose or based on the day activities". |
| No dates | Reply with how to set them. Max 14 days. | Can't plan days without dates. |
| DB changes | `db/migrate.py` adds missing nullable columns (`ALTER TABLE ADD COLUMN`). Still no Alembic. | `create_all` can't add columns to the live DB. Also unblocks `Source.author` (#48). |
| Re-run | Each `/plan` saves a new `Itinerary` version. One plan per chat at a time. | Keeps history. Avoids two agents racing. |
| ask_group | Telegram poll, max 2 per plan. Ends after 5 min, or sooner once everyone who voted on places has answered. | Donovan's call. |
| Tracing | One `AgentTrace` row per LLM call and per tool call. No Langfuse. | YAGNI. The DB rows feed the M5 eval. |
| Output | One message (split per day only if > 4096 chars). | Same "compact chat" rule as M1. |

## Day window

- **Default (flexible):** the day starts at 09:00, or later if the first stop opens later. It ends
  when the last stop ends, at the latest 22:00. If an evening-only place (opens ≥ 17:00) is on
  the day, the latest end moves to 01:00. A day's busy span is at most 12 h.
- **Fixed:** `/plan 10-22` (hours, 0–24; end < start means past midnight). The start and end are hard.
- Anything else after `/plan` → a short usage reply.

## Data model changes

| Table | Change |
|---|---|
| `Trip` | + `hotel_lat`, `hotel_lng` (nullable) |
| `Place` | + `opening_hours` (nullable text). `NULL` = never checked, `""` = checked, OSM has none. |
| `Itinerary` (new) | id, trip_id, version, run_id, used_ai (bool), tradeoffs (text), window (text), created_at |
| `ItineraryItem` (new) | id, itinerary_id, day (date), order, place_id, start_min, end_min, travel_minutes |
| `AgentTrace` (new) | id, trip_id, run_id, step, kind (`llm`/`tool`), tool, input, output, tokens, created_at |

`run_id` is a uuid per `/plan` run, so traces exist even when no plan is saved.
Minutes are counted from midnight on that day (a 00:30 end is 1470).

## Modules (each file < 200 lines)

```
travelkaki/
  config.py             # + plan_model, plan_fallback_model
  db/migrate.py         # add_missing_columns(engine), called by init_db
  db/models.py          # + columns above, Itinerary, ItineraryItem, AgentTrace
  db/plan_queries.py    # save_itinerary, add_trace, set_hotel_pin, set_hours, ...
  geo/nominatim.py      # + extratags=1, GeoResult.opening_hours
  ingest/pipeline.py    # stores opening_hours on new geocodes
  planner/hours.py      # parse OSM hours → is_open(raw, weekday, minute) -> bool | None
  planner/travel.py     # estimate(a, b) -> (minutes, "walk" | "transit")
  planner/types.py      # PlanPlace, Stop, Day, Plan, Issue, Window, Priorities (dataclasses)
  planner/build.py      # build_days(...) -> Plan  (pure, #18)
  planner/validate.py   # validate(plan, places, window) -> list[Issue]  (pure, #19)
  planner/prepare.py    # load trip, tiers, hotel pin, hours backfill -> PlanInput
  planner/tools.py      # tool schemas + run_tool(name, args, state)  (#17)
  planner/loop.py       # the agent loop, limits, traces, code-only fallback  (#16)
  planner/ask.py        # ask_group: poll, wait, result  (#20)
  llm/client.py         # + chat_tools(messages, tools, on_call) for tool calling
  bot/plan.py           # /plan handler: args, lock, progress message, run, post  (#22)
  bot/plan_text.py      # message text + Google Maps directions links  (#22)
```

## Planner input (`prepare.py`)

1. No trip → "run /newtrip first". No dates → "set dates: `/newtrip Tokyo 12-15 Dec`".
   More than 14 days → error.
2. Tier each place (rule above). Drop `skip`. Places with no pin go into `dropped` ("no map pin").
3. Hotel set but no pin → geocode it once with `Nominatim.locate`, store `hotel_lat/lng`.
   Not found → use the city centre and add a warning.
4. Places with a pin and `opening_hours IS NULL` → fetch hours (Nominatim search with
   `extratags`, ~1 s each, then cached in the DB). The progress message says "Checking opening hours…".
5. Visit length by category keyword: food/cafe 60/45 min, museum/attraction 120, park/viewpoint 60,
   shopping 60, bar/nightlife 90, else 60.

## build_days (code, #18)

Input: places, dates, base point (hotel or centre), window, `Priorities` from the agent:
`include` (ids), `exclude` (ids), `pins` ({place_id: day_number}).

1. Candidates = musts + maybes − exclude + include. Pinned places go to their day first.
2. Group musts into days by area: k-means on lat/lng, k = number of days, farthest-point
   seeds from the base, 10 rounds, so results are repeatable. A day over its time budget gives
   its farthest place to the nearest day with room.
3. Add maybes (most votes first) to the closest day that still has time.
4. Order each day by nearest neighbour from the base.
5. Fit times: walk the day from its start. If a place is closed on arrival and opens within
   60 min, wait. Otherwise try it later in the day. Still impossible → move it to `dropped`
   with a reason ("closed on Tue 16 Dec", "no time left on Day 2").
6. Return `Plan(days, dropped)`. The same input always gives the same plan.

## validate (code, #19)

Returns a list of `Issue(level, code, place_id, day, text)`. **Valid** = no `error`.

| Code | Level | Rule |
|---|---|---|
| `missing_must` | error | A must place is not in the plan |
| `skip_included` | error | A skip place is in the plan |
| `closed` | error | Known hours say it's closed at the planned time |
| `day_too_long` | error | Ends after the window's latest end, or busy span > 12 h |
| `long_transfer` | error | A hop between stops > 60 min, or a day's first trip > 3 h |
| `hours_unknown` | warning | No hours for a planned place |
| `meal_time` | warning | Day has meal places (restaurant, ramen, sushi…, not cafes or markets) but none in 11:00–14:30 or 17:30–21:30. Meal places never start before 11:00. |
| `no_hotel_pin` | warning | The base point is the city centre |

`save_plan` accepts a plan whose only errors are `missing_must` for places that `build_days`
put in `dropped` (with a reason). Any other error → the tool says "fix or exclude it first".

## Agent loop (`loop.py`, #16)

- **System prompt:** the goal, the rules above in short form, the tools, the limits. Ask the
  group only when two must-gos compete and no plan fits both.
- **Tools** (JSON schemas, small args so a 4B model copes):

| Tool | Args | Returns |
|---|---|---|
| `list_places` | – | id, name, category, tier, votes, hours known? |
| `get_place_details` | place_id | address, hours text, video note |
| `estimate_travel` | from_id, to_id | minutes, mode |
| `check_open` | place_id, day (1..n), time ("14:00") | open / closed / unknown |
| `build_days` | include?, exclude?, pins? | the draft plan, short text form |
| `validate` | – | issues for the last draft |
| `ask_group` (PR3) | question, options (2–4) | votes per option |
| `save_plan` | tradeoffs (≤ 3 sentences) | ok, or why not |

- **Limits:** 8 LLM rounds, 2 `ask_group` calls, 1500 output tokens per round. Each LLM try
  counts toward `LLM_DAILY_CAP`.
- **Unknown tool, bad JSON args, or a bad place id** → a tool error message goes back to the
  model (counts as a round). It never crashes.
- **Fallback:** no `save_plan` after 8 rounds, `LlmUnavailable`, or `CapReached` →
  `build_days(default priorities)`, then save with `used_ai=False`.
- **Trade-offs shown** = the agent's text (when it used AI) + code-written reasons for every
  dropped place. So a dropped place always has a true reason, even if the model's text is vague.
- **Trace:** every LLM call (tokens) and tool call (input, output cut to 2000 chars) → `AgentTrace`.

## ask_group (`ask.py`, #20)

- Sends an anonymous Telegram poll with the options + "No preference".
- Waits until 5 min pass or `total_voter_count` ≥ the number of people who voted on places
  (at least 1). A `PollHandler` sets an `asyncio.Event` for that poll id.
- Then `stop_poll`, and the counts go back to the agent. Third call → "limit reached, decide yourself".
- The progress message says "Waiting for the poll (up to 5 min)…".

## /plan in the chat (`bot/plan.py`, `bot/plan_text.py`, #22)

1. Parse args (window). Bad args → usage reply.
2. A plan is already running for this chat → "Already planning, hang on ⏳".
3. Post "Planning… 🗺" and edit it as steps go (hours, poll, done).
4. Run in the background (`application.create_task`). Never block other handlers.
5. Post the plan, delete the progress message.

```
🗓 Tokyo plan · v2 · 3 days
Day 1 · Fri 12 Dec
09:30 Tsukiji Outer Market · 1 h
10:45 🚶 12 min → teamLab Planets · 2 h
…
🗺 Day 1 route
…
Trade-offs: Couldn't fit Shibuya Sky – no time left on Day 3.
Not planned: Ramen Afro Beats (no map pin)
⚠️ Hours unknown for 3 places.
```

- Day route link: `https://www.google.com/maps/dir/?api=1&origin=<base>&destination=<base>&waypoints=a|b|…`
  using `lat,lng`. Max 9 waypoints per link (Google's limit); a longer day gets a second link.
- HTML parse mode. Every place name goes through `html.escape`.
- Errors (no trip, no dates, no pinned places, crash) → a plain reply. Never silent.
- Logs: `plan chat=<id> run=<run_id> rounds=<n> used_ai=<bool>` at INFO.

## Errors (the bot is never silent)

| Case | Reply |
|---|---|
| No trip | Start a trip first: `/newtrip Tokyo 12-15 Dec` |
| No dates | Add dates: `/newtrip Tokyo 12-15 Dec` |
| No pinned places | Nothing to plan yet. Post some TikTok/IG links first. |
| LLM down / cap | The plan, marked "planned without AI" |
| Unexpected crash | "Planning failed, please try /plan again." (logged with run_id) |
| Bot restarts mid-plan | Lost. Run `/plan` again. (Not worth recovery code in v1.) |

## Testing

- **Unit (pure):** hours parser (common forms + unknown forms), travel, tiers, `build_days`
  (clusters, capacity, closed day, pins, include/exclude, repeatable), every validator rule,
  Maps link (≤ 9 waypoints), plan text (escaping, split > 4096), window args, migrate helper.
- **Loop:** a scripted fake LLM (a list of tool calls) → saves a plan; bad tool → error
  message; 8 rounds → fallback; `LlmUnavailable` / `CapReached` → fallback; traces written.
- **Handlers:** fake bot → no trip, no dates, lock, progress message edited, plan posted.
- **ask_group:** fake bot + fake clock → early close on enough votes, timeout, limit of 2.
- **Live:** `@pytest.mark.live` runs the real Ollama loop on a fixture trip. Skipped in CI.
- No network or LLM calls in CI.

## Delivery

| PR | Issues | Done when |
|---|---|---|
| PR1 `m2-pr1` | #17 (pure parts), #18, #19, DB + hours | Unit tests pass. Hours saved on a live link. |
| PR2 `m2-pr2` | #16, #17, #21, #22 | **Demo:** `/plan` in the Test group → valid plan + Maps links. |
| PR3 `m2-pr3` | #20 | A poll appears for a real must-go clash, and the plan uses the answer. |

Each PR: branch → PR → CI green → one fresh reviewer → merge. Progress is logged on the issues.

## Risks

| Risk | Mitigation |
|---|---|
| 4B model loops or drops must-gos | Validator + `save_plan` rules, 8-round cap, code-only fallback. `PLAN_FALLBACK_MODEL`. |
| OSM has no hours for many places | Unknown = warning. Google Places (#42) later. |
| Straight-line travel is off in big cities | × 1.3 detour, 60-min transfer rule. OR-Tools / real routing later. |
| Poll waits make `/plan` slow | Max 2 polls, early close, progress message. |
| Mac busy during LLM calls | 20 s Telegram timeouts already set (M1). |
