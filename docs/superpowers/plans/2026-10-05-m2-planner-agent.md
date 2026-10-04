# M2 Planner Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/plan` in the group returns a valid day-by-day itinerary with Google Maps route links and plain-language trade-offs.

**Architecture:** `planner/prepare.py` turns the trip into a `PlanInput` (tiers, pins, hours, base point). A hand-written loop (`planner/loop.py`) lets the LLM call tools. The heavy tools, `build_days` and `validate`, are pure code. If the LLM fails, the code-only plan is used. `bot/plan.py` runs it in the background and posts one compact message.

**Tech Stack:** Python 3.12, python-telegram-bot 22.8, SQLAlchemy 2.1, LiteLLM 1.103 (tool calling), httpx, pytest + pytest-asyncio, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-10-05-m2-planner-agent-design.md` (read it first).

## Global Constraints

- Every `.py` file < 200 lines. Lots of short plain-English comments (Donovan's rule). Never delete old comments.
- Test first. No network or LLM calls in CI. Live tests use `@pytest.mark.live`.
- Never `git add -A`. Stage paths explicitly. Never print or log the bot token or message text.
- **No Claude attribution** in commits, PRs or issue comments (no `Co-Authored-By`, no session links, no "Generated with").
- New settings: `PLAN_MODEL=ollama_chat/qwen3:4b-instruct`, `PLAN_FALLBACK_MODEL=` (empty).
- Limits: 8 LLM rounds, 2 `ask_group` polls, 1500 output tokens per round, 14 days max, 9 waypoints per Maps link, transfer ≤ 60 min, busy span ≤ 12 h (720 min), poll wait 300 s, trace input/output cut to 2000 chars, hours backfill ≤ 25 places per run.
- Default window: start 09:00 (540), latest end 22:00 (1320), or 01:00 (1500) when an evening place (opens ≥ 17:00, or a bar/nightlife/club/izakaya category) is on the day.
- Travel: straight line × 1.3. Under 1500 m → walk at 4.5 km/h. Else transit at 20 km/h + 10 min. Round minutes up.
- Visit minutes by category keyword (lower-case `in` match, first hit wins): cafe/coffee/bakery/dessert 45 · restaurant/ramen/sushi/food/market/stall/izakaya 60 · museum/attraction/theme/aquarium/zoo/gallery 120 · park/viewpoint/temple/shrine/garden 60 · shop/mall/market 60 · bar/nightlife/club 90 · else 60.
- Food keywords (for `meal_time`): cafe, coffee, bakery, dessert, restaurant, ramen, sushi, food, market, stall, izakaya.
- Messages: `parse_mode="HTML"`. Every place name goes through `html.escape`.
- Commands: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .` (in `device_bash` set `UV_PROJECT_ENVIRONMENT=$HOME/.venv-tk`). Git and `gh` run on the Mac shell.
- PR workflow: branch → PR → CI green → one fresh reviewer → `gh pr merge --merge --delete-branch`. Comment progress on each issue. Close issues after merge.

## Review Focus

1. **Place names with `<`, `&` or emoji** → plan message renders, nothing crashes. Test in Task 12.
2. **`/plan` sent twice quickly** → second gets "Already planning, hang on ⏳", only one run. Test in Task 13.
3. **Model sends bad tool args** (string ids like `"3"`, ids from another trip, a list instead of an object, unknown tool) → a tool error string goes back to the model, no crash. Test in Task 10.
4. **Odd OSM hours** (`Mo-Su 11:00-02:00`, `PH off`, `sunrise-sunset`, `Jan-Mar …`) → past-midnight works; unsupported forms are unknown (`None`), never an exception. Test in Task 2.
5. **More days than places, or a day with > 9 stops** → empty days print "Free day"; long days get a second route link. Tests in Tasks 5 and 12.

---

## File map

