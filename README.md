# TravelKaki 🧳

> *CoconutSplit settles who paid. TravelKaki settles where we're going.*

An AI trip planner that lives inside your Telegram group chat.
Drop TikTok / IG links in the chat → TravelKaki pulls out the places → the group votes → an agent plans the days → see it all on a map.

**Status:** early development. See the [Roadmap](../../wiki/Roadmap) and [Milestones](../../milestones).

## How it works

- **Ingest workflow** (fixed steps): link → caption/video → places → geocode → dedupe.
- **Planner agent** (LLM picks its own tool calls): builds, checks and fixes a day-by-day plan, and asks the group when it must choose.
- **Mini app map**: pins coloured by vote, day routes, Google Maps links.

More in the [wiki](../../wiki).

## Stack

Python · python-telegram-bot · FastAPI · SQLite/SQLAlchemy · LiteLLM (your own key or Ollama) · Leaflet + OpenStreetMap

## Development

Needs [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
cp .env.example .env          # then paste your BotFather token into .env
uv sync                       # install dependencies
uv run pytest                 # tests
uv run ruff check .           # lint
uv run uvicorn travelkaki.main:app   # run bot + API (http://127.0.0.1:8000/health)
```

Or with Docker:

```bash
docker compose up --build
```

### Settings (M1)

All settings live in `.env`. See `.env.example` for the full list with comments. The main ones:

| Setting | Default | What it does |
|---|---|---|
| `EXTRACT_MODEL` | `ollama_chat/qwen3:4b-instruct` | LLM that reads captions. Local [Ollama](https://ollama.com), free. Run `ollama pull qwen3:4b-instruct` first. |
| `EXTRACT_FALLBACK_MODEL` | empty | Optional cloud model, tried once if the local one fails. Needs `LLM_API_KEY`. |
| `LLM_DAILY_CAP` | `100` | Max LLM calls per trip per day. |
| `DATABASE_URL` | `sqlite:///data/travelkaki.db` | SQLite file, in the `./data` Docker volume. |
| `NOMINATIM_EMAIL` | empty | Your email for OpenStreetMap geocoding (their policy asks for one). |

Live tests call your local Ollama and are skipped by default: `uv run pytest -m live`.

**Linux hosts:** the container runs as a normal user (uid 1000). If the bot can't create its
database, give that user the data folder: `mkdir -p data && sudo chown 1000:1000 data`.

## Self-hosting

Coming in M5. See [Self Hosting](../../wiki/Self-Hosting).

## Privacy

TravelKaki stores only links (and the post's public caption), extracted places, votes and plans. Other messages are ignored and never logged. `/forget` deletes a trip.

## Licence

MIT
