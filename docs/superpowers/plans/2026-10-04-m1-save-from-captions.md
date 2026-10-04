# M1 Save from Captions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A TikTok/IG link posted in a group becomes saved, voteable place cards, with `/places` showing the tally.

**Architecture:** The bot handlers (`bot/`) save a `Source` and start a background task. The fixed-step pipeline (`ingest/pipeline.py`) runs caption → LLM extract → geocode → dedupe. Every outside call (HTTP, LLM, geocoder) lives on a `Deps` object that is passed in, so tests use fakes. SQLite through sync SQLAlchemy.

**Tech Stack:** Python 3.12, python-telegram-bot 22.8, SQLAlchemy 2.1, LiteLLM 1.103, httpx, yt-dlp, pydantic, pytest + pytest-asyncio, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-10-04-m1-save-from-captions-design.md` (read it first).

## Global Constraints

- Every `.py` file < 200 lines. Lots of short plain-English comments (Donovan's rule). Never delete old comments.
- Test first. No network or LLM calls in CI. Live tests use `@pytest.mark.live` and are skipped unless `-m live`.
- Never `git add -A`. Stage paths explicitly. Never print or log the bot token or message text.
- Logs: one INFO line per command, `"<command> chat=<chat_id>"`.
- Defaults: `DATABASE_URL=sqlite:///data/travelkaki.db`, `EXTRACT_MODEL=ollama_chat/qwen3:4b-instruct`, `EXTRACT_FALLBACK_MODEL=` (empty), `OLLAMA_BASE_URL=http://host.docker.internal:11434`, `LLM_DAILY_CAP=100`, `NOMINATIM_EMAIL=` (empty).
- Limits: 5 links per message, 10 cards per link, `video_note` ≤ 15 words, caption sent to the LLM ≤ 2000 chars, LLM timeout 60 s, Nominatim ≤ 1 req/s, viewbox/far radius 50 km, dedupe radius 100 m.
- Cards and messages use `parse_mode="HTML"`. Every user-supplied string goes through `html.escape`.
- Commands: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .` (in `device_bash` set `UV_PROJECT_ENVIRONMENT=$HOME/.venv-tk`).
- PR workflow: branch → PR → CI green → `gh pr merge --merge --delete-branch`. Comment progress on each issue. Close issues after merge.

## Review Focus

1. **Edited messages** must not process a link twice → `on_message` only handles new messages (`filters.UpdateType.MESSAGE`). Test in Task 10.
2. **Same link posted twice at once** → the unique constraint fires → "Already saved ✅", no crash. Test in Task 1 (`add_source` returns `None` on `IntegrityError`).
3. **HTML special characters in place names / captions** (`<`, `&`, `*`) → cards render and nothing crashes. Test in Task 9.
4. **Stale callback** (place deleted, or bad callback data) → toast "This place no longer exists.", no exception. Test in Task 11.
5. **Very long captions** (TikTok allows ~4000 chars) → cut to 2000 chars before the LLM. Test in Task 6.

---

## File map

| File | Responsibility | Task |
|---|---|---|
| `travelkaki/config.py` | + new settings | 1 |
| `travelkaki/db/base.py` | `Base`, engine, sessions, `init_db` | 1 |
| `travelkaki/db/models.py` | tables + StrEnums | 1 |
| `travelkaki/db/queries.py` | trip/source/place/vote queries | 1, 8 |
| `travelkaki/ingest/urls.py` | canonical URLs, platform, redirects | 2 |
| `travelkaki/bot/trip.py` | `/newtrip` parse + handler | 3 |
| `travelkaki/deps.py` | `Deps` dataclass, `build_deps`, `close_deps` | 3 |
| `travelkaki/llm/cap.py` | daily cap counter | 5 |
| `travelkaki/llm/client.py` | LiteLLM wrapper, retries, fallback | 5 |
| `travelkaki/ingest/captions.py` | oEmbed + yt-dlp | 6 |
| `travelkaki/ingest/extract.py` | prompt, schema, pydantic | 6 |
| `travelkaki/ingest/pipeline.py` | steps, statuses, `PipelineResult` | 8, 14, 15 |
| `travelkaki/bot/cards.py` | card text, keyboards, messages | 9 |
| `travelkaki/bot/links.py` | link detection, `/add`, mention add | 10 |
| `travelkaki/bot/results.py` | run pipeline + post cards/errors | 10 |
| `travelkaki/bot/votes.py` | callbacks, `/places` | 11 |
| `travelkaki/geo/distance.py` | haversine, viewbox | 13 |
| `travelkaki/geo/nominatim.py` | search, rate limit, confidence | 13 |
| `travelkaki/ingest/dedupe.py` | name normalising, duplicate find | 14 |
| `tests/conftest.py` | `sessions` fixture (in-memory SQLite) | 1 |

---

## PR1 — branch `m1-pr1` — #6, #7, #9

### Task 1: Settings, DB tables, trip/source queries (#6)

**Files:**
- Modify: `travelkaki/config.py`, `.env.example`, `Dockerfile`, `pyproject.toml` (move `httpx` to main deps; add `yt-dlp`; add pytest marker `live` and `addopts = "-m 'not live'"`)
- Create: `travelkaki/db/base.py`, `travelkaki/db/models.py`, `travelkaki/db/queries.py`, `tests/conftest.py`
- Test: `tests/test_config.py`, `tests/test_db.py`

**Interfaces:**
- Produces:
  - `Settings` fields: `database_url: str`, `extract_model: str`, `extract_fallback_model: str | None`, `ollama_base_url: str`, `llm_daily_cap: int`, `nominatim_email: str | None` (defaults per Global Constraints).
  - `db.base`: `class Base(DeclarativeBase)`, `make_engine(url: str) -> Engine` (sqlite: creates the parent folder, `check_same_thread=False`; `sqlite://` in-memory uses `StaticPool`), `make_sessions(engine) -> sessionmaker[Session]` (`expire_on_commit=False`), `init_db(engine) -> None`.
  - `db.models`: `SourceStatus(StrEnum)` = pending, caption, done, failed. `Confidence(StrEnum)` = high, low, far, none. `VoteValue(StrEnum)` = must, maybe, skip. Tables `Trip, Source, Place, PlaceSource, Vote, LlmUsage` with the spec's fields. `Place.confidence` defaults to `none`. `Source.status` defaults to `pending`.
  - `db.queries`: `get_trip(s, chat_id) -> Trip | None`. `upsert_trip(s, chat_id, city, start, end, hotel, city_lat=None, city_lng=None) -> Trip`. `add_source(s, trip_id, url, platform, added_by) -> Source | None` (None = duplicate). `get_source(s, source_id) -> Source | None`. `set_source(s, source_id, *, status, error=None, caption=None) -> None`. `mark_interrupted(s) -> list[tuple[int, int]]` (source_id, chat_id) of the sources it marked.
  - Every query function commits its own change.

