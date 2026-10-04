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
    # env_ignore_empty=True: a line like `EXTRACT_FALLBACK_MODEL=` counts as "not set",
    # so the default (often None) is used instead of an empty string. (PR1 review.)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    # Required. From BotFather. The app refuses to start without it.
    telegram_bot_token: str

    # Optional. Your own cloud LLM key (Claude / OpenAI). Used for non-Ollama models.
    llm_api_key: str | None = None

    # Optional. Google Maps/Places key. Without it we fall back to OpenStreetMap.
    google_maps_api_key: str | None = None

    # Off by default. When true, ingest may download videos (your own responsibility, see ToS).
    video_fetch: bool = False

    # Set RUN_BOT=false to start only the web API (used by tests and Docker smoke checks).
    run_bot: bool = True

    # --- M1 settings (spec: docs/superpowers/specs/2026-10-04-m1-save-from-captions-design.md) ---

    # Where the SQLite database lives. The ./data folder is a Docker volume.
    database_url: str = "sqlite:///data/travelkaki.db"

    # LLM used to pull places out of captions. Local Ollama by default (free, no key).
    # Any LiteLLM model string works, e.g. "anthropic/claude-haiku-4-5".
    extract_model: str = "ollama_chat/qwen3:4b-instruct"

    # Optional cloud model, tried once if the local model fails. Empty = no fallback.
    extract_fallback_model: str | None = None

    # How the Docker container reaches Ollama running on the host (Docker Desktop).
    ollama_base_url: str = "http://host.docker.internal:11434"

    # Max LLM calls per trip per day (retries and fallback calls count too).
    llm_daily_cap: int = 100

    # Optional contact email for OpenStreetMap Nominatim (their usage policy asks for one).
    nominatim_email: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Load settings once and reuse them (cached)."""
    return Settings()
