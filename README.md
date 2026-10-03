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

## Self-hosting

Coming in M5. See [Self Hosting](../../wiki/Self-Hosting).

## Privacy

TravelKaki stores only links, extracted places, votes and plans. Other messages are ignored. `/forget` deletes a trip.

## Licence

MIT