- [ ] **Step 1: Write failing tests**
  - `test_config.py::test_m1_defaults`: `extract_model == "ollama_chat/qwen3:4b-instruct"`, `llm_daily_cap == 100`, `database_url == "sqlite:///data/travelkaki.db"`, `extract_fallback_model is None`.
  - `conftest.py`: fixture `sessions` = `make_sessions(make_engine("sqlite://"))` after `init_db`.
  - `test_db.py::test_upsert_trip_updates_and_keeps_id`: two upserts for chat 1 → same `id`, city changes "Tokyo" → "Osaka".
  - `test_db.py::test_add_source_duplicate_returns_none`: the same (trip, url) twice → second is `None`. A different trip with the same url → saved.
  - `test_db.py::test_mark_interrupted`: sources in `pending` and `caption` → `failed` with `error == "interrupted"`. `done` is untouched. Returns 2 `(source_id, chat_id)` pairs.
  - `test_db.py::test_make_engine_creates_sqlite_folder(tmp_path)`: `sqlite:///{tmp_path}/x/y.db` → folder `x` exists.
- [ ] **Step 2: Run** `uv run pytest tests/test_db.py tests/test_config.py -q` → FAIL (import errors).
- [ ] **Step 3: Implement** the files above. In the Dockerfile, before `USER app`: `RUN mkdir -p /app/data && chown app /app/data`. Add the new settings to `.env.example` with one comment line each.
- [ ] **Step 4: Run** the tests again → PASS. Then the full suite + ruff → clean.
- [ ] **Step 5: Commit** `git add <paths>` → `git commit -m "Add DB tables, trip/source queries and M1 settings (#6)"`.

### Task 2: URL normaliser + platform detection (#9)

**Files:** Create `travelkaki/ingest/urls.py`. Test `tests/test_urls.py`.

**Interfaces:**
- Produces:
  - `Platform = Literal["tiktok", "instagram"]`
  - `class LinkError(Exception)`. Raised when a short link can't be resolved.
  - `canonical(url: str) -> tuple[str, Platform] | None`. Pure. `None` = not a TikTok/IG post.
  - `needs_redirect(url: str) -> bool`. True for `vm.tiktok.com`, `vt.tiktok.com`, `tiktok.com/t/`, `instagram.com/share/`.
  - `async resolve(url: str, client: httpx.AsyncClient) -> str`. GET with `follow_redirects=True`, 10 s timeout. Returns the final URL. `httpx.HTTPError` → `LinkError`.
  - `async normalise(url: str, client) -> tuple[str, Platform] | None`. Resolves first if needed, then `canonical`.