| File | Responsibility | Task |
|---|---|---|
| `travelkaki/db/migrate.py` | add missing nullable columns | 1 |
| `travelkaki/db/models.py` | + Trip/Place columns, Itinerary, ItineraryItem, AgentTrace | 1 |
| `travelkaki/db/plan_queries.py` | hotel pin, hours, itinerary, traces, voter count | 1 |
| `travelkaki/planner/hours.py` | OSM hours parser | 2 |
| `travelkaki/geo/nominatim.py`, `ingest/pipeline.py`, `db/place_queries.py` | hours on new geocodes | 3 |
| `travelkaki/planner/types.py` | dataclasses shared by the planner | 4 |
| `travelkaki/planner/travel.py` | travel estimate | 4 |
| `travelkaki/planner/rules.py` | tier, visit minutes, food/evening checks | 4 |
| `travelkaki/planner/build.py` | `build_days` | 5 |
| `travelkaki/planner/validate.py` | `validate` | 6 |
| `travelkaki/config.py`, `llm/client.py` | plan settings, `chat_tools` | 8 |
| `travelkaki/planner/prepare.py` | trip → `PlanInput` | 9 |
| `travelkaki/planner/prompt.py` | system prompt + tool schemas | 10 |
| `travelkaki/planner/tools.py` | `ToolState`, `run_tool` | 10 |
| `travelkaki/planner/loop.py` | agent loop, traces, fallback | 11 |
| `travelkaki/bot/plan_text.py` | message text + route links | 12 |
| `travelkaki/bot/plan.py` | `/plan` handler | 13 |
| `travelkaki/planner/ask.py` | `ask_group` + poll handler | 15 |

---

## PR1 — branch `m2-pr1` — #17 (pure parts), #18, #19, DB

### Task 1: DB changes + migrate helper (#21 tables)

**Files:**
- Create: `travelkaki/db/migrate.py`, `travelkaki/db/plan_queries.py`
- Modify: `travelkaki/db/models.py`, `travelkaki/db/base.py` (`init_db` calls `add_missing_columns`)
- Test: `tests/test_migrate.py`, `tests/test_plan_queries.py`

