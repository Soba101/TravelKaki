"""Tests for the LLM client and the daily cap (issue #11). No real LLM: fakes only."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from travelkaki.config import Settings
from travelkaki.db import queries
from travelkaki.llm.cap import CapReached, make_counter
from travelkaki.llm.client import LlmClient, LlmUnavailable

MESSAGES = [{"role": "user", "content": "hi"}]
SCHEMA = {"type": "object"}


def _settings(**kw):
    return Settings(_env_file=None, telegram_bot_token="x:y", llm_api_key="sk-test", **kw)


def _reply(content: str):
    """Shape of a LiteLLM response: response.choices[0].message.content."""
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _client(completion, **kw):
    sleep = AsyncMock()
    return LlmClient(_settings(**kw), completion=completion, sleep=sleep), sleep


async def test_returns_parsed_json():
    completion = AsyncMock(return_value=_reply('{"places": []}'))
    client, _ = _client(completion)
    on_call = Mock()

    assert await client.extract_json(MESSAGES, SCHEMA, on_call) == {"places": []}

    kwargs = completion.await_args.kwargs
    assert kwargs["model"] == "ollama_chat/qwen3:4b-instruct"
    assert kwargs["api_base"] == "http://host.docker.internal:11434"  # Ollama gets api_base
    assert "api_key" not in kwargs  # ...and never the cloud key
    assert kwargs["response_format"]["json_schema"]["schema"] == SCHEMA
    assert kwargs["timeout"] == 60 and kwargs["temperature"] == 0
    on_call.assert_called_once()


async def test_retries_then_fallback():
    completion = AsyncMock(
        side_effect=[ConnectionError("down"), _reply("not json"), _reply('{"ok": 1}')]
    )
    client, sleep = _client(completion, extract_fallback_model="anthropic/claude-haiku-4-5")
    on_call = Mock()

    assert await client.extract_json(MESSAGES, SCHEMA, on_call) == {"ok": 1}

    models = [c.kwargs["model"] for c in completion.await_args_list]
    assert models == ["ollama_chat/qwen3:4b-instruct"] * 2 + ["anthropic/claude-haiku-4-5"]
    assert completion.await_args_list[2].kwargs["api_key"] == "sk-test"  # cloud gets the key
    assert [c.args[0] for c in sleep.await_args_list] == [1, 3]
    assert on_call.call_count == 3  # every try counts toward the cap


async def test_no_fallback_raises_unavailable():
    completion = AsyncMock(return_value=_reply("not json"))
    client, _ = _client(completion)
    with pytest.raises(LlmUnavailable):
        await client.extract_json(MESSAGES, SCHEMA, Mock())
    assert completion.await_count == 2


async def test_cap_reached_propagates():
    completion = AsyncMock()
    client, _ = _client(completion)
    with pytest.raises(CapReached):
        await client.extract_json(MESSAGES, SCHEMA, Mock(side_effect=CapReached()))
    completion.assert_not_awaited()


def test_cap_stops_calls(sessions):
    with sessions() as s:
        trip = queries.upsert_trip(s, chat_id=1, city="Tokyo", start=None, end=None, hotel=None)
    day = [date(2026, 10, 4)]
    count = make_counter(sessions, trip.id, cap=2, today=lambda: day[0])

    count()
    count()
    with pytest.raises(CapReached):
        count()
    day[0] = date(2026, 10, 5)  # a new day resets the count
    count()


async def test_wrong_shape_answer_is_retried_then_falls_back():
    # Valid JSON but the wrong shape must count as a failed try, so the
    # 2nd try and the cloud fallback still run. (PR2 review)
    completion = AsyncMock(
        side_effect=[_reply('{"wrong": 1}'), _reply('{"wrong": 2}'), _reply('{"ok": 1}')]
    )
    client, _ = _client(completion, extract_fallback_model="anthropic/claude-haiku-4-5")

    def validate(raw):
        if "ok" not in raw:
            raise ValueError("bad shape")
        return raw["ok"]

    assert await client.extract_json(MESSAGES, SCHEMA, Mock(), validate=validate) == 1
    assert completion.await_count == 3


async def test_answer_length_is_limited():
    # A runaway local model must stop: max_tokens is always sent. (PR2 review)
    completion = AsyncMock(return_value=_reply("{}"))
    client, _ = _client(completion)
    await client.extract_json(MESSAGES, SCHEMA, Mock())
    assert completion.await_args.kwargs["max_tokens"] == 1500


def test_litellm_uses_local_cost_map(monkeypatch):
    # LiteLLM downloads a price list on import unless told not to. No network at startup/CI.
    monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)
    import os

    LlmClient(_settings())  # real import path (completion=None)
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