- [ ] **Step 1: Failing tests** (`canonical` input → expected):
  - `https://www.tiktok.com/@a.b/video/7312345678901234567?is_from_webapp=1` → `("https://www.tiktok.com/@a.b/video/7312345678901234567", "tiktok")`
  - `https://tiktok.com/@a.b/video/7312345678901234567/` → same as above
  - `https://www.instagram.com/reel/C1a2B3c4D5e/?igsh=abc` → `("https://www.instagram.com/reel/C1a2B3c4D5e/", "instagram")`
  - `https://instagram.com/reels/C1a2B3c4D5e` → `("https://www.instagram.com/reel/C1a2B3c4D5e/", "instagram")`
  - `https://www.instagram.com/p/aye83DjauH/` → `("https://www.instagram.com/p/aye83DjauH/", "instagram")`
  - `https://www.youtube.com/watch?v=x`, `https://www.tiktok.com/@a.b` (profile, not a post) → `None`
  - `needs_redirect`: True for `https://vm.tiktok.com/ZMabc123/`, `https://www.tiktok.com/t/ZTabc/`, `https://www.instagram.com/share/reel/BAxyz/`. False for a canonical TikTok URL.
  - `normalise` with `httpx.MockTransport` redirecting `vm.tiktok.com/ZMabc123/` → the full video URL → canonical tuple.
  - `normalise` with a transport raising `httpx.ConnectError` → `pytest.raises(LinkError)`.
- [ ] **Step 2: Run** `uv run pytest tests/test_urls.py -q` → FAIL.
- [ ] **Step 3: Implement.** Use `urllib.parse`. Regexes: TikTok path `^/@([^/]+)/video/(\d+)`; IG path `^/(reel|reels|p)/([A-Za-z0-9_-]+)`. Hosts are compared without `www.`/`m.`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `"Add URL normaliser and platform detection (#9)"`.

### Task 3: `/newtrip`, Deps wiring, command menu, command logging (#7)

**Files:**
- Create: `travelkaki/bot/trip.py`, `travelkaki/deps.py`
- Modify: `travelkaki/bot/app.py`, `travelkaki/bot/handlers.py` (log line in `start`), `travelkaki/web/app.py`
- Test: `tests/test_trip.py`, `tests/test_app.py`

**Interfaces:**
- Consumes: `db.base.*`, `queries.upsert_trip`, `queries.mark_interrupted`, `Settings`.
- Produces:
  - `@dataclass NewTrip: city: str; start: date | None; end: date | None; hotel: str | None`
  - `class TripParseError(ValueError)`. Its message is shown to the user as-is.
  - `parse_newtrip(text: str, today: date) -> NewTrip`
  - `async newtrip(update, context) -> None`. Uses `context.bot_data["deps"].sessions`.
  - `deps.Deps` dataclass: `sessions: sessionmaker`, `http: httpx.AsyncClient`, `llm: object | None`, `geo: object | None`, `fetch_caption: Callable | None`, `daily_cap: int`, `interrupted: list[tuple[int, int]]` (default empty). Later tasks fill in `llm`, `fetch_caption`, `geo`. Pipeline calls `deps.fetch_caption(url, platform, deps.http)`.
  - `deps.build_deps(settings) -> Deps`: make the engine, `init_db`, `interrupted = mark_interrupted(...)`, open the httpx client. `async deps.close_deps(d) -> None`.
  - `bot.app.build_application(token: str, deps: Deps | None = None) -> Application`. Stores `deps` in `bot_data["deps"]`.
  - `bot.app.COMMANDS: list[BotCommand]` = start, newtrip, add, places. `async register_commands(app) -> None` calls `set_my_commands`. The lifespan calls it after `start()`. PTB's `post_init` does not run with a manual start.

- [ ] **Step 1: Failing tests** (`today = date(2026, 10, 4)`):
  - `"Tokyo 12-15 Dec"` → `NewTrip("Tokyo", date(2026,12,12), date(2026,12,15), None)`
  - `"Tokyo 12 Dec - 3 Jan"` → start `2026-12-12`, end `2027-01-03`
  - `"New York 3-7 Jan hotel The Plaza"` → `NewTrip("New York", date(2027,1,3), date(2027,1,7), "The Plaza")`
  - `"Seoul 5 Mar"` → start = end = `2027-03-05`
  - `"Kyoto"` → dates `None`, hotel `None`
  - `"Osaka 15-12 Dec"` and `""` → `TripParseError`. The empty-string message contains `/newtrip Tokyo 12-15 Dec`.
  - `test_newtrip_saves_trip_and_replies`: fake update (`effective_chat.id=1`, `effective_message.reply_text=AsyncMock()`), `context.args=["Tokyo","12-15","Dec"]`, `bot_data={"deps": Deps(sessions=...)}` → trip saved, reply contains "Tokyo".
  - `test_newtrip_bad_input_replies_error` → reply text = the error message, nothing saved.
  - `test_app.py::test_registers_m1_commands`: `{c.command for c in COMMANDS} == {"start","newtrip","add","places"}`. `build_application` has a `CommandHandler` for `newtrip`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Date pattern: `D-D Mon`, `D Mon - D Mon` (`-`, `–` or `to`), or `D Mon`. Month = first 3 letters, case-insensitive. Two simple regexes are fine. Only the test results matter.
  City = the text before the match, hotel = the text after the word `hotel`. Year: start in this year unless it's before `today` (then next year). End year bumps if end < start. End < start after bumping (e.g. `15-12 Dec`) → error `"End date is before start date. Example: /newtrip Tokyo 12-15 Dec"`.
  `web/app.py` lifespan: `deps = build_deps(settings)` before the bot. Pass it to `build_application`. `await close_deps(deps)` in `finally`. With `RUN_BOT=false`, still build and close deps.
