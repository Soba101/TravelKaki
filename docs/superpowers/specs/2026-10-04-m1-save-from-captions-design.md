# M1 Save from Captions — Design

**Date:** 2026-10-04 · **Milestone:** M1 (due 2026-10-25) · **Issues:** #6–#15
**Status:** design approved by Donovan in chat. Spec awaiting review.

## Goal

A friend posts a TikTok or Instagram link in the group. The bot finds the places, saves them,
and anyone can vote Must-go / Maybe / Skip. `/places` shows the tally.

**Done when:** a real TikTok link and a real IG link in our test group → place cards appear →
votes save → `/places` shows counts. Checked on the Docker bot, screenshots in the issues.

**Not in M1:** video download / transcripts (M4), planner (M2), map (M3), Google Places
(follow-up issue), `/forget`, Alembic migrations, multiple trips per chat.

## Decisions

| Topic | Choice | Why |
|---|---|---|
| Build order | 4 thin-slice PRs (see Delivery) | Demo after PR3. Small PRs, each with tests. |
| LLM | Local first (Ollama `qwen3:4b-instruct`), optional cloud fallback | Free by default. Tested: 3/3 places, valid JSON, 7.5 s on an M2. |
| Subscriptions | Not supported | Claude Pro/Max OAuth is banned outside Claude Code / claude.ai. "Sign in with ChatGPT" is partner-only (Oct 2026). Revisit if it opens up. |
| JSON | JSON schema via LiteLLM `response_format`, then pydantic | Stricter than prompt-only JSON. |
| Geocoding | OSM Nominatim only | No Google key yet. Google Places moves to a follow-up issue. |
| DB | SQLite, sync SQLAlchemy 2.0, `create_all` | Local and fast. Migrations later, before going public. |
| Slow sync work | `asyncio.to_thread` (yt-dlp) | Keeps the bot responsive. |
| Background jobs | `application.create_task` | No queue needed in v1. |
| No trip yet | Reply "run /newtrip first", store nothing | Matches "store only trip data". |
| Progress | 👀 reaction on the link, then cards | No extra message. Ignore if reactions are restricted. |
| Reply shape | One card per place | Clean button rows on phones. |

## Data model (`db/models.py`)

| Table | Fields | Rules |
|---|---|---|
| `Trip` | id, chat_id, city, city_lat, city_lng, start_date, end_date, hotel, created_at | `chat_id` unique. `/newtrip` again updates it and keeps places. Dates and hotel optional. |
| `Source` | id, trip_id, url, platform, caption, status, error, added_by, created_at | Unique (trip_id, url). `status`: `pending → caption → done / failed`. |
| `Place` | id, trip_id, name, category, lat, lng, address, video_note, confidence, created_at | `confidence`: `high`, `low`, `far`, `none`. lat/lng null when `none`. |
| `PlaceSource` | place_id, source_id | Many-to-many. Text adds have no source. |
| `Vote` | id, place_id, tg_user_id, value | Unique (place_id, tg_user_id). `value`: `must`, `maybe`, `skip`. |
| `LlmUsage` | trip_id, day, calls | Primary key (trip_id, day). |

## Modules (each file < 200 lines)

```
travelkaki/
  config.py           # + database_url, extract_model, extract_fallback_model,
                      #   ollama_base_url, llm_daily_cap, nominatim_email
  db/base.py          # engine, session factory, init_db() (create_all)
  db/models.py        # tables above
  db/queries.py       # small named functions: get_trip, upsert_trip, add_source, vote, ...
  ingest/urls.py      # normalise + detect platform (#9)
  ingest/captions.py  # TikTok oEmbed, yt-dlp metadata for IG (#10)
  ingest/extract.py   # prompt, JSON schema, pydantic check (#10)
  ingest/dedupe.py    # same name within 100 m (#13)
  ingest/pipeline.py  # runs the steps, updates status, returns result (#15)
  llm/client.py       # LiteLLM call, retries + backoff, local → fallback (#11)
  llm/cap.py          # per-trip daily call cap (#11)
  geo/nominatim.py    # search, 1 req/s lock, viewbox, confidence (#12)
  bot/trip.py         # /newtrip + date parsing (#7)
  bot/links.py        # link detection, /add, @mention add (#8)
  bot/votes.py        # vote + wrong-place + retry callbacks, /places (#14)
  bot/cards.py        # card text + inline keyboards
```