**Interfaces:**
- Produces:
  - `Trip.hotel_lat`, `Trip.hotel_lng`: `float | None`. `Place.opening_hours`: `str | None` (`None` = never checked, `""` = checked, none).
  - `Itinerary(id, trip_id, version: int, run_id: str(36), used_ai: bool, tradeoffs: str = "", window: str(20), created_at)`.
  - `ItineraryItem(id, itinerary_id, day: date, order: int, place_id, start_min: int, end_min: int, travel_minutes: int)`.
  - `AgentTrace(id, trip_id, run_id, step: int, kind: str(10), tool: str | None, input: str, output: str, tokens: int = 0, created_at)`.
  - `migrate.add_missing_columns(engine) -> list[str]`: returns `"table.column"` for each column added. A missing NOT NULL column → `RuntimeError`.
  - `plan_queries`: `set_hotel_pin(s, trip_id, lat, lng) -> None` · `set_hours(s, place_id, raw: str) -> None` · `add_trace(s, trip_id, run_id, step, kind, tool, input, output, tokens=0) -> None` (cuts input/output to 2000 chars) · `voter_count(s, trip_id) -> int` (distinct `tg_user_id` on the trip's places).
  - `save_itinerary` needs `Plan` (Task 4), so it is added in Task 11.

- [ ] **Step 1: Write failing tests**
  - `test_migrate.py::test_adds_missing_columns_and_keeps_rows`: create the old `trip` table with raw SQL (no hotel columns), insert one row → `init_db(engine)` → the columns exist (`sqlalchemy.inspect`), the row is still there, and the return value includes `"trip.hotel_lat"`.
  - `test_migrate.py::test_second_run_adds_nothing` → `[]`.
  - `test_plan_queries.py::test_trace_is_cut`: a 5000-char output is saved as 2000 chars.
  - `test_plan_queries.py::test_voter_count_distinct`: 2 users voting on 3 places → 2.
- [ ] **Step 2: Run** `uv run pytest tests/test_migrate.py tests/test_plan_queries.py -q` → FAIL.
- [ ] **Step 3: Implement.** `add_missing_columns`: for each table in `Base.metadata.sorted_tables` that exists, compare `inspect(engine).get_columns`. For each missing column, `ALTER TABLE {t} ADD COLUMN {c} {col.type.compile(engine.dialect)}`.
- [ ] **Step 4: Run** → PASS. Full suite + ruff clean.
- [ ] **Step 5: Commit** `"Add itinerary/trace tables and a small add-column migration (#21)"`.

### Task 2: Opening-hours parser (#17)

**Files:** Create `travelkaki/planner/hours.py` · Test `tests/test_hours.py`

**Interfaces:**
- Produces: `parse(raw: str | None) -> dict[int, list[tuple[int, int]]] | None` (weekday 0 = Monday → open intervals in minutes; an end > 1440 means past midnight; `None` = unknown) · `is_open(raw, weekday: int, minute: int) -> bool | None` (also checks yesterday's past-midnight interval) · `next_open(raw, weekday, minute) -> int | None` (the next opening minute that day, at or after `minute`).
- Supported forms: `24/7`; rules split by `;`; each rule is `[days] times`. Days: `Mo Tu We Th Fr Sa Su`, ranges `Mo-Fr`, lists `Sa,Su`, mixed `Mo-Fr,Su`. Missing days = every day. Times: `HH:MM-HH:MM`, comma-separated. `off` / `closed` = closed. Later rules override earlier days. Anything else in the string (PH, SH, months, week numbers, `sunrise`, `+`, quotes, `||`) → `None`.

- [ ] **Step 1: Write failing tests**
  - `test_simple_week`: `"Mo-Fr 10:00-22:00; Sa,Su 09:00-23:00"` → `parse(...)[0] == [(600, 1320)]`, `[6] == [(540, 1380)]`.
  - `test_24_7` → every day `[(0, 1440)]`.
  - `test_past_midnight`: `"Mo-Su 18:00-02:00"` → `is_open(raw, 1, 60) is True` (Tue 01:00 = Monday's interval), `is_open(raw, 1, 900) is False`.
  - `test_off_overrides`: `"Mo-Su 10:00-20:00; Tu off"` → `is_open(raw, 1, 720) is False`.
  - `test_split_times`: `"Mo-Fr 11:00-14:00,17:00-22:00"` → `next_open(raw, 0, 900) == 1020`.
  - `test_unknown_forms`: `None`, `""`, `"PH off"`, `"sunrise-sunset"`, `"Jan-Mar Mo-Fr 10:00-18:00"`, `"Mo-Fr 10:00+"` → `parse` is `None`, `is_open` is `None`. No exceptions.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with one regex per token type. Keep it < 120 lines.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `"Parse common OSM opening hours (#17)"`.

### Task 3: Save hours on new geocodes (#17)

**Files:** Modify `travelkaki/geo/nominatim.py`, `travelkaki/db/place_queries.py`, `travelkaki/ingest/pipeline.py` · Test `tests/test_geo.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces: `GeoResult.opening_hours: str | None = None` (from `hits[0]["extratags"]["opening_hours"]` when present). Search params gain `"extratags": 1`. `add_place(..., opening_hours: str | None = None)`. The pipeline saves `hit.opening_hours or ""` when there is a hit, and `None` when there is no pin.

- [ ] **Step 1: Write failing tests**
  - `test_geo.py::test_search_reads_opening_hours`: the fake HTTP returns `extratags: {"opening_hours": "Mo-Su 10:00-20:00"}` → the result has it, and the request params include `extratags=1`.
  - `test_geo.py::test_missing_extratags_is_none`.
  - `test_pipeline.py::test_pinned_place_stores_hours`: the fake geo returns hours → `Place.opening_hours` is saved. A hit with no hours → `""`. No hit → `None`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** full suite → PASS.
- [ ] **Step 5: Commit** `"Store OSM opening hours when geocoding (#17)"`.

### Task 4: Planner types, travel, rules (#17, #18)

**Files:** Create `travelkaki/planner/types.py`, `travelkaki/planner/travel.py`, `travelkaki/planner/rules.py` · Test `tests/test_travel_rules.py`

**Interfaces:**
- Produces (`types.py`, all `@dataclass`):
  - `Window(start: int = 540, latest_end: int = 1320, fixed: bool = False)`, plus `EVENING_END = 1500` and `MAX_SPAN = 720`. `Window.label() -> str` gives `"flex"` or `"10-22"`.
  - `PlanPlace(id: int, name: str, category: str, lat: float, lng: float, tier: str, must: int, maybe: int, hours: str | None, visit: int, note: str = "", address: str | None = None)`.
  - `Stop(place_id: int, start: int, end: int, travel: int, mode: str)`.
  - `Day(date: date, stops: list[Stop])`.
  - `Dropped(place_id: int, name: str, reason: str)`.
  - `Plan(days: list[Day], dropped: list[Dropped])`.
  - `Issue(level: str, code: str, text: str, place_id: int | None = None, day: int | None = None)` (`day` is 1-based).
  - `Priorities(include: list[int] = [], exclude: list[int] = [], pins: dict[int, int] = {})` (use `field(default_factory=...)`).
  - `PlanInput(trip_id: int, city: str, dates: list[date], base: tuple[float, float], base_is_hotel: bool, places: list[PlanPlace], skipped: list[int], dropped: list[Dropped], window: Window)`, with `place(id) -> PlanPlace | None`.
- `travel.estimate(a: tuple[float, float], b: tuple[float, float]) -> tuple[int, str]`.
- `rules.tier(must: int, maybe: int, skip: int) -> str` (`"skip" | "must" | "maybe"`) · `rules.visit_minutes(category: str) -> int` · `rules.is_food(category) -> bool` · `rules.is_evening(place: PlanPlace) -> bool` (category keyword, or known hours where every interval starts ≥ 1020).

- [ ] **Step 1: Write failing tests**
  - `test_estimate`: same point → `(0, "walk")`. ~1 km apart → `(18, "walk")`. ~10 km apart → `(49, "transit")`. Build the points with `geo.distance` in mind (e.g. 0.009° latitude ≈ 1 km).
  - `test_tier`: `(0,0,0)` → maybe. `(1,0,0)` → must. `(1,0,2)` → skip. `(0,2,2)` → maybe. `(0,0,1)` → skip.
  - `test_visit_minutes`: `"Cafe"` → 45, `"ramen shop"` → 60, `"Museum"` → 120, `"bar"` → 90, `""` → 60.
  - `test_is_evening`: category `"izakaya"` → True. Hours `"Mo-Su 18:00-02:00"` → True. A museum with day hours → False.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `"Add planner types, travel estimate and rules (#17)"`.

### Task 5: build_days (#18)

**Files:** Create `travelkaki/planner/build.py` · Test `tests/test_build.py`

**Interfaces:**
- Consumes: Task 4 types, `travel.estimate`, `hours.is_open/next_open`, `rules.is_evening`.
- Produces: `build_days(inp: PlanInput, pr: Priorities | None = None) -> Plan`. Pure and repeatable. Every candidate ends up in exactly one place: a day's stops or `dropped`.

- [ ] **Step 1: Write failing tests** (a helper `make_input(places, days=2, window=Window())`, with Tokyo-like points)
  - `test_clusters_by_area`: 2 days, 2 places near A and 2 near B (≥ 8 km apart) → each day holds one area.
  - `test_same_input_same_plan`: two calls → equal plans.
  - `test_closed_day_moves_must`: a must closed on day 1's weekday (`"Mo-Su 10:00-18:00; Tu off"`, day 1 = a Tuesday), 2 days → it is planned on day 2.
  - `test_closed_whole_trip_dropped`: closed every trip day → in `dropped`, reason contains `"closed"`.
  - `test_waits_up_to_60_min`: a place opening at 10:00 as the first stop → it starts at 600.
  - `test_no_time_left`: 12 two-hour musts on 1 day → some dropped, reason contains `"no time left"`, and no day ends after 1320.
  - `test_evening_place_extends_day`: a bar open 18:00–02:00 → planned, may end after 1320 but ≤ 1500.
  - `test_fixed_window`: `Window(600, 1200, fixed=True)` → first start ≥ 600, last end + the trip back ≤ 1200.
  - `test_include_exclude_pins`: exclude a must → not planned (it doesn't go to `dropped` either; it's the agent's choice). Pin a place to day 2 → it's on day 2. Include a maybe → it's planned.
  - `test_more_days_than_places`: 1 place, 3 days → 3 `Day`s, two with `stops == []`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** following the spec's "build_days" steps 1–6. Plus one repair pass: each dropped must is tried on every other day (append → reorder by nearest neighbour → refit). Keep the first day where every stop still fits. Assignment budget per day = Σ(visit + 15) ≤ `MAX_SPAN`. Split helpers (`_cluster`, `_order`, `_fit`) if the file nears 200 lines → `planner/fit.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `"build_days: group by area, order by distance, fit hours (#18)"`.

### Task 6: validate (#19)

**Files:** Create `travelkaki/planner/validate.py` · Test `tests/test_validate.py`

**Interfaces:**
- Produces: `validate(plan: Plan, inp: PlanInput) -> list[Issue]` · `errors(issues) -> list[Issue]` · `savable(plan, issues) -> bool` (no errors, except `missing_must` for places in `plan.dropped`).
- Codes and levels: exactly the spec's table (`missing_must`, `skip_included`, `closed`, `day_too_long`, `long_transfer` = error; `hours_unknown`, `meal_time`, `no_hotel_pin` = warning). The text names the place and the day, e.g. `"teamLab Planets is closed at 14:00 on Day 2"`.

- [ ] **Step 1: Write failing tests**: one test per code with a hand-built `Plan`, plus:
  - `test_build_days_output_has_no_errors_except_dropped_musts`: run `build_days` on the Task 5 fixtures → `savable` is True.
  - `test_savable_rejects_closed`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `"validate(plan): itinerary rules with errors and warnings (#19)"`.

### Task 7: PR1 ship

- [ ] Rebuild Docker (`docker compose up -d --build`). Post one TikTok link in the Test group → check the DB: the new place has `opening_hours` set (or `""`). Check that the old rows survived the migration.
- [ ] Push `m2-pr1` (it already holds the spec + this plan) → PR "M2 PR1: planner core (hours, build_days, validate)" → CI green → fresh reviewer → fix Important+ → merge.
- [ ] Comment on #17 (pure parts), #18 and #19, and close #18 and #19.

---

## PR2 — branch `m2-pr2` — #16, #17, #21, #22 (demo)

### Task 8: Plan settings + LLM tool calling (#16)

**Files:** Modify `travelkaki/config.py`, `.env.example`, `travelkaki/llm/client.py` · Test `tests/test_config.py`, `tests/test_llm.py`

**Interfaces:**
- Produces: `Settings.plan_model: str = "ollama_chat/qwen3:4b-instruct"`, `Settings.plan_fallback_model: str | None = None`.
  - `llm.client.ToolCall(id: str, name: str, arguments: str)` and `ToolReply(content: str | None, tool_calls: list[ToolCall], message: dict, tokens: int)` (dataclasses). `message` = the assistant message to add back to the history (`model_dump(exclude_none=True)`).
  - `LlmClient.chat_tools(messages, tools, on_call) -> ToolReply`. Same tries as extract (main ×2, fallback ×1, `on_call` before each try, `CapReached` passes through), using `plan_model`/`plan_fallback_model`, `tools=tools`, `temperature=0`, `max_tokens=1500`, `timeout=120`. `_tries(main, fallback)` is shared with `extract_json`.

- [ ] **Step 1: Write failing tests**: `test_plan_defaults`. `test_chat_tools_parses_tool_calls` (a fake completion returns one tool call → `ToolReply.tool_calls[0].name == "list_places"`, `tokens` from `usage.total_tokens`). `test_chat_tools_uses_plan_model` (the model passed == `plan_model`). `test_chat_tools_falls_back_then_raises`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `"LLM tool calling for the planner (#16)"`.

### Task 9: prepare (#17)

**Files:** Create `travelkaki/planner/prepare.py` · Test `tests/test_prepare.py`

**Interfaces:**
- Produces: `class PlanError(Exception)` with `.code` in `{"no_trip", "no_dates", "too_many_days", "no_places"}` · `async prepare(deps: Deps, chat_id: int, window: Window, progress=None) -> PlanInput`. `progress` is an optional `async (text) -> None`.
- Steps: the spec's "Planner input" 1–5. Hotel: `deps.geo.locate(hotel, city, center)` → `set_hotel_pin`. Not found → base = city centre, `base_is_hotel=False`. Hours backfill: up to 25 pinned places with `opening_hours is None` → `progress("Checking opening hours…")` once → `deps.geo.search(f"{name}, {city}", viewbox(pin, 1))`. A hit stores `hit.opening_hours or ""`; no hit leaves it `None`. `no_places` = no pinned must/maybe places.

- [ ] **Step 1: Write failing tests** (fake geo): each `PlanError` code. Tiers applied and skips in `skipped`. Unpinned places in `dropped` with reason `"no map pin"`. Hotel pinned once (a second call makes no geo call). Hours backfilled and saved. A 15-day trip → `too_many_days`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `"prepare: trip, votes, hotel and hours into PlanInput (#17)"`.

### Task 10: Tools (#17)

**Files:** Create `travelkaki/planner/prompt.py`, `travelkaki/planner/tools.py` · Test `tests/test_tools.py`

**Interfaces:**
- Produces: `prompt.SYSTEM_PROMPT: str` (goal, rules, limits, "ask the group only when two must-gos compete") · `prompt.TOOLS: list[dict]` (OpenAI-style schemas for the spec's tool table, without `ask_group`) · `prompt.ASK_TOOL: dict` (used in Task 15).
  - `tools.ToolState(inp: PlanInput, draft: Plan | None = None, issues: list[Issue] = [], saved: bool = False, tradeoffs: str = "", polls: int = 0, ask=None)`.
  - `async tools.run_tool(name: str, raw_args: str, st: ToolState) -> str` (async so `ask_group` can await in Task 15): never raises. It returns compact text or JSON for the model. Bad JSON / non-object / unknown tool / unknown or non-int id → `"error: …"`. Ids and `pins` keys may arrive as `"3"`: accept digit strings. `save_plan` with no draft → error. With `not savable` → `"error: fix or exclude first: <codes>"`. Otherwise sets `saved` and `tradeoffs` (cut to 3 sentences / 400 chars).
  - `tools.plan_summary(plan, inp) -> str`: one line per day: `Day 1 (Tue 16 Dec): Tsukiji 09:30, teamLab 11:00 | dropped: X (reason)`.

- [ ] **Step 1: Write failing tests**: `list_places` lists tiers and votes. `check_open` returns `open`/`closed`/`unknown`. `build_days` then `validate` stores a draft and issues. `save_plan` before `build_days` → error. Review Focus 3: `run_tool("estimate_travel", '{"from_id":"1","to_id":999}', st)` starts with `"error"`. `run_tool("nope", "{}", st)` → error. `run_tool("build_days", "[1,2]", st)` → error.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `"Planner tools and prompt (#17)"`.

### Task 11: Agent loop + traces + fallback (#16, #21)

**Files:** Create `travelkaki/planner/loop.py` · Modify `tests/fakes.py` (+ `FakeToolLlm`), `travelkaki/db/plan_queries.py` (+ `save_itinerary`) · Test `tests/test_loop.py`, `tests/test_plan_queries.py`

**Interfaces:**
- Consumes: `LlmClient.chat_tools`, `ToolState`, `run_tool`, `SYSTEM_PROMPT`, `TOOLS`, `make_counter`, `add_trace`, `build_days`, `validate`.
- Produces: `plan_queries.save_itinerary(s, trip_id, run_id, plan: Plan, *, used_ai: bool, tradeoffs: str, window: str) -> Itinerary` (version = last + 1; one `ItineraryItem` per stop, `day` = that day's date) · `PlanResult(plan: Plan, issues: list[Issue], used_ai: bool, tradeoffs: str, rounds: int)` · `async run_planner(deps: Deps, inp: PlanInput, run_id: str, ask=None) -> PlanResult`. `MAX_ROUNDS = 8`. With `ask` set, `ASK_TOOL` is added to the tools.
- Behaviour: messages = system + user ("Plan this trip: <city>, <n> days"). Each round: `chat_tools` → trace (`kind="llm"`, tokens) → run each tool call → trace (`kind="tool"`) → append the `role: tool` messages. Stop when `st.saved`. A round with text and no tool call → append "Use the tools. Finish with save_plan." No save after 8 rounds, `LlmUnavailable` or `CapReached` → fallback: `plan = build_days(inp)`, `used_ai=False`, `tradeoffs=""`. A saved plan uses `st.draft`. Issues are always recomputed with `validate`.
- `FakeToolLlm(script: list[ToolReply | Exception])`: calls `on_call()` each round and pops the script.

- [ ] **Step 1: Write failing tests**: `test_plan_queries.py::test_versions_increase` (two `save_itinerary` → versions 1, 2; item count = stops). `test_scripted_run_saves` (list → build → validate → save → `used_ai`, rounds == 4, traces > 4). `test_bad_tool_does_not_crash`. `test_eight_rounds_then_fallback` (the script never saves). `test_llm_down_fallback`. `test_cap_reached_fallback` (cap 0). `test_text_only_reply_nudges`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `"Planner agent loop with traces and code-only fallback (#16, #21)"`.

### Task 12: Plan text + route links (#22)

**Files:** Create `travelkaki/bot/plan_text.py` · Test `tests/test_plan_text.py`

**Interfaces:**
- Produces: `route_links(base: tuple, points: list[tuple]) -> list[str]` (chunks of ≤ 9 waypoints; each link `https://www.google.com/maps/dir/?api=1&origin=lat,lng&destination=lat,lng&waypoints=a|b` URL-encoded; origin/destination = base; for later chunks the origin is the last point of the previous chunk) · `format_plan(inp: PlanInput, result: PlanResult, version: int) -> list[str]` (each ≤ 4096 chars, split on day blocks).
- Copy: the layout in the spec's "/plan in the chat". Times `HH:MM` (minutes mod 1440). Duration `45 min` / `1 h` / `1 h 30`. 🚶 for walk, 🚇 for transit. Empty day → `Free day`. Route link text `🗺 Day N route` (`Day N route 2` for the second chunk). `Not planned:` lists `inp.dropped` + `plan.dropped` with reasons. `⚠️ Hours unknown for N places.` when N > 0. When not `used_ai`: `Planned without AI (the model was unavailable).`

- [ ] **Step 1: Write failing tests**: Review Focus 1 (name `"A<b>&🍜"` → escaped, no raw `<b>`). Review Focus 5 (12 stops → 2 links, each with ≤ 9 waypoints). `Free day` shown. A 1500-minute end prints `01:00`. Long plan → split, every part ≤ 4096. Without AI → footer present.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `"Plan message text and Google Maps route links (#22)"`.

### Task 13: /plan handler (#22)

**Files:** Create `travelkaki/bot/plan.py` · Modify `travelkaki/bot/app.py` (handler + `BotCommand("plan", "Plan the days: /plan or /plan 10-22")`) · Test `tests/test_plan_command.py`

**Interfaces:**
- Produces: `parse_window(args: list[str]) -> Window` (`[]` → `Window()`; `["10-22"]` → `Window(600, 1320, fixed=True)`; `["18-2"]` → latest_end 1560; anything else → `ValueError`) · `async plan_command(update, context)` · `async run_plan(bot, chat_id: int, window: Window, deps: Deps) -> None`.
- Flow: bad args → usage reply `Usage: /plan or /plan 10-22`. A chat already in `bot_data["planning"]` → `Already planning, hang on ⏳`. Else add the chat, send `Planning… 🗺` (keep its message id), `application.create_task(run_plan(...))`. `run_plan`: `prepare(progress=edit the progress message)` → `run_planner` → `save_itinerary` → send each part of `format_plan` via `results.send` → delete the progress message. On `PlanError` → edit the progress message to the spec's error copy. On any other exception → log with run_id, then `Planning failed, please try /plan again.` Always remove the chat from `planning` in `finally`. Log `plan chat=<id> run=<run_id> rounds=<n> used_ai=<bool>`.

- [ ] **Step 1: Write failing tests** (fake bot recording send/edit/delete, in-memory DB, fake geo, `FakeToolLlm`): `test_parse_window`. `test_no_trip_reply`. `test_no_dates_reply`. Review Focus 2 (two `plan_command` calls before the task runs → the second replies "Already planning"). `test_full_run_posts_plan_and_saves_itinerary`. `test_crash_is_not_silent` (prepare raises `RuntimeError` → the failure text is sent, and the lock is released). `test_application_registers_plan`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `"/plan command: background run, progress message, posted plan (#22)"`.

### Task 14: PR2 ship (demo)

- [ ] Live test `tests/test_planner_live.py` (`@pytest.mark.live`): a fixture trip with 6 Tokyo places over 2 days, run with the real Ollama → `used_ai` is True and `savable`. Run it in the throwaway container (see the handoff).
- [ ] Rebuild Docker. In the Test group: `/newtrip Tokyo <dates> hotel <name>` if needed → `/plan` → screenshot. Open each route link. Check the `itinerary` and `agent_trace` rows. Try `/plan 10-22` and a double `/plan`.
- [ ] PR "M2 PR2: /plan agent (demo)" → CI green → fresh reviewer → fixes → merge. Comment on and close #16, #17, #21, #22.

---

## PR3 — branch `m2-pr3` — #20

### Task 15: ask_group (#20)

**Files:** Create `travelkaki/planner/ask.py` · Modify `travelkaki/planner/tools.py` (the `ask_group` branch), `travelkaki/bot/plan.py` (pass `ask`), `travelkaki/bot/app.py` (`PollHandler(on_poll)`) · Test `tests/test_ask.py`

**Interfaces:**
- Produces: `POLL_WAIT = 300` · `async ask_group(bot, chat_id: int, question: str, options: list[str], target: int, waiters: dict, timeout: float = POLL_WAIT) -> dict[str, int]` (sends an anonymous poll with `options + ["No preference"]`, registers `waiters[poll_id] = (target, asyncio.Event())`, waits until the event fires or the timeout passes, calls `stop_poll`, returns `{option: votes}`, removes the waiter) · `async on_poll(update, context)` (sets the event when `poll.total_voter_count >= target`).
- `run_tool("ask_group", …)`: no `st.ask` → `"error: not available"`. `st.polls >= 2` → `"limit reached, decide yourself"`. Options must be 2–4 strings of ≤ 100 chars, question ≤ 300 chars, else an error. Otherwise `polls += 1`, then `await st.ask(question, options)` → JSON counts.
- `bot/plan.py` builds `ask` as a closure: `progress("Waiting for the poll (up to 5 min)…")`, then `ask_group(bot, chat_id, q, opts, max(1, voter_count), bot_data["polls"])`.

- [ ] **Step 1: Write failing tests**: `test_early_close` (a fake bot; `on_poll` with `total_voter_count=2`, target 2 → returns before the timeout; `stop_poll` called). `test_timeout` (`timeout=0.01`). `test_third_poll_refused`. `test_bad_options_rejected`. `test_application_registers_poll_handler`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `"ask_group: Telegram poll with early close (#20)"`.

### Task 16: PR3 ship + M2 close-out

- [ ] Live: set up a clash (two musts that only fit the same afternoon) → `/plan` → the poll appears → vote → the plan follows the answer. Check that poll updates arrive (PTB default `allowed_updates` includes `poll`; if not, pass `allowed_updates=Update.ALL_TYPES` in `start_polling`).
- [ ] PR "M2 PR3: ask_group polls" → CI → reviewer → merge. Close #20 and the M2 milestone.
- [ ] Update `claude/handoff.md` in the project and the Obsidian note `Brain/Projects/TravelKaki.md`. Add deferred minors to a new M2 follow-ups issue.