- [ ] **Step 4: Run** the full suite + ruff → PASS.
- [ ] **Step 5: Commit** `"Add /newtrip, deps wiring and command menu (#7)"`.

### Task 4: PR1 ship

- [ ] Rebuild Docker: `docker compose up -d --build`. In the test group: `/newtrip Tokyo 12-15 Dec` → reply. `docker exec travelkaki-travelkaki-1 python -c "import sqlite3;print(sqlite3.connect('data/travelkaki.db').execute('select city,start_date from trip').fetchall())"` shows the row. The logs show `newtrip chat=…` and no message text.
- [ ] README: new settings + the Linux `./data` note (`sudo chown 1000:1000 data`).
- [ ] Push, `gh pr create` ("Closes #6 #7 #9"), wait for CI green, merge, and comment results on #6 #7 #9.

---

## PR2 — branch `m1-pr2` — #11, #10

### Task 5: LLM cap + client (#11)

**Files:** Create `travelkaki/llm/cap.py`, `travelkaki/llm/client.py`. Test `tests/test_llm.py`.

**Interfaces:**
- Produces:
  - `class CapReached(Exception)`. `make_counter(sessions, trip_id: int, cap: int, today: Callable[[], date] = date.today) -> Callable[[], None]`. Each call adds 1 to `LlmUsage(trip_id, today)`. If the count is already ≥ cap, it raises `CapReached` and does not count.
  - `class LlmUnavailable(Exception)`.
  - `class LlmClient(settings, completion=litellm.acompletion, sleep=asyncio.sleep)`.
  - `async LlmClient.extract_json(messages: list[dict], schema: dict, on_call: Callable[[], None]) -> dict`.
  - Order: primary up to 2 tries (sleep 1 s, then 3 s between tries) → fallback 1 try if set → `LlmUnavailable`. `on_call()` runs before **every** try. `CapReached` propagates at once.
  - kwargs: `model`, `messages`, `response_format={"type":"json_schema","json_schema":{"name":"extraction","schema":schema}}`, `timeout=60`, `temperature=0`. `api_base=ollama_base_url` when the model starts with `ollama`, else `api_key=llm_api_key`.
  - Retryable failures: any exception from `completion`, plus `json.JSONDecodeError` on `choices[0].message.content`.

- [ ] **Step 1: Failing tests** (fake `completion` AsyncMock, fake `sleep`):
  - `test_returns_parsed_json`: content `'{"places": []}'` → `{"places": []}`. Called once. `api_base` passed for the ollama model.
  - `test_retries_then_fallback`: primary raises twice, fallback returns JSON → result ok. Models called = `[primary, primary, fallback]`. Sleeps `[1, 3]`. `on_call` called 3 times.
  - `test_no_fallback_raises_unavailable`: primary bad JSON twice, no fallback → `LlmUnavailable`.
  - `test_cap_stops_calls`: `make_counter(cap=2)`: 2 calls ok, the 3rd → `CapReached`. A new day (fake `today`) → ok again.
  - `test_cap_reached_propagates`: `on_call` raises `CapReached` → raised, `completion` never called.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `"Add LLM client with retries, fallback and daily cap (#11)"`.

### Task 6: Captions + extraction (#10)

**Files:** Create `travelkaki/ingest/captions.py`, `travelkaki/ingest/extract.py`, `tests/fixtures/captions.json`, `scripts/try_link.py`. Modify `travelkaki/deps.py` (fill `llm`, `fetch_caption`). Test `tests/test_captions.py`, `tests/test_extract.py`, `tests/test_live.py`.

**Interfaces:**
- Produces:
  - `@dataclass Caption: text: str; author: str | None`
  - `async fetch_caption(url: str, platform: Platform, client: httpx.AsyncClient) -> Caption | None`. TikTok: GET `https://www.tiktok.com/oembed?url=<url>` → `title`, `author_name`. IG: `asyncio.to_thread` running yt-dlp `YoutubeDL({"quiet":True,"skip_download":True}).extract_info(url, download=False)` → `description`, `uploader`. Any error or empty text → `None`.
  - `class ExtractedPlace(BaseModel)`: `name, category, city, video_note: str`. `class Extraction(BaseModel)`: `places: list[ExtractedPlace]`. `SCHEMA = Extraction.model_json_schema()`.
  - `build_messages(city: str, caption: str) -> list[dict]`. System prompt from the spike (trip city, only places named in the text, `video_note` ≤ 15 words). Caption cut to 2000 chars.
  - `async extract_places(llm, city, caption, on_call) -> list[ExtractedPlace]`. pydantic `ValidationError` → `LlmUnavailable`. Notes trimmed to 15 words. Places with an empty name dropped. **No** 10-cap here (the pipeline counts extras).

