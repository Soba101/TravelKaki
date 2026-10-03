# M0 Skeleton — Design

**Date:** 2026-10-04 · **Milestone:** M0 (due 2026-10-11) · **Issues:** #2, #3, #4, #5
**Status:** approved by Donovan in chat.

## Goal

A clean, runnable base for M1.
Done when: `docker compose up` starts the bot, `/start` replies, `/health` is ok, CI is green.

Not in M0: database tables, LLM calls, ingest, planner. Those packages are empty.

## Decisions

| Topic | Choice | Why |
|---|---|---|
| Layout | One parent package `travelkaki/` | Avoids clashes with generic names like `db`, `web`. |
| Deps tool | `uv` + `uv.lock` | Same commands locally, in Docker and in CI. |
| Python | 3.12 | Current stable, good library support. |
| Bot + API | FastAPI lifespan starts/stops the bot | One command (`uvicorn`), clean shutdown. |
| Bot mode | Polling | No open ports needed. |
| API in M0 | Only `GET /health` | Proves bot + API share one process. Docker healthcheck uses it. |

## Files

```
travelkaki/
  __init__.py
  config.py          # reads .env into one Settings object
  main.py            # entry point: exposes `app` for uvicorn
  bot/
    __init__.py
    handlers.py      # /start handler + welcome text
    app.py           # builds the telegram Application
  web/
    __init__.py
    app.py           # FastAPI app, /health, lifespan that runs the bot
  ingest/ geo/ planner/ db/ llm/   # __init__.py only, one-line note each
tests/
  test_config.py  test_start.py  test_health.py
pyproject.toml  uv.lock  Dockerfile  docker-compose.yml  .env.example
.github/workflows/ci.yml
```

Every file stays under 200 lines.

## Behaviour

- **Config:** `TELEGRAM_BOT_TOKEN` is required. Missing → clear error at startup.
  Optional: `LLM_API_KEY`, `GOOGLE_MAPS_API_KEY`, `VIDEO_FETCH` (default `false`).
- **/start:** replies with a welcome. It says what TravelKaki stores
  (links, extracted places, votes, plans), that other messages are ignored, and that `/forget` deletes a trip.
- **/health:** returns `{"ok": true}`.
- **Bot off switch for tests:** the lifespan only starts the bot when a token is set
  and `RUN_BOT` is not `false`. Tests set `RUN_BOT=false`.

## Docker

- Image built with uv. Runs `uvicorn travelkaki.main:app --host 0.0.0.0 --port 8000`.
- Compose reads `.env`. Port bound to `127.0.0.1:8000` only.
- Healthcheck hits `/health`. Memory limit 512 MB.

## CI

`.github/workflows/ci.yml` on push and PR: `uv sync`, `ruff check`, `ruff format --check`, `pytest`.

## Tests (no network, no Telegram)

1. Missing token → config error.
2. `/start` handler replies with text containing the privacy notice (fake update object).
3. `/health` returns ok (FastAPI TestClient, `RUN_BOT=false`).

## Manual steps (Donovan)

- Create the bot in BotFather; check `@TravelKakiBot` is free.
- Put the token in `.env`, run `docker compose up`, send `/start`.
