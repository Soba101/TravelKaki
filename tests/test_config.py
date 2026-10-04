"""Tests for travelkaki.config: settings are read from env vars / .env."""

import pytest
from pydantic import ValidationError

from travelkaki.config import Settings


def test_missing_token_raises_clear_error(monkeypatch):
    # No token anywhere -> settings must refuse to load.
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ValidationError, match="(?i)telegram_bot_token"):
        Settings(_env_file=None)  # _env_file=None: ignore any real .env on disk


def test_reads_token_and_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    s = Settings(_env_file=None)
    assert s.telegram_bot_token == "123:abc"
    # Optional settings have safe defaults.
    assert s.video_fetch is False
    assert s.run_bot is True
    assert s.llm_api_key is None


def test_m1_defaults(monkeypatch):
    # M1 settings: local LLM first, SQLite in ./data, daily cap of 100 LLM calls per trip.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    s = Settings(_env_file=None)
    assert s.database_url == "sqlite:///data/travelkaki.db"
    assert s.extract_model == "ollama_chat/qwen3:4b-instruct"
    assert s.extract_fallback_model is None
    assert s.ollama_base_url == "http://host.docker.internal:11434"
    assert s.llm_daily_cap == 100
    assert s.nominatim_email is None


def test_empty_env_values_mean_unset(monkeypatch):
    # .env.example has lines like `EXTRACT_FALLBACK_MODEL=`. Empty must mean "not set",
    # not the model name "". (Found in PR1 review.)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    s = Settings(_env_file=".env.example")
    assert s.extract_fallback_model is None
    assert s.llm_api_key is None
    assert s.nominatim_email is None
    assert s.llm_daily_cap == 100


def test_plan_defaults(monkeypatch):
    """M2: the planner model is local by default, with no fallback."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    s = Settings(_env_file=None)
    assert s.plan_model == "ollama_chat/qwen3:4b-instruct"
    assert s.plan_fallback_model is None