- [ ] **Step 1: Failing tests:**
  - `fetch_caption` TikTok with `httpx.MockTransport` returning `{"title":"Ichiran 🍜","author_name":"foodie"}` → `Caption("Ichiran 🍜","foodie")`. Status 404 → `None`.
  - IG: monkeypatch `captions._ytdlp_info` (a small sync helper) → `{"description":"x","uploader":"y"}` → `Caption("x","y")`. Raising → `None`.
  - `build_messages("Tokyo", "a"*5000)`: the user content length is 2000 and "Tokyo" is in the system content.
  - `extract_places` with fake llm returning 2 places, one note of 20 words → 2 places, note has 15 words. Fake returning `{"wrong": 1}` → `LlmUnavailable`.
  - `test_live.py` (`@pytest.mark.live`): real `LlmClient(get_settings())` on each fixture caption. Each expected name is found (case-insensitive substring).
  - `tests/fixtures/captions.json`: 5 entries `{caption, city, expected:[names]}`. Include the Tokyo spike caption.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** `scripts/try_link.py <url> <city>`: normalise → caption → extract → print JSON. Uses real settings.
- [ ] **Step 4: Run** the suite → PASS. Locally: `OLLAMA_BASE_URL=http://localhost:11434 uv run pytest -m live -q` → PASS. If LiteLLM doesn't pass `json_schema` through to Ollama, switch the Ollama path to `format=schema` via `extra_body`, then note it on #11.
- [ ] **Step 5: Commit** `"Add caption fetching and LLM place extraction (#10)"`.

### Task 7: PR2 ship

- [ ] On the Mac: `uv run python scripts/try_link.py <real TikTok travel link> Tokyo` and the same with a real IG reel. Paste the JSON output into #10.
- [ ] PR ("Closes #10 #11"), CI green, merge, comment.

---

## PR3 — branch `m1-pr3` — #8, #14 (demo)

### Task 8: Pipeline v1 + place/vote queries

**Files:** Create `travelkaki/ingest/pipeline.py`. Modify `travelkaki/db/queries.py` (if it would pass 200 lines, put place/vote queries in `db/place_queries.py`). Test `tests/test_pipeline.py`, `tests/test_db.py`.

**Interfaces:**
- Consumes: `Deps`, `fetch_caption`, `extract_places`, `make_counter`, `CapReached`, `LlmUnavailable`.
- Produces:
  - queries: `add_place(s, trip_id, *, name, category, video_note, lat=None, lng=None, address=None, confidence=Confidence.none) -> Place`. `link_source(s, place_id, source_id)`. `trip_places(s, trip_id) -> list[Place]`. `get_place(s, place_id) -> Place | None`. `vote(s, place_id, user_id, value) -> VoteCounts` (toggle: same value removes). `@dataclass VoteCounts: must:int; maybe:int; skip:int`. `vote_counts(s, place_id) -> VoteCounts`. `places_with_counts(s, trip_id) -> list[tuple[Place, VoteCounts]]`. `clear_pin(s, place_id) -> Place | None`. `reset_source(s, source_id)` (back to `pending`, error `None`).
  - pipeline error codes (str constants): `NO_CAPTION="no_caption"`, `LLM_UNAVAILABLE="llm_unavailable"`, `CAP_REACHED="cap_reached"`, `NO_PLACES="no_places"`, `UNKNOWN="unknown"`.
  - `@dataclass PipelineResult: places: list[Place]; merged: list[str]; extra: int; error: str | None; author: str | None`
  - `async run(source_id: int, deps: Deps) -> PipelineResult`. Sets status `caption` → fetch → store caption → extract → save places + `link_source` → `done`. On any error: status `failed` + error code. Unexpected exceptions are logged with a traceback → `UNKNOWN`. Only the first 10 places go into `places`. `extra` = the rest, which are still saved.
  - `async add_by_name(trip_id: int, name: str, deps) -> PipelineResult`. Saves one place with category `"place"` and an empty note.
  - Internal `async _save(trip, extracted, source_id, deps) -> Place | str`. Returns the new `Place`, or the merged name (always a new Place until Task 14).