New deps: `httpx` (moves from dev to main), `yt-dlp`.

New settings (`.env.example` updated):

| Setting | Default |
|---|---|
| `DATABASE_URL` | `sqlite:///data/travelkaki.db` |
| `EXTRACT_MODEL` | `ollama_chat/qwen3:4b-instruct` |
| `EXTRACT_FALLBACK_MODEL` | empty (no fallback) |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` |
| `LLM_API_KEY` | empty. Passed to LiteLLM as `api_key` for non-Ollama models. |
| `LLM_DAILY_CAP` | `100` calls per trip per day |
| `NOMINATIM_EMAIL` | empty. Added to the User-Agent, as Nominatim's policy asks. |

## Bot commands

- `/newtrip Tokyo 12-15 Dec hotel Gracery Shinjuku`
  - City = text before the dates. Dates optional. Also `12 Dec - 3 Jan`.
  - No year → the next upcoming date. End before start → error with an example.
  - `hotel <name>` optional, stored as text.
  - Geocodes the city once and stores `city_lat/lng`.
- `/add <link>` → same as a posted link. `/add <name>` (no link) → text add.
- `@travelkakiibot add <name>` → text add.
- `/places` → list with vote counts.
- `set_my_commands` at startup: `/start /newtrip /add /places`.
- Each handler logs `command + chat_id` at INFO. Never message text.

## Link flow (`bot/links.py`)

1. Read `url` and `text_link` entities from the text or caption. Max 5 links per message.
2. Not TikTok/IG → ignore, store nothing.
3. No trip → "Start a trip first: `/newtrip Tokyo 12-15 Dec`".
4. Normalised URL already saved for this trip → "Already saved ✅".
5. Save `Source(pending)`, react 👀, start `pipeline.run(source_id)` as a task.

## Pipeline (`ingest/pipeline.py`)

Fixed steps. All outside calls (HTTP, LLM, geocoder) are passed in, so tests use fakes.

1. **Normalise** (`urls.py`): follow redirects for `vm.tiktok.com`, `vt.tiktok.com`,
   `tiktok.com/t/`, IG share links (httpx, 10 s timeout). Strip query and fragment.
   Canonical forms: `https://www.tiktok.com/@user/video/<id>`, `https://www.instagram.com/reel/<code>/`
   (`/p/` kept as `/p/`).
2. **Caption** (status `caption`): TikTok → `https://www.tiktok.com/oembed?url=…` (`title`, `author_name`).
   IG → yt-dlp `extract_info(download=False)` (`description`, `uploader`). Empty → fail `no_caption`.
3. **Extract** (`extract.py`): check the cap, then call the LLM with the trip city and the caption.
   Schema: `{places: [{name, category, city, video_note}]}`. `video_note` ≤ 15 words.
   Pydantic checks the output. Max 10 places are kept.
4. **Geocode** (`nominatim.py`): search `"<name>, <trip city>"` in a ~50 km viewbox around the city
   (bounded). Found → `high`. Not found → search again without the box:
   found ≤ 50 km from the city → `low`, found > 50 km away → `far`, not found → `none`.
   One shared async lock keeps it to ≤ 1 request/s. Results are cached in memory.
5. **Dedupe** (`dedupe.py`): normalise the name (lowercase, no punctuation, single spaces).
   Same normalised name within 100 m (or both without coords) → merge: add `PlaceSource`, no new card.
6. **Done**: status `done`. Post one card per new place. Merged ones → "Ichiran already saved (+1 link)".
   More than 10 → "+N more, see /places".

Text add skips steps 1–3.

## LLM client (`llm/client.py`, `llm/cap.py`)

