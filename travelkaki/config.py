"""App settings, read from environment variables or a `.env` file.

Each field below maps to an env var with the same name in UPPER CASE.
Example: `telegram_bot_token` <- TELEGRAM_BOT_TOKEN.
See `.env.example` for the full list.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Read from `.env` in the working directory. Real env vars win over the file.
    # extra="ignore": unknown keys in .env don't crash the app.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Required. From BotFather. The app refuses to start without it.
    telegram_bot_token: str

    # Optional. Your own LLM provider key (Claude / OpenAI). Not used until M1.
    llm_api_key: str | None = None

    # Optional. Google Maps/Places key. Without it we fall back to OpenStreetMap.
    google_maps_api_key: str | None = None

    # Off by default. When true, ingest may download videos (your own responsibility, see ToS).
    video_fetch: bool = False

    # Set RUN_BOT=false to start only the web API (used by tests and Docker smoke checks).
    run_bot: bool = True


@lru_cache
def get_settings() -> Settings:
    """Load settings once and reuse them (cached)."""
    return Settings()