- [ ] **Step 1: Failing tests** (fakes via `Deps(sessions, http=None, llm=FakeLlm, fetch_caption=fake, geo=None, daily_cap=100)`):
  - happy path: 2 places → `result.places` names, source `done`, caption stored, 2 `PlaceSource` rows.
  - `fetch_caption → None` → `error == "no_caption"`, source `failed`/`no_caption`.
  - llm raises `LlmUnavailable` → `"llm_unavailable"`. `daily_cap=0` → `"cap_reached"`.
  - llm returns 0 places → `"no_places"`.
  - 12 places → `len(places) == 10`, `extra == 2`, 12 rows saved.
  - `fetch_caption` raises `RuntimeError` → `"unknown"`, source `failed`.
  - `test_db.py::test_vote_toggle`: must → `VoteCounts(1,0,0)`. Same again → `(0,0,0)`. Then skip → `(0,0,1)`. Two users → counts add up.
- [ ] **Steps 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `"Add ingest pipeline and place/vote queries"`.

### Task 9: Cards and messages

**Files:** Create `travelkaki/bot/cards.py`. Test `tests/test_cards.py`.

**Interfaces:**
- Produces:
  - `maps_url(place, city) -> str`. With coords: `https://www.google.com/maps/search/?api=1&query=<lat>,<lng>`. Without: `query=<urlencoded "name, city">`.
  - `card_text(place, city, poster: str | None, platform: str | None) -> str` (HTML).
    - Line 1 `📍 <b>{name}</b> · {category}`.
    - Line 2 `“{video_note}”` if any.
    - Line 3 `from {poster}'s {TikTok|Instagram} · <a href="{maps}">Map ↗</a>`. A text add shows only the map link.
    - `low` adds `Is this right? {address}`. `far` adds `⚠️ Not near {city}`.
  - `card_keyboard(place, counts) -> InlineKeyboardMarkup`. Row `✅ Must n`/`🤔 Maybe n`/`❌ Skip n` with data `v:{id}:m|y|s`. `low`/`far` add a row `👎 Wrong place` (`w:{id}`).
  - `ERRORS: dict[str, str]` with the spec's exact copy (keys = error codes + `interrupted`, `link_error`. Test: every code in `pipeline` has an entry). `link_error` = "Couldn't open that link. Try again in a minute."
  - `retry_keyboard(source_id) -> InlineKeyboardMarkup` (`🔁 Retry`, `r:{id}`).
  - `places_text(rows: list[tuple[Place, VoteCounts]], city) -> list[str]`. Sorted by (must, maybe) descending. `skip > must` goes under `<b>Skipped</b>`. Chunks ≤ 4096 chars. Empty list → `["No places yet. Post a TikTok or IG link!"]`.
  - `parse_callback(data: str) -> tuple[str, int, str | None] | None`. Bad data → `None`.
- [ ] **Step 1: Failing tests:**
  - A name `Bar <Ishi> & *Co*` shows up escaped (`&lt;Ishi&gt; &amp;`) in `card_text`. (Review Focus 3)
  - `low` text contains "Is this right?" and the keyboard has 2 rows. `high` has 1 row.
  - Callback data are all ≤ 64 bytes for id `10**9`.
  - `places_text` order: A(must 2), B(must 1, maybe 3), C(skip 2, must 0) → A before B, C after "Skipped". 300 places → every chunk ≤ 4096.
  - `parse_callback("v:12:m") == ("v", 12, "m")`. `parse_callback("x") is None`. `parse_callback("v:abc:m") is None`.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `"Add place cards, keyboards and messages"`.

### Task 10: Link detection, `/add`, mention add, posting results (#8)

**Files:** Create `travelkaki/bot/links.py`, `travelkaki/bot/results.py`. Modify `travelkaki/bot/app.py`. Test `tests/test_links.py`.

**Interfaces:**
- Consumes: `urls.normalise`, `LinkError`, `queries.get_trip/add_source`, `pipeline.run/add_by_name`, `cards.*`.
- Produces:
  - `find_links(message) -> list[str]`. From `message.entities`/`caption_entities` of type `url` (the text slice) and `text_link` (`entity.url`), via `message.parse_entities`/`parse_caption_entities`. Max 5.
  - `parse_mention_add(text: str, bot_username: str) -> str | None`. Case-insensitive `@{bot_username} add <name>` → name.
  - `async on_message(update, context)`. Registered as `MessageHandler(filters.UpdateType.MESSAGE & (filters.TEXT | filters.CAPTION) & ~filters.COMMAND, on_message)`.
  - `async add_command(update, context)`. `/add <link>` → link flow. `/add <name>` → text add. No args → usage reply.
  - `async handle_link(url, update, context) -> None`. The spec's link flow, steps 2–5. **Deviation from spec (agreed reason):** `urls.normalise` runs here, not in the pipeline, because the duplicate check needs the canonical URL. `LinkError` → reply `ERRORS["link_error"]`. Reaction: `context.bot.set_message_reaction(chat_id, message_id, "👀")` in try/except `TelegramError`. Background: `context.application.create_task(post_pipeline(...))`.
  - `results.post_pipeline(bot, chat_id: int, reply_to: int, source_id: int, poster: str | None, platform: str, deps) -> None`. Runs `pipeline.run`. Error → `ERRORS[code]` (+ `retry_keyboard` for `llm_unavailable`, `unknown`, `interrupted`). Else one card per place, a line per merged name, and "+N more, see /places".
  - `results.post_text_add(bot, chat_id, reply_to, trip_id, name, deps) -> None`.