- `extract_json(trip_id, system, user, schema) -> dict`.
- Every call (retries and fallback too) counts toward `LlmUsage`. Over the cap → `CapReached`.
- Primary model: up to 2 tries (backoff 1 s, 3 s) on connection errors or invalid JSON.
- Still failing and `EXTRACT_FALLBACK_MODEL` set → 1 try on the fallback.
- Still failing → `LlmUnavailable`.
- Timeout 60 s (the first local call loads the model).

## Errors (the bot is never silent)

Every failure sets `Source.status = failed`, stores `error`, and replies with the next step.
Failure messages carry a `[🔁 Retry]` button (`r:<source_id>`) that re-runs the pipeline.

| Error | Message |
|---|---|
| `no_caption` | "Couldn't read that post. Add by name: `@travelkakiibot add <place>`" |
| `llm_unavailable` | "AI model unreachable. Is Ollama running?" + Retry |
| `cap_reached` | "Daily AI limit reached for this trip. Add by name or try tomorrow." |
| `no_places` | "No places found in that post. Add by name: `@travelkakiibot add <place>`" |
| `interrupted` | Set at startup for sources stuck in `pending`/`caption`. Retry works. |
| Anything else | "Something went wrong reading that link." + Retry. Logged with traceback. |

## Cards and votes (`bot/cards.py`, `bot/votes.py`)

```
📍 Ichiran Shibuya · restaurant
"24h open, solo booths"
from @alex's TikTok · Map ↗
[✅ Must 2] [🤔 Maybe 0] [❌ Skip 0]
```

- Map link: Google Maps search URL with lat/lng (or name + city if no coords).
- `low` → adds "Is this right? <address>". `far` → adds "⚠️ Not near <city>". Both add `[👎 Wrong place]`.
- `[👎 Wrong place]` (`w:<place_id>`) clears lat/lng and sets `none`.
- Vote callback `v:<place_id>:<m|y|s>`. Anyone in the chat can vote.
  - New or different value → set it. Same value again → remove the vote.
  - Answer with a short toast and edit the card counts.
- `/places`: sorted by Must count, then Maybe. Places where Skip > Must go in a "Skipped" section at the end.
  Split at 4096 chars.

## Privacy

- Stored: links, the post's public caption (for Retry and the M5 evals), places, votes.
- Never stored or logged: other message text.
- Welcome text already says this. The README gets the same note.

## Docker

- Dockerfile creates `/app/data` owned by the app user.
- README: one-line `chown` fix for `./data` on Linux hosts.
- Compose already passes `.env`. Ollama is reached at `host.docker.internal`.

## Testing

- **Unit:** URL normaliser, date parsing, extraction checks, dedupe, cards and keyboards, cap,
  geocode confidence rule (fake HTTP).
- **Pipeline:** fake caption fetcher, LLM and geocoder → statuses, each error, retry, merge.
- **Handlers:** fake `Update`/`Context` → link detection, no-trip reply, duplicate link, vote toggle.
- **DB:** in-memory SQLite per test.
- **Live:** `@pytest.mark.live` runs real Ollama on fixture captions. Skipped in CI.
- No network or LLM calls in CI.

## Delivery

| PR | Issues | Done when |
|---|---|---|
| PR1 | #6 DB, #7 `/newtrip`, #9 URLs | Trip saved from a real `/newtrip`. Normaliser tests pass. |
| PR2 | #11 LLM, #10 captions + extract | A script turns a real TikTok link into places JSON. |
| PR3 | #8 links, #14 votes + `/places` | **Demo:** link → cards → votes → `/places` in the test group. |
| PR4 | #12 geocode, #13 dedupe, #15 status + retry | Pins, merges and every failure message checked live. |

Each PR: branch → PR → CI green → merge. Progress and problems are logged on the issues.
Google Places gets a new issue when #12 closes.

## Risks

| Risk | Mitigation |
|---|---|
| IG rate-limits yt-dlp | `no_caption` → add-by-name. Video fallback in M4. |
| Small local model misreads captions | Schema + pydantic. Cloud fallback setting. M5 eval measures it. |
| Nominatim misses small shops | `low`/`none` confidence shown on the card. Google Places later. |
| Telegram edit limits on busy votes | Friend-group scale. Revisit if errors show up. |
