"""Tests for group -> supergroup migration (the chat id changes)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.fakes import make_deps
from travelkaki.bot import trip as trip_bot
from travelkaki.db import queries

OLD, NEW = -5165068643, -1004452095260


def test_migrate_trip_moves_chat_id(sessions):
    with sessions() as s:
        queries.upsert_trip(s, OLD, "Tokyo", None, None, None)
        assert queries.migrate_trip(s, OLD, NEW) is True
        assert queries.get_trip(s, OLD) is None
        assert queries.get_trip(s, NEW).city == "Tokyo"


def test_migrate_trip_is_idempotent(sessions):
    with sessions() as s:
        queries.upsert_trip(s, OLD, "Tokyo", None, None, None)
        queries.migrate_trip(s, OLD, NEW)
        assert queries.migrate_trip(s, OLD, NEW) is False  # nothing left to move
        assert queries.get_trip(s, NEW).city == "Tokyo"


def test_migrate_trip_without_trip_or_when_new_exists(sessions):
    with sessions() as s:
        assert queries.migrate_trip(s, OLD, NEW) is False
        queries.upsert_trip(s, OLD, "Tokyo", None, None, None)
        queries.upsert_trip(s, NEW, "Paris", None, None, None)
        assert queries.migrate_trip(s, OLD, NEW) is False  # never clobber a trip
        assert queries.get_trip(s, OLD).city == "Tokyo"


def _update(chat_id, to=None, frm=None):
    msg = SimpleNamespace(migrate_to_chat_id=to, migrate_from_chat_id=frm)
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), effective_message=msg)


async def test_handler_on_old_chat_message(sessions):
    with sessions() as s:
        queries.upsert_trip(s, OLD, "Tokyo", None, None, None)
    ctx = SimpleNamespace(
        bot_data={"deps": make_deps(sessions)}, bot=SimpleNamespace(send_message=AsyncMock())
    )
    await trip_bot.on_migrate(_update(OLD, to=NEW), ctx)
    with sessions() as s:
        assert queries.get_trip(s, NEW).city == "Tokyo"


async def test_handler_on_new_chat_message(sessions):
    with sessions() as s:
        queries.upsert_trip(s, OLD, "Tokyo", None, None, None)
    ctx = SimpleNamespace(
        bot_data={"deps": make_deps(sessions)}, bot=SimpleNamespace(send_message=AsyncMock())
    )
    await trip_bot.on_migrate(_update(NEW, frm=OLD), ctx)
    await trip_bot.on_migrate(_update(OLD, to=NEW), ctx)  # both messages arrive: still fine
    with sessions() as s:
        assert queries.get_trip(s, NEW).city == "Tokyo"