- [ ] **Step 1: Failing tests** (fake update/context, `deps` with in-memory DB, `context.application.create_task` = a list-append fake, `context.bot` AsyncMocks):
  - text with a TikTok `url` entity + an existing trip → source row saved, `set_message_reaction` awaited, 1 task created.
  - no trip → reply contains `/newtrip Tokyo 12-15 Dec`, no source rows.
  - same link twice → second reply "Already saved ✅".
  - YouTube link → no reply, no rows.
  - `set_message_reaction` raising `BadRequest` → still 1 task created.
  - `parse_mention_add("@TravelKakiiBot add Ichiran Shibuya", "travelkakiibot") == "Ichiran Shibuya"`. Plain chat text → `None`. Neither creates a source.
  - Review Focus 1: build the app and check that the `on_message` handler's filter rejects an `Update` with `edited_message` (`handler.check_update(update)` is falsy).
  - `post_pipeline` with a fake result of 2 places → 2 `send_message` calls with `parse_mode="HTML"` and `reply_markup`. Error `llm_unavailable` → 1 message with the Retry keyboard.
- [ ] **Steps 2–5:** FAIL → implement (register `CommandHandler("add")` + `MessageHandler` in `build_application`) → PASS → commit `"Detect links, /add and mention adds, post place cards (#8)"`.

### Task 11: Votes + `/places` (#14)

**Files:** Create `travelkaki/bot/votes.py`. Modify `travelkaki/bot/app.py` (`CallbackQueryHandler(on_callback)`, `CommandHandler("places")`). Test `tests/test_votes.py`.

**Interfaces:**
- Produces: `async on_callback(update, context)`. Dispatches on `parse_callback`:
  - `v` → `queries.vote`, then `query.answer("Voted Must-go" | "Vote removed" | …)`, then `query.edit_message_reply_markup(card_keyboard(...))`.
  - `w` and `r` are wired in Tasks 14–15. Until then: `query.answer()`.
  - Unknown data or a missing place → `query.answer("This place no longer exists.")`.
  - `async places_command(update, context)`. No trip → the same "start a trip" text. Else send each chunk of `places_text` with HTML.
- [ ] **Step 1: Failing tests:** vote → `edit_message_reply_markup` awaited with Must count 1. Same tap → count 0 + toast "Vote removed". Place id 999 → toast "This place no longer exists." and no edit (Review Focus 4). `/places` with 2 places → 1 message containing both names.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `"Add vote buttons and /places (#14)"`.

### Task 12: PR3 ship (demo)

- [ ] `docker compose up -d --build`. In the test group: `/newtrip Tokyo 12-15 Dec`, post a real TikTok travel link → 👀 → cards. Vote from 2 accounts if possible. `/places` shows the counts. Post an IG reel too. Try `@travelkakiibot add Ichiran Shibuya`.
- [ ] Screenshots to #8 and #14. PR ("Closes #8 #14"), CI green, merge.

---

## PR4 — branch `m1-pr4` — #12, #13, #15

### Task 13: Distance + Nominatim (#12)

**Files:** Create `travelkaki/geo/distance.py`, `travelkaki/geo/nominatim.py`. Modify `travelkaki/deps.py` (`geo`), `travelkaki/bot/trip.py` (geocode the city on `/newtrip`). Test `tests/test_geo.py`.

**Interfaces:**
- Produces:
  - `distance_m(a: tuple[float, float], b: tuple[float, float]) -> float` (haversine, metres). `viewbox(center, km=50) -> tuple[float, float, float, float]` as (left_lon, top_lat, right_lon, bottom_lat).
  - `@dataclass GeoResult: lat: float; lng: float; address: str`
  - `class Nominatim(client, email: str | None, min_interval=1.0, clock=time.monotonic, sleep=asyncio.sleep)`.
  - `async search(query: str, box: tuple | None = None) -> GeoResult | None`. GET `https://nominatim.openstreetmap.org/search` with `format=jsonv2`, `limit=1`, `viewbox` + `bounded=1` when a box is given. User-Agent `TravelKaki/0.1 (+https://github.com/Soba101/TravelKaki; {email})`. An `asyncio.Lock` + sleep keeps calls ≥ `min_interval` apart. In-memory dict cache keyed by (query, box). HTTP error → `None`.
  - `async locate(name: str, city: str, center: tuple | None) -> tuple[GeoResult | None, Confidence]`. The spec's rule: bounded hit → `high`. Else unbounded: ≤ 50 km → `low`, > 50 km → `far`, none → `none`. `center=None` → unbounded hit = `low`.
