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