- [ ] **Step 1: Failing tests:**
  - `distance_m` Shibuya (35.6595, 139.7005) ↔ Shinjuku (35.6896, 139.7006) ≈ 3350 m ± 50.
  - `search` with `MockTransport`: the params include `bounded=1` when boxed, and the UA contains "TravelKaki". A second identical call → no second request (cache).
  - Rate limit: fake clock at 0.0 for both calls → `sleep` awaited with ≈ 1.0 before the second distinct query.
  - `locate`: bounded hit → `high`. Bounded miss + unbounded hit 10 km away → `low`. 400 km → `far`. Both miss → `(None, none)`.
  - `/newtrip` with a fake geo → the trip has `city_lat`/`city_lng`. Geo returning `None` → the trip still saves.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `"Add Nominatim geocoding with confidence rules (#12)"`.

### Task 14: Dedupe + geocode in the pipeline + wrong-place button (#13)

**Files:** Create `travelkaki/ingest/dedupe.py`. Modify `travelkaki/ingest/pipeline.py` (`_save`), `travelkaki/bot/votes.py` (`w`). Test `tests/test_dedupe.py`, `tests/test_pipeline.py`, `tests/test_votes.py`.

**Interfaces:**
- Produces:
  - `normalise_name(name: str) -> str`. casefold, drop punctuation (keep letters/digits of any script), collapse spaces.
  - `find_duplicate(name, lat, lng, places: list[Place]) -> Place | None`. Same normalised name and (both have coords and are ≤ 100 m apart, or both have no coords).
  - `_save` now: `deps.geo.locate(name, trip.city, center)` (skipped if `deps.geo is None`) → `find_duplicate` against `trip_places` → if found: `link_source` + return the name; else `add_place` with coords/address/confidence.
  - `w` callback: `clear_pin`, then edit the message text to the original `query.message.text_html` + `"\n❌ Pin removed"`, keeping the vote row only. Toast "Pin removed".
- [ ] **Step 1: Failing tests:**
  - `normalise_name("Ichiran, Shibuya!") == normalise_name("ichiran  shibuya") == "ichiran shibuya"`. `normalise_name("一蘭 渋谷")` stays non-empty.
  - `find_duplicate`: same name 50 m away → match. Same name 500 m away → `None`. Different name 0 m → `None`. Both no coords → match.
  - Pipeline: an existing "Ichiran Shibuya" at the same coords + an extracted "ichiran shibuya" → `result.merged == ["ichiran shibuya"]`, no new place, a `PlaceSource` added to the existing one.
  - Pipeline with fake geo `low` → the saved place has confidence `low` and the address.
  - `w` callback → place lat/lng `None`, confidence `none`, toast "Pin removed".
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `"Dedupe places and geocode them in the pipeline (#13)"`.

### Task 15: Retry + interrupted (#15)

**Files:** Modify `travelkaki/bot/votes.py` (`r`), `travelkaki/bot/results.py`. Test `tests/test_votes.py`, `tests/test_pipeline.py`.

**Interfaces:**
- Produces: `r` callback → `queries.reset_source`, then `query.answer("Retrying…")`, `query.edit_message_reply_markup(None)`, `context.application.create_task(post_pipeline(..., source_id, poster=None, platform=source.platform))`. If the source is missing or already `done` → toast "Nothing to retry."
- `results.announce_interrupted(bot, deps) -> None`: for each `(source_id, chat_id)` in `deps.interrupted`, send `ERRORS["interrupted"]` ("I restarted while reading a link. Tap Retry to try again.") with `retry_keyboard(source_id)`. The lifespan calls it after `register_commands`. Telegram errors per chat are logged and skipped.
- [ ] **Step 1: Failing tests:** `announce_interrupted` with 2 items → 2 `send_message` calls carrying `r:<id>` buttons. A failed source + `r` tap → status `pending`, 1 task created, markup removed. A `done` source → toast "Nothing to retry.", no task. End to end with fakes: fail (`llm_unavailable`) → retry with a working fake LLM → `done` and places saved.
- [ ] **Steps 2–5:** FAIL → implement → PASS → commit `"Add per-link retry (#15)"`.

### Task 16: PR4 ship + M1 close-out

- [ ] Docker rebuild. Live checks: a link with a famous place (`high` pin, Map link opens the right spot), a vague name (`low` prompt, 👎 works), the same place from 2 links (merge message). Stop Ollama → post a link → "AI model unreachable" + Retry. Start Ollama → Retry → cards.
- [ ] Screenshots + results to #12 #13 #15. PR ("Closes #12 #13 #15"), CI green, merge.
- [ ] Update `Brain/Projects/TravelKaki.md` and the Project handoff. M1 milestone: 0 open.
